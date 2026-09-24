"""
Is the live site built from the code CI just tested?

Deploys run from a laptop (deploy.sh), not from git. On 2026-09-24 the live
site carried 13,631 titles and the pushed code 13,538: 98 titles were live that
existed in no pushed commit, and the oldest unpushed commit was 10 days old. So
checks.yml, which builds origin/main, was testing a site nobody was serving,
and the live one existed on one disk.

This compares the search index CI just built from origin/main with the one the
live site serves, as SETS of slugs. Built from the deployed code the two match
exactly (measured: 13,631 and 13,631, 0 difference either way), so any
difference is real drift, and the direction says which kind:

- live but not built: deployed from unpushed work. CI is testing stale code and
  that work is not backed up. The dangerous direction.
- built but not live: pushed but not deployed. Normal for the hour between the
  two, a forgotten deploy if it persists.

Counts and a few slugs only; slugs are this site's own public URLs.

    python scripts/drift_check.py --built code/dist/search-index.json \\
        --live https://flixshows.me/search-index.json --summary drift.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def slugs(entries: list) -> set[str]:
    return {e["s"] for e in entries if isinstance(e, dict) and e.get("s")}


def judge(built: list, live: list) -> tuple[list[str], dict]:
    """Pure: problems and counts for two search indexes."""
    b, l = slugs(built), slugs(live)
    M = {"built_titles": len(b), "live_titles": len(l),
         "live_not_pushed": len(l - b), "pushed_not_live": len(b - l)}
    P = []
    if not b or not l:
        P.append(f"an index is empty (built {len(b)}, live {len(l)}), so drift could not be measured")
        return P, M
    if l - b:
        P.append(f"{len(l - b)} titles are live that the pushed code does not build, e.g. "
                 f"{sorted(l - b)[:5]}: the site was deployed from unpushed work, so these checks "
                 "tested stale code and that work is not backed up. Push akv2011/stream-site")
    if b - l:
        P.append(f"{len(b - l)} titles in the pushed code are not live, e.g. {sorted(b - l)[:5]}: "
                 "pushed but not deployed")
    return P, M


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--built", required=True)
    ap.add_argument("--live", required=True)
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    try:
        built = json.loads(Path(a.built).read_text())
        req = urllib.request.Request(a.live, headers={"User-Agent": "flixshows-ci-drift/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            live = json.loads(r.read())
        P, M = judge(built, live)
    except Exception as e:                                        # noqa: BLE001
        P, M = [f"drift check could not measure: {type(e).__name__}: {e}"], {}
    Path(a.summary).write_text(json.dumps(
        {"suite": "Build checks", "ok": not P, "problems": P, "measured": M}, indent=2))
    for k, v in M.items():
        print(f"  {k:<18} {v}")
    for p in P:
        print(f"  PROBLEM {p}")
    return 0 if not P else 1


if __name__ == "__main__":
    sys.exit(main())
