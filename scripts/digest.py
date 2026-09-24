"""
Turn discovery's backlog into "what is NEW since the last run", so the mail is
a notification Arun acts on rather than a red run he learns to ignore.

Discovery (stream-site/scripts/coverage_check.py) reports the whole backlog
every day: titles the source has and we do not, series the source has more
episodes of than we carry, and so on. On 2026-09-24 that was 99 new titles and
338 series behind by 2,893 episodes. Mailed daily as-is, the same 400 lines
arrive every morning until someone ingests them, and a mail that says the same
thing every day gets filtered. So this compares today's findings with the
previous run's, by stable id, and reports only what moved.

Three outcomes, none of them quiet about a failure:
- discovery could not measure (its "problems"): red, mailed, and the previous
  state is kept, because an untrustworthy run must not become the baseline.
- something new appeared: green, mailed as a notification.
- nothing new: green, silent.

The first run, and any run whose cached state was evicted (the Actions cache
drops entries unused for 7 days), has nothing to compare with. It says so and
reports the whole backlog as a baseline instead of calling all of it new.

Not built on purpose: a "backlog stalled" red. Ingestion is manual today, so
"nothing ingested in 7 days" is a choice, not a fault. Add it when ingestion is
automated, keyed on nothing leaving the backlog while new items arrive.

Findings contract (coverage_check.py --summary):
    "findings": {"missing_ingestable": [{"id", "title"}],
                 "behind_on_episodes": [{"id", "title", "have", "source"}],
                 "disappeared": [{"id", "title"}],
                 "tmdb_missing": [{"tmdb_id", "title", "kind"}]}

    python scripts/digest.py --discovery summary.json --state state/state.json --out report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KINDS = ("missing_ingestable", "behind_on_episodes", "disappeared", "tmdb_missing")
LABEL = {
    "missing_ingestable": "new source title(s) with episodes, not on the site",
    "behind_on_episodes": "series gained episodes we do not carry",
    "disappeared": "title(s) we carry are no longer listed by the source",
    "tmdb_missing": "recent TMDB release(s) not carried",
}
MAX_LINES = 15      # per kind in the mail; the counts carry the rest


def _key(kind: str, item: dict) -> str:
    return str(item.get("tmdb_id") if kind == "tmdb_missing" else item.get("id"))


def diff(prev: dict | None, findings: dict) -> tuple[dict, dict]:
    """Pure. Returns ({kind: [new items]}, next_state).

    An item is new if its id was not in the previous run's set. For series
    behind on episodes it is also new when the source count has GROWN since,
    because another episode landing on a series we already knew was behind is
    exactly the event worth hearing about.
    """
    prev_seen = (prev or {}).get("seen", {})
    new: dict[str, list[dict]] = {}
    seen: dict[str, dict] = {}
    for kind in KINDS:
        items = findings.get(kind) or []
        before = prev_seen.get(kind, {})
        now = {}
        fresh = []
        for it in items:
            k = _key(kind, it)
            val = int(it.get("source") or 0) if kind == "behind_on_episodes" else 1
            now[k] = val
            if k not in before or (kind == "behind_on_episodes" and val > int(before[k])):
                fresh.append(it)
        new[kind] = fresh
        seen[kind] = now
    return new, {"seen": seen}


def _line(kind: str, it: dict) -> str:
    t = it.get("title", "?")
    if kind == "behind_on_episodes":
        return f"{t}: we have {it.get('have')}, source has {it.get('source')}"
    if kind == "tmdb_missing":
        return f"{t} ({it.get('kind', '?')}, tmdb {it.get('tmdb_id')})"
    return str(t)


def build_report(summary: dict, prev: dict | None) -> tuple[dict, dict | None]:
    """Pure. (report for report.py, state to save or None to keep the old one)."""
    if summary.get("problems"):
        return ({"suite": "Discovery", "ok": False, "problems": summary["problems"],
                 "measured": summary.get("measured", {})}, None)
    findings = summary.get("findings")
    if not isinstance(findings, dict):
        return ({"suite": "Discovery", "ok": False, "measured": summary.get("measured", {}),
                 "problems": ["discovery summary has no 'findings' object, so nothing new can "
                              "be told apart from the standing backlog; the checker's output "
                              "contract changed"]}, None)

    new, state = diff(prev, findings)
    total_new = sum(len(v) for v in new.values())
    measured = dict(summary.get("measured", {}))
    measured.update({f"new_{k}": len(v) for k, v in new.items()})
    baseline = prev is None

    if total_new == 0:
        return {"suite": "Discovery", "ok": True, "problems": [], "notify": [],
                "measured": measured}, state

    parts = [f"{len(new[k])} {LABEL[k]}" for k in KINDS if new[k]]
    head = ("first run, backlog baseline: " if baseline else "since the last run: ") + ", ".join(parts)
    lines = [head]
    for k in KINDS:
        if not new[k]:
            continue
        lines.append(f"{LABEL[k]} ({len(new[k])}):")
        lines += [f"  {_line(k, it)}" for it in new[k][:MAX_LINES]]
        if len(new[k]) > MAX_LINES:
            lines.append(f"  ...and {len(new[k]) - MAX_LINES} more")
    return {"suite": "Discovery", "ok": True, "problems": [], "notify": lines,
            "measured": measured}, state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discovery", required=True, help="coverage_check.py --summary output")
    ap.add_argument("--state", required=True, help="previous state, read then overwritten")
    ap.add_argument("--out", required=True, help="report summary for report.py")
    a = ap.parse_args()

    dpath, spath = Path(a.discovery), Path(a.state)
    if not dpath.exists():
        report = {"suite": "Discovery", "ok": False, "measured": {},
                  "problems": ["discovery wrote no summary, so it never reached its own "
                               "measurement"]}
        state = None
    else:
        try:
            summary = json.loads(dpath.read_text())
        except json.JSONDecodeError as e:
            summary = {"problems": [f"discovery summary is not valid JSON: {e}"]}
        prev = json.loads(spath.read_text()) if spath.exists() else None
        report, state = build_report(summary, prev)

    Path(a.out).write_text(json.dumps(report, indent=2))
    if state is not None:
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(json.dumps(state))

    # Counts only: this repo's logs are public and the findings name the source.
    for k, v in report.get("measured", {}).items():
        print(f"  {k:<28} {v}")
    print(f"digest: ok={report['ok']} problems={len(report.get('problems', []))} "
          f"notify_lines={len(report.get('notify', []))} "
          f"state={'saved' if state is not None else 'KEPT previous'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
