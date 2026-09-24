"""
Did every scheduled check in this repo actually RUN, recently, as far as its
own assertions? And keep the schedules from being switched off.

Two ways a check here dies without saying so, both already seen:

1. The run exists and is red or green, but its probe step never executed.
   From 2026-09-13 to 09-23 every run of checks.yml died at the private
   checkout, and on the sister site a skipped job hid for four days behind a
   green sibling. So this reads each workflow's latest run down to the STEP
   LIST and requires the named probe step to have concluded success or
   failure. Skipped, cancelled or null means the code was never reached,
   whatever colour the run badge is.

2. GitHub's docs: "In a public repository, scheduled workflows are
   automatically disabled when no repository activity has occurred in 60
   days." This repo holds no code and is rarely pushed, so every schedule in
   it, this one included, would stop silently. Each run calls the workflow
   enable endpoint for every workflow here (the approach gh-workflow-keepalive
   uses, with no dummy commits). Whether that resets the 60-day timer is NOT
   documented, so this is belt only: a watchdog cannot report its own
   disablement, and the braces have to be a watch from outside this repo.

Judged by LAST RUN, never last success: a checker that goes red has worked.
Uses only the default GITHUB_TOKEN of this repo (actions: write).

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo python scripts/watchdog.py --summary s.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

# workflow file -> (NAME of the step that proves the code was reached, max hours
# since the last run). The step is the FIRST real check, not the last: if the
# build fails, the later checks are skipped as a result, and that is a finding
# for the report, not a run that "never happened". Limits allow for GitHub
# delivering only about half the scheduled runs under load (6-7 of 13
# requested, measured on the sister site 2026-09-20).
WATCHED = {
    "live-check.yml": ("Check the live site", 8),
    "checks.yml": ("Build", 50),
}
KEEPALIVE = ["live-check.yml", "checks.yml", "watchdog.yml"]


def api(method: str, path: str) -> tuple[int, object]:
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", method=method,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "flixshows-ci-watchdog/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def judge(wf: str, step_name: str, limit_h: float, run: dict | None,
          steps: list[dict] | None, now: dt.datetime) -> list[str]:
    """Pure: problems for one workflow given its latest run and that run's steps."""
    if run is None:
        return [f"{wf}: no run on record at all, it has never been scheduled or dispatched"]
    started = dt.datetime.strptime(run["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc)
    age_h = (now - started).total_seconds() / 3600
    probs = []
    if age_h > limit_h:
        probs.append(f"{wf}: last run {age_h:.1f}h ago, limit {limit_h:.0f}h. It has stopped "
                     "being scheduled (GitHub disables public-repo schedules after 60 days "
                     "without activity) or its runs are being dropped")
    if run.get("status") != "completed":
        return probs          # still running or queued: the step list is not final yet
    names = {s.get("name", ""): s.get("conclusion") for s in (steps or [])}
    hit = [c for n, c in names.items() if n == step_name]
    if not hit:
        probs.append(f"{wf}: latest run has no step named {step_name!r}; the workflow "
                     "was renamed or restructured and this watchdog must be updated")
    elif hit[0] not in ("success", "failure"):
        probs.append(f"{wf}: latest run never reached its {step_name!r} step "
                     f"(conclusion {hit[0]!r}), so nothing was measured whatever the badge says")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    P: list[str] = []
    M: dict = {}

    for wf, (step, limit) in WATCHED.items():
        code, data = api("GET", f"/actions/workflows/{wf}/runs?per_page=1&exclude_pull_requests=true")
        if code == 404:
            P.append(f"{wf}: workflow file not found in this repo, coverage was removed")
            continue
        if code != 200:
            P.append(f"{wf}: could not list runs (HTTP {code}), so its health is unknown")
            continue
        runs = (data or {}).get("workflow_runs") or []
        run = runs[0] if runs else None
        steps = None
        if run and run.get("status") == "completed":
            c2, jobs = api("GET", f"/actions/runs/{run['id']}/jobs")
            if c2 != 200:
                P.append(f"{wf}: could not read the job steps of run {run['id']} (HTTP {c2})")
                continue
            steps = [s for j in (jobs or {}).get("jobs", []) for s in j.get("steps", [])]
        P += judge(wf, step, limit, run, steps, now)
        M[wf] = (f"last run {run['created_at']} {run.get('conclusion')}" if run else "never")

    for wf in KEEPALIVE:
        # GitHub records the 60-day rule only here: state becomes
        # "disabled_inactivity" and nothing else announces it.
        c0, meta = api("GET", f"/actions/workflows/{wf}")
        wstate = (meta or {}).get("state", f"unknown (HTTP {c0})")
        M[f"state {wf}"] = wstate
        if c0 == 200 and wstate != "active":
            P.append(f"{wf} was {wstate}; re-enabling it now. If this says disabled_inactivity, "
                     "the keepalive did not stop GitHub's 60-day rule and an outside watch is needed")
        code, _ = api("PUT", f"/actions/workflows/{wf}/enable")
        M[f"keepalive {wf}"] = code
        if code not in (200, 204):
            P.append(f"keepalive: could not re-enable {wf} (HTTP {code}); its schedule may be "
                     "disabled after 60 days without repo activity")

    out = {"suite": "Watchdog", "ok": not P, "problems": P, "measured": M}
    with open(a.summary, "w") as f:
        json.dump(out, f, indent=2)
    for k, v in M.items():
        print(f"  {k:<28} {v}")
    for p in P:
        print(f"  PROBLEM {p}")
    print("OK" if not P else f"FAILED: {len(P)} problem(s)")
    return 0 if not P else 1


if __name__ == "__main__":
    sys.exit(main())
