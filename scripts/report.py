"""
Mail a check's result, and treat "no result" as the loudest result of all.

Every check in this repo writes a JSON summary:
    {"suite": "Site check", "ok": false, "problems": ["...", ...], "measured": {...}}
This step runs `if: always()` and reads it. Three cases, none of them quiet:

- summary present, ok=false  -> mail, subject names the first problem, exit 1
- summary present, ok=true   -> no mail, exit 0
- summary MISSING            -> mail "the check never ran", exit 1

The third case is the whole reason this file lives in the PUBLIC repo rather
than next to the checks. On 2026-09-23 every run of this repo for ten days had
died at the private checkout with "Input required and not supplied: token",
and every step after it was skipped, including any mail step that lived
downstream. A mailer that depends on the code checkout dies with it. This one
needs nothing but stdlib and two secrets, so a failed checkout still produces
a mail saying so.

A missing RESEND_API_KEY or ALERT_EMAIL is also a failure, never a skip. A
check that disables itself when unconfigured reports health it never measured.
This repo is public, so there is no fallback address to print here.

Step outcomes arrive as STEPS_JSON (the workflow passes `${{ toJSON(steps) }}`),
so a missing summary names the step that actually failed instead of guessing.
With no --summary at all, the result is built from the step outcomes alone,
which is how the build checks report: they print text, their steps pass or fail.

Subject: "[FlixShows] <suite>: <first problem>" (+N more). Product and issue
read from the subject line without opening the mail; a bare count does not.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PRODUCT = "FlixShows"

# What a failed step MEANS, so the mail says what to do rather than "failure".
HINTS = {
    "require-secrets": "repository secrets are missing on GirisankarG/stream-site-ci "
                       "(Settings > Secrets and variables > Actions), so nothing ran",
    "checkout-code": "could not check out akv2011/stream-site: the CODE_REPO_PAT secret "
                     "is missing, expired, or lacks Contents: read on that repo. Nothing ran.",
    "tests": "the checker's own mutation tests failed, so its detectors cannot be trusted "
             "and the live check was not run",
    "install": "dependency install failed, nothing was checked",
    "drift": "the live site is not built from the pushed code (titles in the run log); "
             "push akv2011/stream-site so these checks test what readers are served",
    "crawl": "the source did not answer this runner, which is what a datacenter IP being "
             "walled looks like. Not measured: this is NOT 'no new titles'",
    "discover": "discovery could not compare the source with the site",
}


def _steps_raw() -> dict:
    raw = os.environ.get("STEPS_JSON", "")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {"steps-json": {"outcome": "unparseable"}}
    except json.JSONDecodeError:
        return {"steps-json": {"outcome": "unparseable"}}


def step_outcomes() -> dict[str, str]:
    """{step_id: outcome} from STEPS_JSON, in workflow order."""
    return {k: (v or {}).get("outcome", "?") for k, v in _steps_raw().items()}


def failed_steps(steps: dict[str, str]) -> list[str]:
    """Each real failure by name; steps merely SKIPPED because of it collapse into one
    line, so the subject names the cause instead of "(+6 more)" of consequences."""
    raw = _steps_raw()
    out, skipped = [], []
    for sid, outcome in steps.items():
        if outcome == "success":
            continue
        if outcome == "skipped":
            skipped.append(sid)
            continue
        line = f"step {sid}: {outcome}"
        missing = ((raw.get(sid) or {}).get("outputs") or {}).get("missing", "")
        if missing:
            line += f", not set: {missing}"
        if sid in HINTS:
            line += f". {HINTS[sid]}"
        out.append(line)
    if skipped:
        out.append(f"{len(skipped)} later step(s) skipped as a result: {', '.join(skipped)}")
    return out


def load_summary(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        return {"suite": "?", "ok": False,
                "problems": [f"summary at {path} is not valid JSON: {e}"], "measured": {}}
    if not isinstance(d, dict) or "ok" not in d or "problems" not in d:
        return {"suite": str(d.get("suite", "?")) if isinstance(d, dict) else "?", "ok": False,
                "problems": [f"summary at {path} lacks ok/problems keys"], "measured": {}}
    return d


def subject_for(suite: str, problems: list[str]) -> str:
    head = problems[0][:110] if problems else "ok"
    more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
    return f"[{PRODUCT}] {suite}: {head}{more}"


def html_body(suite: str, problems: list[str], measured: dict, run_url: str,
              notice: bool = False) -> str:
    esc = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    items = "".join(f"<li>{esc(p)}</li>" for p in problems)
    meas = "".join(f"<li><code>{esc(k)}</code> = {esc(v)}</li>" for k, v in measured.items())
    head = (f"{esc(PRODUCT)}: {esc(suite)}" if notice
            else f"{esc(PRODUCT)}: {esc(suite)} found {len(problems)} problem(s)")
    return (f"<h2>{head}</h2>"
            f"<ul>{items}</ul>"
            f"<p>Measured:</p><ul>{meas or '<li>(nothing measured)</li>'}</ul>"
            f"<p><a href=\"{esc(run_url)}\">Run log</a></p>")


def send(subject: str, html: str) -> bool:
    key = os.environ.get("RESEND_API_KEY", "")
    to = os.environ.get("ALERT_EMAIL", "")
    sender = os.environ.get("ALERT_FROM", "")
    missing = [n for n, v in (("RESEND_API_KEY", key), ("ALERT_EMAIL", to), ("ALERT_FROM", sender)) if not v]
    if missing:
        print(f"[report] cannot mail: missing {', '.join(missing)}. UNSENT: {subject}")
        return False
    payload = json.dumps({"from": sender, "to": [to], "subject": subject, "html": html}).encode()
    last = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "https://api.resend.com/emails", data=payload, method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         # Resend 403s urllib's default UA (error 1010).
                         "User-Agent": "flixshows-ci-report/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status < 400:
                    print("[report] emailed")      # never print the address in a public log
                    return True
                last = f"Resend {r.status}"
        except urllib.error.HTTPError as e:
            last = f"Resend {e.code}: {e.read()[:200]!r}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:                       # noqa: BLE001
            last = f"request error: {e}"
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    print(f"[report] EMAIL FAILED: {last}. UNSENT: {subject}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="", help="JSON written by the check; omit to "
                    "judge from step outcomes alone")
    ap.add_argument("--suite", required=True, help='e.g. "Site check"; goes in the subject')
    ap.add_argument("--dry-run", action="store_true", help="print, never send")
    ap.add_argument("--private-detail", action="store_true",
                    help="log counts only; the problems themselves go to the mail alone. "
                         "For checks whose findings name a source or its URLs, since this "
                         "repo's logs are public")
    a = ap.parse_args()

    run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
               f"{os.environ.get('GITHUB_RUN_ID', '')}")

    steps = step_outcomes()
    bad_steps = failed_steps(steps)
    if not a.summary:
        # Build checks: the step outcomes ARE the result.
        s = {"suite": a.suite, "ok": bool(steps) and not bad_steps, "measured": steps,
             "problems": bad_steps or ([] if steps else
                         ["no step outcomes were passed (STEPS_JSON empty), so nothing "
                          "can be said about whether anything ran"])}
    else:
        s = load_summary(a.summary)
        if s is None:
            why = (bad_steps[0] if bad_steps else
                   "every step reported success but no summary was written")
            s = {"suite": a.suite, "ok": False, "measured": steps,
                 "problems": [f"{why}. {a.suite} never reached its own assertions, "
                              "so nothing was measured."]}

    suite = s.get("suite") or a.suite
    problems = [str(p) for p in s.get("problems", [])]
    notify = [str(n) for n in s.get("notify", [])]
    if s.get("ok") and not problems and notify:
        # Green, but worth hearing: e.g. discovery's "3 new titles since the last
        # run". Mailed, and the run stays green, because nothing is broken.
        subject = subject_for(suite, notify)
        if a.private_detail:
            print(f"[report] {suite}: notification ({len(notify)} line(s)), detail in the mail only")
        else:
            print(f"[report] notify: {subject}")
        if not a.dry_run and not send(subject, html_body(suite, notify, s.get("measured", {}),
                                                         run_url, notice=True)):
            return 1   # a notification nobody can receive is a failure, not a success
        return 0
    if s.get("ok") and not problems:
        print(f"[report] {suite}: ok, nothing to mail")
        return 0

    subject = subject_for(suite, problems)
    if a.private_detail:
        # The subject carries the first problem too, so it stays out of the log.
        print(f"[report] {suite}: {len(problems)} problem(s), detail in the mail only")
    else:
        print(f"[report] subject: {subject}")
        for p in problems:
            print(f"  - {p}")
    if a.dry_run:
        print("[report] dry run, not sent")
        return 1
    send(subject, html_body(suite, problems, s.get("measured", {}), run_url))
    return 1                       # red is the signal that persists if the mail fails


if __name__ == "__main__":
    sys.exit(main())
