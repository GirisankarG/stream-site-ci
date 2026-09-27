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
- analytics is RUNNING: window.sa_event is a function. The host allowlist only
  proves the script loaded; a 200 carrying a broken body passes it while the
  site records nothing, found weeks later as a flat dashboard (MS_Seo)
- no uncaught page error on any page visited
- a watch page has no iframe before a click: players mount only on a gesture
- the hero trailer MOUNTS (youtube-nocookie, muted, aria-hidden), after its five
  gates are asserted first so a runner that fails a gate reads as the runner,
  not the site; and at 390px it must NOT mount
- hovering a card applies .peek and its backdrop from img.flixshows.me loads
- the watch-page pill is hidden AND computes to display:none; a class once beat
  the [hidden] rule and shipped it visible while the attribute was correct
- every [hidden] element on every page computes to display:none
- the episode panel (fixture breaking-bad-2008, a title KNOWN to carry episode
  names; a title with no TMDB match legitimately shows "Episode 4") opens with
  named rows, runtimes, and exactly one WATCHING mark

The trailer frame's own TEXT is read from inside the cross-origin YouTube frame
(the driver can, page JavaScript cannot) and must not be YouTube's embed error.
That is not playback: it proves WE configured the embed so YouTube accepts it.
Found live 2026-09-27 by MS_UI: every visitor saw "Video player configuration
error" (Error 153) because the site sends Referrer-Policy: no-referrer, which
YouTube now refuses. The mount check passed it, since the frame loaded fine.

The watch-page Trailer button (fixture interstellar-2014, which has a trailer)
shares that cause, so its iframe must carry a referrerpolicy that SENDS a
cross-origin referrer, and its frame text must not be the embed error. The
requirement is "YouTube receives a referrer", not one exact value, so any
policy in REFERRER_OK passes.

On a phone (390x844, mobile, touch), on breaking-bad-2008: the player is above
the fold; the episode panel opens as a bottom sheet (fixed, full width, flush to
the bottom) with every row in view and every row a 44px tap target, which holds
for this fixture's 7-episode season; a 16-episode season scrolls inside the
sheet by design. On the phone homepage, every card title renders: display
block, at least 14px tall, inside its card, not empty. Geometry, not the class,
because the bug it catches was captions clipped by an inline span under
overflow:hidden while the class stayed right.

Deliberately NOT asserted, because each is a third party's answer: that the
trailer PLAYS (.hero-bg.playing) or that its mute button is VISIBLE. Both are set
by the YouTube iframe's own load handler, which never fired in headless on
2026-09-24; asserting either would redden every run for a reason not ours.

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
SERIES = f"{SITE}/watch/breaking-bad-2008"   # fixture: carries episode names (7 of 7)
TRAILER_PAGE = f"{SITE}/watch/interstellar-2014"   # fixture: has a trailer button
PHONE = {"width": 390, "height": 844}
# Policies under which a cross-origin iframe request carries a Referer. Absent or
# no-referrer / same-origin inherit or suppress it, which is what YouTube refuses.
REFERRER_OK = {"origin", "strict-origin", "origin-when-cross-origin",
               "strict-origin-when-cross-origin", "no-referrer-when-downgrade", "unsafe-url"}

PHONE_WATCH_JS = """() => { const r = document.getElementById('stage');
  return r ? {stage_bottom: Math.round(r.getBoundingClientRect().bottom), vh: innerHeight}
           : {stage_bottom: null, vh: innerHeight}; }"""

PHONE_SHEET_JS = """() => { const e = document.getElementById('epanel'); if (!e) return null;
  const r = e.getBoundingClientRect(), rows = [...e.querySelectorAll('.ep')].map(x => x.getBoundingClientRect());
  return {position: getComputedStyle(e).position, left: Math.round(r.left), width: Math.round(r.width),
          vw: innerWidth, bottom: Math.round(r.bottom), vh: innerHeight, rows: rows.length,
          in_view: rows.filter(q => q.top >= 0 && q.bottom <= innerHeight).length,
          min_row_h: rows.length ? Math.round(Math.min(...rows.map(q => q.height))) : null}; }"""

PHONE_CAPS_JS = """() => { const caps = [...document.querySelectorAll('.rail .card .cap')];
  const bad = caps.filter(c => { const cs = getComputedStyle(c), r = c.getBoundingClientRect(),
                                        k = c.closest('.card').getBoundingClientRect();
    return cs.display !== 'block' || r.height < 14 || r.bottom > k.bottom + 1 || !c.textContent.trim(); });
  return {caps: caps.length, bad: bad.length}; }"""

