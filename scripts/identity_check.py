"""
Build-time completeness of the sitemap, as an identity with no threshold:

    watch pages built  -  watch pages marked noindex  ==  watch URLs in the sitemap

Exact by construction, so it has no tuning knob to loosen: both sides move
together whenever a stream host dies and titles fall below the indexing bar.
A count that went down because fewer titles qualified satisfies it; a sitemap
that dropped URLs while their pages stayed indexable does not. Measured on the
deployed build 2026-09-27: 13,631 - 5,433 = 8,198 = 8,198.

    python scripts/identity_check.py --dist code/dist --summary identity.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_NOINDEX = re.compile(r'<meta name="robots" content="[^"]*noindex', re.I)
_WATCH_LOC = re.compile(r"<loc>[^<]*/watch/[^<]*</loc>")


def judge(built: int, noindex: int, in_sitemap: int) -> list[str]:
    if built == 0:
        return ["the build produced 0 watch pages, so the identity measured nothing"]
    if built - noindex != in_sitemap:
        return [f"sitemap identity broken: {built} watch pages built - {noindex} noindex = "
                f"{built - noindex}, but the sitemap lists {in_sitemap} watch URLs "
                f"({in_sitemap - (built - noindex):+d}). The sitemap and the pages' robots tags "
                "disagree about what is indexable"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    d = Path(a.dist)
    pages = sorted((d / "watch").glob("*.html"))
    noindex = sum(1 for p in pages if _NOINDEX.search(p.read_text(errors="replace")[:4000]))
    sm = d / "sitemap.xml"
    in_sitemap = len(_WATCH_LOC.findall(sm.read_text())) if sm.exists() else 0
    P = judge(len(pages), noindex, in_sitemap) if sm.exists() else ["the build wrote no sitemap.xml"]
    M = {"watch_built": len(pages), "watch_noindex": noindex, "watch_in_sitemap": in_sitemap}
    Path(a.summary).write_text(json.dumps({"suite": "Build checks", "ok": not P,
                                           "problems": P, "measured": M}, indent=2))
    for k, v in M.items():
        print(f"  {k:<18} {v}")
    for p in P:
        print(f"  PROBLEM {p}")
    return 0 if not P else 1


if __name__ == "__main__":
    sys.exit(main())
