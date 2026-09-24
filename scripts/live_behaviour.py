"""
Do the interactive features actually WORK on the served flixshows.me, in a real
browser, rather than merely exist in the build?

Every behaviour check before this ran against dist/ on a laptop, never against
the live site, so a deploy that shipped a stale or partial build passed them all.
And the failure these catch has already shipped twice, dead and green: the hero
trailer, and every carousel arrow, both queried the DOM before their markup
existed, wired nothing, threw nothing, and looked fine. So this asserts the
EFFECT each feature leaves behind, never that its setup ran:

- every rail with arrows carries data-railed="1" (set by the rail script at
  runtime, absent from the HTML, so only a browser can see it), and there is at
  least one rail, or an empty page would pass
- clicking a right arrow moves the track by WHOLE cards: scrollLeft > 0 alone
  once passed while the arrow scrolled 90% of a viewport and left a half card
  against the edge, so the landing position must be a multiple of the card pitch
- every scrollable rail has dots, and starts with its left arrow disabled; both
  were wrong for the entire time the rails were inert, so either catches it
- search returns results for a title we carry
- no uncaught page error on the home or a watch page
- a watch page has no iframe before a click: players mount only on a gesture

Measured on the live site 2026-09-24: 17 rails, 0 unwired, arrow landed at 1316
= 7 x 188, 14 scrollable rails all with dots and a disabled left arrow, 13
results for "breaking", 0 page errors, 0 iframes before click. Selectors are
taken from the served HTML, not from a description of it: a guessed selector
produces a false failure that looks exactly like a real one (search results
are `#results a`; `role=option` matches nothing).

Deliberately NOT asserted: that a video plays. That is a third party's answer,
and from a datacenter IP a provider may serve a challenge instead, which would
make this check red for a reason that is not ours.

    python scripts/live_behaviour.py --summary behaviour.json
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

SITE = "https://flixshows.me"
WATCH = f"{SITE}/watch/iron-man-2008"
QUERY = "breaking"
VIEWPORT = {"width": 1366, "height": 900}

RAILS_JS = """() => {
  const rails = [...document.querySelectorAll('section.rail')].filter(s => s.querySelector('.arw'));
  const scroll = rails.filter(s => { const t = s.querySelector('.track');
                                     return t && t.scrollWidth > t.clientWidth + 2; });
  return {
    rails: rails.length,
    unwired: rails.filter(s => !s.dataset.railed).length,
    scrollable: scroll.length,
    dots_empty: scroll.filter(s => !s.querySelectorAll('.dots i').length).length,
    left_enabled_at_start: scroll.filter(s => {
      const t = s.querySelector('.track'), a = s.querySelectorAll('.arw')[0];
      return t.scrollLeft === 0 && a && !a.disabled; }).length,
  };
}"""

STEP_JS = """async () => {
  const s = [...document.querySelectorAll('section.rail')].find(x => {
    const t = x.querySelector('.track');
    return t && t.scrollWidth > t.clientWidth + 2 && x.querySelectorAll('.card').length > 2; });
  if (!s) return null;
  const t = s.querySelector('.track'), c = t.querySelectorAll('.card');
  const pitch = c[1].offsetLeft - c[0].offsetLeft;
  s.querySelectorAll('.arw')[1].click();
  let last = -1;
  for (let i = 0; i < 30; i++) {           // wait for the smooth scroll to settle
    await new Promise(r => setTimeout(r, 100));
    if (t.scrollLeft > 0 && t.scrollLeft === last) break;
    last = t.scrollLeft;
  }
  return {pitch, scrollLeft: t.scrollLeft};
}"""


def judge(m: dict) -> list[str]:
    """Pure: problems from the raw measurements."""
    P = []
    for page, title in (("home", m.get("home_title", "")), ("watch", m.get("watch_title", ""))):
        if "just a moment" in title.lower() or "attention required" in title.lower():
            return [f"{page} page: UNVERIFIED from the CI runner, served a challenge page; "
                    "nothing about the site's behaviour was measured"]
    r = m.get("rails") or {}
    if not r.get("rails"):
        P.append("home page has 0 rails with arrows, so no carousel was checked at all")
    elif r.get("unwired"):
        P.append(f"{r['unwired']} of {r['rails']} rails are NOT wired (no data-railed): their "
                 "arrows do nothing, the failure that shipped dead and green before")
    if r.get("rails") and not r.get("scrollable"):
        P.append("no rail is scrollable, so the arrow behaviour could not be checked")
    if r.get("dots_empty"):
        P.append(f"{r['dots_empty']} scrollable rails have no dots")
    if r.get("left_enabled_at_start"):
        P.append(f"{r['left_enabled_at_start']} rails at position 0 have an ENABLED left arrow")

    st = m.get("step")
    if r.get("scrollable") and not st:
        P.append("found no scrollable rail with more than 2 cards to click through")
    elif st:
        pitch, sl = st.get("pitch") or 0, st.get("scrollLeft") or 0
        if sl <= 0:
            P.append("clicking a right arrow did not move the track at all")
        elif pitch <= 0:
            P.append(f"card pitch measured as {pitch}px, so card stepping could not be judged")
        elif abs(sl - round(sl / pitch) * pitch) > 1:
            P.append(f"the right arrow scrolled to {sl}px, not a multiple of the {pitch}px card "
                     "pitch: it leaves a part card against the edge instead of stepping whole cards")

    tiers = m.get("search_tiers") or {}
    for tier in ("search-hot.json", "search-index.json"):
        st_ = tiers.get(tier)
        if st_ is None:
            P.append(f"typing a search never requested {tier}; search changed shape and this "
                     "check must be updated, or search is not wired")
        elif st_ != 200:
            P.append(f"search tier {tier} failed ({st_}), so search covers "
                     + ("only the hot tier" if tier == "search-index.json" else "nothing fast"))
    if not m.get("search_results"):
        P.append(f"search for {QUERY!r} returned 0 results on the served site")
    for page in ("home", "watch"):
        errs = m.get(f"{page}_errors") or []
        if errs:
            P.append(f"{page} page threw {len(errs)} uncaught error(s), first: {errs[0]}")
    if m.get("watch_iframes"):
        P.append(f"the watch page has {m['watch_iframes']} iframe(s) before any click; players "
                 "must mount only on a gesture")
    return P


def measure() -> dict:
    from playwright.sync_api import sync_playwright
    m: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))

        page.goto(SITE + "/", wait_until="load", timeout=60000)
        page.wait_for_timeout(2000)            # let the rail and search scripts initialise
        m["home_title"] = page.title()
        m["rails"] = page.evaluate(RAILS_JS)
        m["step"] = page.evaluate(STEP_JS)
        # Search loads two index tiers lazily on the first keystroke: the small hot
        # tier answered at 0.4s with 1 result, the full index at ~2.1s with 13
        # (measured 2026-09-24). Counting as soon as ANY result shows measured the
        # hot tier alone, so a full index that failed to load passed. Record each
        # tier's real response, wait for the full one, then count once it settles.
        tiers: dict = {}
        watch = ("search-hot.json", "search-index.json")
        name = lambda u: u.split("?")[0].rsplit("/", 1)[-1]
        page.on("response", lambda r: tiers.setdefault(name(r.url), r.status)
                if name(r.url) in watch else None)
        page.on("requestfailed", lambda r: tiers.setdefault(name(r.url), f"failed: {r.failure}")
                if name(r.url) in watch else None)
        page.fill("#q", QUERY)
        for _ in range(75):                        # up to 15s for the full tier to answer
            if "search-index.json" in tiers:
                break
            page.wait_for_timeout(200)
        last, stable = -1, 0
        for _ in range(25):                        # then until the count holds for 1s
            n = page.evaluate("document.querySelectorAll('#results a').length")
            stable = stable + 1 if n == last else 0
            last = n
            if stable >= 5:
                break
            page.wait_for_timeout(200)
        m["search_results"] = last
        m["search_tiers"] = dict(tiers)
        m["home_errors"] = list(errors)

        errors.clear()
        page.goto(WATCH, wait_until="load", timeout=60000)
        page.wait_for_timeout(2000)
        m["watch_title"] = page.title()
        m["watch_iframes"] = page.evaluate("document.querySelectorAll('iframe').length")
        m["watch_errors"] = list(errors)
        browser.close()
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    out = {"suite": "Live behaviour", "ok": False, "problems": [], "measured": {}}
    try:
        m = measure()
        P = judge(m)
        flat = {"rails": (m.get("rails") or {}).get("rails"),
                "rails_unwired": (m.get("rails") or {}).get("unwired"),
                "scrollable_rails": (m.get("rails") or {}).get("scrollable"),
                "arrow_step": m.get("step"), "search_results": m.get("search_results"),
                "search_tiers": m.get("search_tiers"),
                "page_errors": len(m.get("home_errors", [])) + len(m.get("watch_errors", [])),
                "watch_iframes_before_click": m.get("watch_iframes")}
        out.update(ok=not P, problems=P, measured=flat)
    except Exception as e:                                        # noqa: BLE001
        # A timeout waiting for search results lands here, and says so.
        out["problems"] = [f"live behaviour check crashed: {type(e).__name__}: {str(e)[:200]}"]
        traceback.print_exc()
    Path(a.summary).write_text(json.dumps(out, indent=2))
    for k, v in out["measured"].items():
        print(f"  {k:<28} {v}")
    for p in out["problems"]:
        print(f"  PROBLEM {p}")
    print("OK" if out["ok"] else f"FAILED: {len(out['problems'])} problem(s)")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