HERO_JS = """() => { const v = document.querySelector('.hero-video'), c = navigator.connection || {};
  return {gates: {wide: innerWidth >= 760, hover: matchMedia('(hover:hover)').matches,
                  motion_ok: !matchMedia('(prefers-reduced-motion: reduce)').matches,
                  save_data_off: !c.saveData, net_4g: c.effectiveType === '4g'},
          mounted: !!v, host: v ? new URL(v.src).host : null,
          muted: v ? /[?&]mute=1/.test(v.src) : null,
          aria_hidden: v ? v.getAttribute('aria-hidden') : null}; }"""

HIDDEN_JS = """() => [...document.querySelectorAll('[hidden]')]
  .filter(e => getComputedStyle(e).display !== 'none')
  .map(e => e.id ? '#' + e.id : (e.className ? '.' + String(e.className).split(' ')[0] : e.tagName))"""

WATCHPAGE_JS = """() => { const c = document.getElementById('chip');
  return {chip: !!c, chip_hidden: c ? c.hidden : null,
          chip_display: c ? getComputedStyle(c).display : null,
          frame_iframes: document.querySelectorAll('#frame iframe').length,
          iframes: document.querySelectorAll('iframe').length}; }"""

EP_BEFORE_JS = """() => ({epanel_hidden: (document.getElementById('epanel') || {}).hidden,
  epopen_expanded: document.getElementById('epopen') ? document.getElementById('epopen').getAttribute('aria-expanded') : null,
  epq: !!document.getElementById('epq'),
  srcs_open: document.getElementById('srcs') ? document.getElementById('srcs').open : null})"""

EP_AFTER_JS = """() => { const rows = [...document.querySelectorAll('#epanel .ep')];
  const name = r => ((r.querySelector('.ept') || {}).textContent || '').trim();
  return {epanel_hidden: document.getElementById('epanel').hidden, rows: rows.length,
          generic_names: rows.filter(r => /^Episode \\d+$/.test(name(r))).length,
          no_name: rows.filter(r => !r.querySelector('.ept')).length,
          no_runtime: rows.filter(r => !r.querySelector('.epr')).length,
          watching: document.querySelectorAll('.ep[aria-pressed=true] .now').length}; }"""

PEEK_JS = """() => { const c = document.querySelector('.card.peek'); if (!c) return null;
  const im = c.querySelector('.art img.bd');
  return im ? {complete: im.complete, width: im.naturalWidth} : {img: 'missing'}; }"""
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
    for page in ("home", "watch", "series"):
        errs = m.get(f"{page}_errors") or []
        if errs:
            P.append(f"{page} page threw {len(errs)} uncaught error(s), first: {errs[0]}")
    if m.get("watch_iframes"):
        P.append(f"the watch page has {m['watch_iframes']} iframe(s) before any click; players "
                 "must mount only on a gesture")

    if m.get("sa_event") != "function":
        P.append(f"analytics is not running: window.sa_event is {m.get('sa_event')!r}, not a "
                 "function. The script host may still answer 200, so the allowlist passes "
                 "while the site records no visits")

    # Hero trailer: gates first, so a runner that fails one is not read as the site.
    h = m.get("hero") or {}
    off = [g for g, ok in (h.get("gates") or {}).items() if not ok]
    if off:
        P.append(f"hero trailer not checked: the runner fails its gate(s) {off}, so the "
                 "trailer correctly refused. Fix the runner's browser profile, not the site")
    elif not h.get("mounted"):
        P.append("hero trailer never mounted although all five of its gates pass")
    else:
        if h.get("host") != "www.youtube-nocookie.com":
            P.append(f"hero trailer mounted from {h.get('host')}, not www.youtube-nocookie.com")
        if not h.get("muted"):
            P.append("hero trailer mounted without mute=1, so it would autoplay with sound")
        if h.get("aria_hidden") != "true":
            P.append("hero trailer is not aria-hidden, so screen readers announce a decorative video")
    ft = m.get("hero_frame_text") or ""
    if h.get("mounted") and embed_error(ft):
        P.append(f"the hero trailer shows YouTube's error to every visitor ({ft[:80]!r}): the "
                 f"embed is misconfigured. Referrer-Policy is {m.get('referrer_policy')!r}; "
                 "YouTube refuses embeds that arrive with no referrer")
    if m.get("phone_hero_mounted"):
        P.append("hero trailer mounted on a 390px phone, where its gate must refuse it")

    # Watch-page Trailer button.
    if "trailer_button" in m:
        if not m.get("trailer_button"):
            P.append("interstellar-2014 has no #trailer button, though it is the fixture that has a trailer")
        elif not m.get("trailer_iframes"):
            P.append("clicking #trailer mounted no iframe in #frame")
        else:
            pol = m.get("trailer_referrerpolicy")
            if pol not in REFERRER_OK:
                P.append(f"the Trailer iframe's referrerpolicy is {pol!r}, so YouTube receives no "
                         "referrer and refuses the embed. It needs one that sends a cross-origin "
                         "referrer, such as strict-origin-when-cross-origin")
            if embed_error(m.get("trailer_frame_text")):
                P.append(f"the watch-page Trailer shows YouTube's error "
                         f"({(m.get('trailer_frame_text') or '')[:60]!r})")
    if m.get("trailer_errors"):
        P.append(f"trailer page threw {len(m['trailer_errors'])} uncaught error(s), "
                 f"first: {m['trailer_errors'][0]}")

    # Phone.
    pw = m.get("phone_watch")
    if pw is not None:
        if pw.get("stage_bottom") is None:
            P.append("phone watch page has no #stage player")
        elif pw["stage_bottom"] > pw["vh"]:
            P.append(f"on a phone the player ends at {pw['stage_bottom']}px, below the "
                     f"{pw['vh']}px fold: a reader has to scroll to find it")
    sh = m.get("phone_sheet")
    if "phone_watch" in m:
        if not sh:
            P.append("on a phone, #epopen opened no episode panel with rows")
        else:
            if (sh["position"] != "fixed" or sh["left"] != 0 or sh["width"] != sh["vw"]
                    or sh["bottom"] != sh["vh"]):
                P.append(f"on a phone the episode panel is not a bottom sheet (position "
                         f"{sh['position']}, left {sh['left']}, width {sh['width']}/{sh['vw']}, "
                         f"bottom {sh['bottom']}/{sh['vh']})")
            if sh["in_view"] != sh["rows"]:
                P.append(f"on a phone only {sh['in_view']} of {sh['rows']} episode rows are "
                         "reachable in the sheet on breaking-bad-2008, whose season fits")
            if sh.get("min_row_h") is not None and sh["min_row_h"] < 44:
                P.append(f"on a phone the shortest episode row is {sh['min_row_h']}px, under "
                         "the 44px tap target")
    pc = m.get("phone_captions")
    if pc is not None:
        if not pc.get("caps"):
            P.append("the phone homepage has 0 card titles, so none were checked")
        elif pc.get("bad"):
            P.append(f"on a phone {pc['bad']} of {pc['caps']} card titles do not render (clipped, "
                     "empty, or outside their card)")

    # Hover preview: a network dependency of ours, polled rather than slept.
    if m.get("peek_before"):
        P.append(f"{m['peek_before']} cards carry .peek before anything was hovered")
    pk = m.get("peek")
    if pk is None:
        P.append("hovering a card with a backdrop did not apply .peek within 3s")
    elif pk.get("img") == "missing":
        P.append("the hovered card has .peek but no backdrop image element")
    elif not (pk.get("complete") and pk.get("width")):
        P.append("the hovered card's backdrop did not load from img.flixshows.me within 3s")

    # Watch-page pill and every [hidden] element.
    for label in ("watch", "series"):
        w = m.get(f"{label}_page") or {}
        if not w.get("chip"):
            P.append(f"{label} page has no #chip status pill")
        elif not w.get("chip_hidden") or w.get("chip_display") != "none":
            P.append(f"{label} page status pill is VISIBLE before play (hidden={w.get('chip_hidden')}, "
                     f"display={w.get('chip_display')}); a class once beat the [hidden] rule exactly so")
        if w.get("frame_iframes"):
            P.append(f"{label} page has {w['frame_iframes']} iframe(s) in #frame before a click")
    for page in ("home", "watch", "series"):
        leaked = m.get(f"{page}_hidden_visible") or []
        if leaked:
            P.append(f"{page} page: {len(leaked)} [hidden] element(s) still render, e.g. {leaked[:4]}; "
                     "a display rule is beating the hidden attribute")

    # Episode panel on the fixture series.
    eb, ea = m.get("ep_before") or {}, m.get("ep_after") or {}
    if eb.get("epanel_hidden") is not True or eb.get("epopen_expanded") != "false":
        P.append(f"episode panel is not shut on load (hidden={eb.get('epanel_hidden')}, "
                 f"aria-expanded={eb.get('epopen_expanded')})")
    if not eb.get("epq"):
        P.append("episode panel has no #epq search box")
    if eb.get("srcs_open"):
        P.append("the sources list starts open; it must start collapsed")
    if ea:
        if ea.get("epanel_hidden") is not False:
            P.append("clicking #epopen did not open the episode panel")
        elif not ea.get("rows"):
            P.append("the episode panel opened with 0 episode rows")
        else:
            if ea.get("generic_names") or ea.get("no_name"):
                P.append(f"{ea.get('generic_names', 0) + ea.get('no_name', 0)} of {ea['rows']} episodes "
                         "on breaking-bad-2008 have no real name (shown as 'Episode N'), on a title "
                         "known to carry names")
            if ea.get("no_runtime"):
                P.append(f"{ea['no_runtime']} of {ea['rows']} episode rows have no runtime")
            if ea.get("watching") != 1:
                P.append(f"the episode panel shows {ea.get('watching')} WATCHING marks, not exactly 1")
    return P


def youtube_text(page, tries: int = 40) -> str | None:
    """innerText of the page's YouTube frame, read by the driver across origins."""
    for _ in range(tries):
        yt = [f for f in page.frames if "youtube" in (f.url or "")]
        if yt:
            try:
                txt = yt[0].evaluate("document.body ? document.body.innerText : ''")
            except Exception as e:                               # noqa: BLE001
                txt = f"<could not read the frame: {type(e).__name__}>"
            if txt and txt.strip():
                return txt.strip()[:200]
        page.wait_for_timeout(250)
    return None


def embed_error(text: str | None) -> bool:
    import re as _re
    t = text or ""
    return "configuration error" in t.lower() or bool(_re.search(r"\bError \d{3}\b", t))


def measure() -> dict:
    from playwright.sync_api import sync_playwright
    m: dict = {}

    def poll(page, js, until, tries, gap_ms):
        v = None
        for _ in range(tries):
            v = page.evaluate(js)
            if until(v):
                break
            page.wait_for_timeout(gap_ms)
        return v

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))

        # ---- home
        # domcontentloaded, never "load": load waits on the analytics vendor's CDN,
        # which held it open past 30s on a congested link and timed a context out.
        # sa_event is polled below instead, which measures analytics directly.
        home_resp = page.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
        # Pause the hero the way a keyboard user does, BEFORE any wait. Once it
        # rotates (every 7s), leaving a slide removes its trailer and the next one
        # mounts ~0.9s later, so an unpaused read can find no trailer and report a
        # working one as broken. The rotation clock starts at DOMContentLoaded, so
        # focusing after a wait is too late. A no-op on today's single hero.
        page.evaluate("(() => { const b = document.querySelector('.hero:not([inert]) .btn-primary');"
                      " if (b) b.focus({preventScroll: true}); })()")
        m["home_title"] = page.title()
        m["sa_event"] = poll(page, "typeof window.sa_event", lambda v: v == "function", 50, 200)
        # Up to 45s. Today the trailer mounts only after window load, which took
        # 12.9s and 21.1s on two measured runs (analytics plus dozens of posters),
        # so an 8s window started at DOMContentLoaded read a working trailer as
        # never mounted. The next build gates it on the first backdrop instead.
        m["hero"] = poll(page, HERO_JS, lambda v: v["mounted"], 225, 200)
        m["referrer_policy"] = home_resp.headers.get("referrer-policy") if home_resp else None
        m["hero_frame_text"] = youtube_text(page)
        page.wait_for_timeout(1500)            # let the rail and search scripts initialise
        m["rails"] = page.evaluate(RAILS_JS)
        m["step"] = page.evaluate(STEP_JS)
        m["peek_before"] = page.evaluate("document.querySelectorAll('.card.peek').length")
        card = page.locator(".card[data-bd]").first
        if card.count():
            card.scroll_into_view_if_needed()
            card.hover()
            # 600ms dwell timer, then the backdrop download: landed at 0.7-1.3s.
            m["peek"] = poll(page, PEEK_JS, lambda v: bool(v and (v.get("width") or v.get("img"))),
                             30, 100)
        else:
            m["peek"] = None
        m["home_hidden_visible"] = page.evaluate(HIDDEN_JS)

        # Search last: typing opens a results panel over the page. It loads two
        # tiers lazily on the first keystroke: the small hot tier answered at
        # 0.4s with 1 result, the full index at ~2.1s with 13 (2026-09-24).
        # Counting at first sight measured the hot tier alone, so a dead full
        # index passed. Record each tier's real response, wait for the full one,
        # then count once the number holds.
        tiers: dict = {}
        want = ("search-hot.json", "search-index.json")
        name = lambda u: u.split("?")[0].rsplit("/", 1)[-1]
        page.on("response", lambda r: tiers.setdefault(name(r.url), r.status)
                if name(r.url) in want else None)
        page.on("requestfailed", lambda r: tiers.setdefault(name(r.url), f"failed: {r.failure}")
                if name(r.url) in want else None)
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

        # ---- a movie watch page
        errors.clear()
        page.goto(WATCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        m["watch_title"] = page.title()
        m["watch_page"] = page.evaluate(WATCHPAGE_JS)
        m["watch_iframes"] = m["watch_page"]["iframes"]
        m["watch_hidden_visible"] = page.evaluate(HIDDEN_JS)
        m["watch_errors"] = list(errors)

        # ---- the fixture series, and its episode panel
        errors.clear()
        page.goto(SERIES, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        m["series_page"] = page.evaluate(WATCHPAGE_JS)
        m["series_hidden_visible"] = page.evaluate(HIDDEN_JS)
        m["ep_before"] = page.evaluate(EP_BEFORE_JS)
        if page.locator("#epopen").count():
            page.click("#epopen")
            m["ep_after"] = poll(page, EP_AFTER_JS, lambda v: v["epanel_hidden"] is False and v["rows"],
                                 20, 150)
        m["series_errors"] = list(errors)

        # ---- the watch-page Trailer button
        errors.clear()
        page.goto(TRAILER_PAGE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        m["trailer_button"] = page.locator("#trailer").count()
        if m["trailer_button"]:
            page.click("#trailer")
            try:
                page.wait_for_selector("#frame iframe", timeout=10000)
                m["trailer_iframes"] = page.evaluate("document.querySelectorAll('#frame iframe').length")
                m["trailer_referrerpolicy"] = page.evaluate(
                    "document.querySelector('#frame iframe').getAttribute('referrerpolicy')")
                m["trailer_frame_text"] = youtube_text(page)
            except Exception:                                    # noqa: BLE001
                m["trailer_iframes"] = 0     # judged below: the click mounted nothing
        m["trailer_errors"] = list(errors)

        # ---- a real phone: mobile, touch, 390x844
        ctx = browser.new_context(viewport=PHONE, is_mobile=True, has_touch=True,
                                  device_scale_factor=3)
        phone = ctx.new_page()
        phone.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
        phone.wait_for_timeout(4000)
        m["phone_hero_mounted"] = phone.evaluate("!!document.querySelector('.hero-video')")
        m["phone_captions"] = phone.evaluate(PHONE_CAPS_JS)
        phone.goto(SERIES, wait_until="domcontentloaded", timeout=60000)
        phone.wait_for_timeout(1500)
        m["phone_watch"] = phone.evaluate(PHONE_WATCH_JS)
        if phone.locator("#epopen").count():
            phone.click("#epopen")
            m["phone_sheet"] = poll(phone, PHONE_SHEET_JS,
                                    lambda v: bool(v and v.get("rows")), 20, 150)
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
                "page_errors": sum(len(m.get(f"{x}_errors", [])) for x in ("home", "watch", "series")),
                "watch_iframes_before_click": m.get("watch_iframes"),
                "analytics_sa_event": m.get("sa_event"),
                "hero": {k: (m.get("hero") or {}).get(k) for k in ("mounted", "host", "muted")},
                "hero_on_phone": m.get("phone_hero_mounted"),
                "hero_frame_text": m.get("hero_frame_text"),
                "referrer_policy": m.get("referrer_policy"),
                "peek": m.get("peek"),
                "hidden_but_rendered": sum(len(m.get(f"{x}_hidden_visible") or [])
                                           for x in ("home", "watch", "series")),
                "episode_panel": m.get("ep_after"),
                "trailer_referrerpolicy": m.get("trailer_referrerpolicy"),
                "trailer_frame_text": m.get("trailer_frame_text"),
                "phone_player_bottom": (m.get("phone_watch") or {}).get("stage_bottom"),
                "phone_sheet": m.get("phone_sheet"),
                "phone_captions": m.get("phone_captions")}
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
