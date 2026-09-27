"""
Check the SERVED flixshows.me: is it up, is every URL it advertises real, and is
the image project serving what the pages reference?

Stdlib only, and it never touches the private code repo. That is deliberate:
every run of this repo from 2026-09-13 to 09-23 died at the private checkout
("Input required and not supplied: token"), so the build-time checks never ran
once. A check that needs no private code cannot fail that way, so the live half
lives here on its own.

Every assertion is a POSITIVE signal against a committed reference
(baseline.json), never against yesterday's output and never a bare status code:

- A 200 is not a page. The sister site served its not-found page under HTTP 200
  for 489 advertised URLs, so a sampled page must carry its own canonical and
  must not carry the not-found title.
- A 404 is asserted by STATUS first and title second. A title-only check breaks
  the day someone fixes the status; a status-only check misses a 200 that
  renders a not-found body.
- Validity is not completeness. Every remaining URL in a sitemap that quietly
  lost 4,000 entries is perfectly valid, so the loc count has a committed floor.
- Samples are STRATIFIED: one URL per path type and one non-ASCII loc when any
  exist, then random fill. A random 12 from 9,354 once missed an entire class of
  19 non-ASCII slugs on this same site and the claim "all self-canonical" rested
  on draws that never touched them.
- img.flixshows.me is a SEPARATE Pages project. Its immutable cache rule was
  inert for weeks because a _headers file only applies to the project it ships
  in, and every page check stayed green meanwhile.

"Measured nothing" is a failure, never a pass: an empty sitemap, an empty sample
or a home page referencing no image each produce their own problem.

A Cloudflare challenge served to the runner is reported as UNVERIFIED FROM THIS
VANTAGE, not as dead: GitHub runners are datacenter IPs and a challenge there
says nothing about real readers. It is still red, because nothing was measured.

    python scripts/live_check.py --summary summary.json
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "flixshows-ci-livecheck/1.0 (+https://github.com/GirisankarG/stream-site-ci)"
TIMEOUT = 30

_TITLE = re.compile(r"<title>([^<]*)</title>", re.I)
_ROBOTS = re.compile(r'<meta\s+name="robots"\s+content="([^"]*)"', re.I)
_CANON = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"', re.I)
_LOC = re.compile(r"<loc>([^<]*)</loc>")
_SITEMAP_DECL = re.compile(r"^Sitemap:\s*(\S+)\s*$", re.M | re.I)
# Tags that make the browser fetch bytes from the host in the attribute.
_FETCHING = re.compile(
    r'<(script|iframe|img|source|video|audio|embed)\b[^>]*?\bsrc="(?:https?:)?//([^/"?#]+)'
    r'|<link\b[^>]*?\bhref="(?:https?:)?//([^/"?#]+)', re.I)
_WALL = ("just a moment", "attention required", "checking your browser",
         "access denied", "cf-browser-verification", "challenge-platform")


# ----------------------------------------------------------------- fetching

class Resp:
    def __init__(self, status: int, url: str, headers: dict, body: str, error: str = ""):
        self.status, self.url, self.headers, self.body, self.error = status, url, headers, body, error


def fetch(url: str) -> Resp:
    """GET with one retry on network error or 5xx. Never raises: an unreachable
    URL is a finding, returned with status 0 and the reason."""
    # A non-ASCII loc (/watch/pokémon-1997) cannot go on the wire as-is.
    parts = urllib.parse.urlsplit(url)
    wire = urllib.parse.urlunsplit(parts._replace(
        path=urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")))
    last = ""
    for attempt in range(2):
        try:
            req = urllib.request.Request(wire, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read(8_000_000).decode("utf-8", "replace")
                return Resp(r.status, r.geturl(), {k.lower(): v for k, v in r.headers.items()}, body)
        except urllib.error.HTTPError as e:
            body = e.read(2_000_000).decode("utf-8", "replace") if e.fp else ""
            if e.code < 500 or attempt == 1:
                return Resp(e.code, e.geturl() or wire, {k.lower(): v for k, v in (e.headers or {}).items()}, body)
            last = f"HTTP {e.code}"
        except Exception as e:                                   # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt == 0:
            time.sleep(3)
    return Resp(0, wire, {}, "", error=last)


# ------------------------------------------------------ pure judgement (tested)

def title_of(body: str) -> str:
    m = _TITLE.search(body)
    return html.unescape(m.group(1)).strip() if m else ""


def is_wall(r: Resp) -> bool:
    """A challenge page served to a datacenter IP, not the site's own content."""
    if r.status not in (403, 429, 503) and r.status != 200:
        return False
    low = r.body[:20000].lower()
    return any(w in low for w in _WALL) and "flixshows" not in title_of(r.body).lower()


def same_url(a: str, b: str) -> bool:
    """Equal after unescaping and unquoting both sides, so a raw-UTF-8 loc and
    its percent-encoded wire form compare equal. MEASURED NEGATIVE: 23 locs on
    2026-09-24 are non-ASCII and all are correct (loc, canonical and served URL
    agree). The spec would prefer percent-encoding; do not add an assertion that
    fires on either form."""
    n = lambda u: urllib.parse.unquote(html.unescape(u)).rstrip("/")
    return n(a) == n(b)


def external_hosts(body: str, site_host: str) -> set[str]:
    out = set()
    for m in _FETCHING.finditer(body):
        host = (m.group(2) or m.group(3) or "").lower().split(":")[0]
        if host and host != site_host and not host.endswith("." + site_host):
            out.add(host)
    return out


def judge_page(url: str, r: Resp, b: dict) -> list[str]:
    """Problems with one sampled sitemap URL. Empty list means it is its own page."""
    site_host = urllib.parse.urlsplit(b["site"]).hostname
    if r.status == 0:
        return [f"{url}: unreachable ({r.error})"]
    if is_wall(r):
        return [f"{url}: UNVERIFIED from the CI runner, served a challenge page "
                f"(HTTP {r.status}); says nothing about real readers, but nothing was measured"]
    probs = []
    if r.status != 200:
        probs.append(f"{url}: HTTP {r.status}, an advertised URL must serve 200")
    if not same_url(r.url, url):
        probs.append(f"{url}: redirected to {r.url}; the sitemap advertises a URL that is not the page")
    t = title_of(r.body)
    if t.startswith(b["not_found_title_prefix"]):
        probs.append(f"{url}: serves the not-found page ({t!r}) while advertised")
    m = _ROBOTS.search(r.body)
    if m and "noindex" in m.group(1).lower():
        probs.append(f"{url}: renders noindex but is in the sitemap, a contradiction crawlers act on")
    c = _CANON.search(r.body)
    if not c:
        probs.append(f"{url}: no canonical")
    elif not same_url(c.group(1), url):
        probs.append(f"{url}: canonical points at {c.group(1)}, telling search engines this is a duplicate")
    if re.search(r"<iframe\b", r.body, re.I):
        probs.append(f"{url}: an <iframe> is in the served HTML; players must mount only on a click")
    extra = external_hosts(r.body, site_host) - set(b["allowed_external_hosts"])
    if extra:
        probs.append(f"{url}: loads from unapproved third-party host(s) {sorted(extra)}; "
                     f"approved are {b['allowed_external_hosts']}")
    return probs


def judge_404(url: str, r: Resp, b: dict, home_title: str) -> list[str]:
    """A URL that cannot exist must say so by STATUS, then by body."""
    if r.status == 0:
        return [f"{url}: unreachable ({r.error})"]
    if is_wall(r):
        return [f"{url}: UNVERIFIED from the CI runner, challenge page (HTTP {r.status})"]
    probs = []
    t = title_of(r.body)
    if r.status != 404:
        probs.append(f"{url}: a nonexistent URL returned HTTP {r.status}, not 404 (soft 404)")
    if not t.startswith(b["not_found_title_prefix"]):
        probs.append(f"{url}: not-found body missing, title is {t!r}")
    if home_title and t == home_title:
        probs.append(f"{url}: serves the HOMEPAGE for a nonexistent URL, which invites "
                     "search engines to treat it as a homepage duplicate")
    return probs


def judge_image(url: str, r: Resp, b: dict) -> list[str]:
    if r.status == 0:
        return [f"image {url}: unreachable ({r.error})"]
    probs = []
    ctype = r.headers.get("content-type", "")
    cc = r.headers.get("cache-control", "")
    if r.status != 200:
        probs.append(f"image {url}: HTTP {r.status}")
    if not ctype.startswith("image/"):
        probs.append(f"image {url}: served {ctype!r}, not an image")
    if len(r.body) < 100:
        probs.append(f"image {url}: only {len(r.body)} bytes")
    if b["image_cache_control_must_contain"] not in cc:
        probs.append(f"image {url}: cache-control is {cc!r}, the immutable rule is not applied "
                     "on the image project, so every image revalidates instead of caching for a year")
    return probs


def stratified_sample(locs: list[str], n: int, rng: random.Random) -> list[str]:
    """One per first path segment, one non-ASCII if any, then random fill."""
    picked: list[str] = []
    by_type: dict[str, list[str]] = {}
    for u in locs:
        seg = urllib.parse.urlsplit(u).path.strip("/").split("/")[0] or "(root)"
        by_type.setdefault(seg, []).append(u)
    for seg in sorted(by_type):
        picked.append(rng.choice(by_type[seg]))
    non_ascii = [u for u in locs if not u.isascii()]
    if non_ascii:
        picked.append(rng.choice(non_ascii))
    rest = [u for u in locs if u not in set(picked)]
    picked += rng.sample(rest, max(0, min(n - len(picked), len(rest))))
    return list(dict.fromkeys(picked))


# --------------------------------------------------------------------- main

def run(b: dict, rng: random.Random) -> tuple[list[str], dict]:
    site = b["site"].rstrip("/")
    site_host = urllib.parse.urlsplit(site).hostname
    P: list[str] = []
    M: dict = {}

    # 1) Home: up, and the site's own title. The frequent uptime signal.
    home = fetch(site + "/")
    M["home_status"] = home.status
    home_title = title_of(home.body)
    if home.status == 0:
        P.append(f"home page unreachable: {home.error}")
    elif is_wall(home):
        P.append(f"home page: UNVERIFIED from the CI runner, challenge page (HTTP {home.status})")
    elif home.status != 200 or not home_title.startswith(b["home_title_prefix"]):
        P.append(f"home page: HTTP {home.status}, title {home_title!r}, "
                 f"expected 200 and a title starting {b['home_title_prefix']!r}")

    # 1b) Homepage integrity, from the served HTML. On 2026-09-27 the live homepage
    # showed 165 cards for 109 titles (Game of Thrones 4 times) and its hero title
    # again in a row below; the next build fixes both (MS_UI, b937e35). Exactly
    # one h1, whatever the hero carousel does.
    if home.status == 200:
        hrefs = home_card_links(home.body)
        dupes = sorted({u for u in hrefs if hrefs.count(u) > 1})
        hero = hero_links(home.body)
        h1s = len(re.findall(r"<h1\b", home.body, re.I))
        M.update(home_cards=len(hrefs), home_card_titles=len(set(hrefs)), home_h1=h1s)
        if not hrefs:
            P.append("home page has 0 title cards, so the homepage was not checked")
        if dupes:
            P.append(f"the homepage shows {len(dupes)} titles more than once ({len(hrefs)} cards "
                     f"for {len(set(hrefs))} titles), e.g. {dupes[:3]}")
        if hero & set(hrefs):
            P.append(f"the hero title also appears in a row below it: {sorted(hero & set(hrefs))[:3]}")
        if h1s != 1:
            P.append(f"the homepage has {h1s} h1 elements, not exactly 1")

    # 2) robots.txt declares exactly the committed sitemap set.
    rb = fetch(site + "/robots.txt")
    declared = set(_SITEMAP_DECL.findall(rb.body)) if rb.status == 200 else set()
    want = set(b["sitemaps"])
    M["robots_status"] = rb.status
    if rb.status != 200:
        P.append(f"robots.txt: HTTP {rb.status} {rb.error}".strip())
    elif declared != want:
        P.append(f"robots.txt sitemap declarations wrong: missing {sorted(want - declared)}, "
                 f"unexpected {sorted(declared - want)}")

    # 3) Sitemap: well-formed, within the committed band, every loc clean.
    locs: list[str] = []
    for sm in b["sitemaps"]:
        r = fetch(sm)
        if r.status != 200:
            P.append(f"{sm}: HTTP {r.status} {r.error}".strip())
            continue
        if "<sitemapindex" in r.body[:2000]:
            # Not silently mis-counted: the checker must be taught the index.
            P.append(f"{sm} became a sitemap INDEX; this checker counts urlset locs only and "
                     "must be updated before its counts mean anything")
            continue
        locs += _LOC.findall(r.body)
    M["sitemap_locs"] = len(locs)
    if len(locs) < b["sitemap_min_locs"]:
        P.append(f"sitemap holds {len(locs)} URLs, under the committed floor of "
                 f"{b['sitemap_min_locs']}: a collapsed or partial deploy")
    if len(locs) > b["sitemap_max_locs"]:
        P.append(f"sitemap holds {len(locs)} URLs, over the {b['sitemap_max_locs']} protocol limit")
    clean = re.compile(rf"^{re.escape(site)}(/\S*)?$")
    bad = [u for u in locs if not clean.match(u)]
    html_suffix = [u for u in locs if urllib.parse.urlsplit(u).path.endswith(".html")]
    M["bad_locs"], M["html_suffix_locs"] = len(bad), len(html_suffix)
    if bad:
        P.append(f"{len(bad)} sitemap locs are not clean absolute URLs on {site} "
                 f"(whitespace, wrong host): {bad[:3]}")
    if html_suffix:
        P.append(f"{len(html_suffix)} sitemap locs end in .html, which Pages 308-redirects away: "
                 f"{html_suffix[:3]}")

    # 4) Stratified sample: each is its own real, indexable, self-canonical page.
    sample = stratified_sample(locs, b["sample_size"], rng) if locs else []
    M["sampled"] = len(sample)
    M["sampled_types"] = sorted({urllib.parse.urlsplit(u).path.strip("/").split("/")[0] or "(root)"
                                 for u in sample})
    if not sample:
        P.append("sampled 0 sitemap URLs, so no advertised page was verified at all")
    dead = 0
    for u in sample:
        pp = judge_page(u, fetch(u), b)
        dead += bool(pp)
        P += pp
    M["sampled_bad"] = dead

    # 4b) Completeness, as an IDENTITY rather than a threshold. The sitemap count
    # moves legitimately every time a stream host dies (09-24: 9,354 to 8,504 on
    # purpose, f62b688), so a floor fitted to it cries wolf on correct behaviour.
    # What does not move: watch pages served = pages in the sitemap + pages left
    # out, and every page left out must be noindex. A sitemap that wrongly dropped
    # indexable pages shows up here as left-out pages WITHOUT noindex, whatever its
    # size. Measured 2026-09-27: 13,631 served, 8,198 in the sitemap, 5,433 left
    # out, 6 of 6 sampled noindex. The other half, sitemap pages being indexable,
    # is step 4's noindex assertion.
    ix = fetch(site + "/search-index.json")
    served: set[str] = set()
    if ix.status != 200:
        P.append(f"search-index.json: HTTP {ix.status} {ix.error}".strip()
                 + ", so sitemap completeness could not be checked")
    else:
        try:
            served = {e["s"] for e in json.loads(ix.body) if isinstance(e, dict) and e.get("s")}
        except (json.JSONDecodeError, TypeError, KeyError):
            P.append("search-index.json is not the expected list of {s: slug}")
    in_sitemap = {urllib.parse.unquote(urllib.parse.urlsplit(u).path.split("/watch/", 1)[1]).rstrip("/")
                  for u in locs if "/watch/" in u}
    M["watch_served"], M["watch_in_sitemap"] = len(served), len(in_sitemap)
    if served:
        orphans = in_sitemap - served
        if orphans:
            P.append(f"the sitemap advertises {len(orphans)} watch pages the site does not serve, "
                     f"e.g. {sorted(orphans)[:3]}")
        left_out = sorted(served - in_sitemap)
        M["watch_left_out"] = len(left_out)
        probe = rng.sample(left_out, min(b["left_out_sample"], len(left_out)))
        indexable = []
        for slug in probe:
            r = fetch(f"{site}/watch/{slug}")
            mr = _ROBOTS.search(r.body) if r.status == 200 else None
            if r.status == 200 and not (mr and "noindex" in mr.group(1).lower()):
                indexable.append(slug)
        M["left_out_sampled"], M["left_out_indexable"] = len(probe), len(indexable)
        if indexable:
            P.append(f"{len(indexable)} of {len(probe)} sampled pages LEFT OUT of the sitemap are "
                     f"indexable, e.g. {indexable[:3]}: the sitemap dropped pages the build meant "
                     "to include")

    # 5) Real 404s on every path type the sitemap uses, plus the bare root.
    token = f"ci-probe-{rng.randrange(10**8)}"
    probes = [f"{site}/{token}"] + [f"{site}/{seg}/{token}" for seg in M["sampled_types"]
                                    if seg != "(root)"]
    for u in probes:
        P += judge_404(u, fetch(u), b, home_title)
    M["not_found_probes"] = len(probes)

    # 6) The image project, through an image the home page actually references.
    img_re = re.compile(rf'https://{re.escape(b["image_host"])}/[^"\s)]+\.(?:webp|jpe?g|png|avif)', re.I)
    imgs = img_re.findall(home.body)
    M["home_images_referenced"] = len(imgs)
    if not imgs:
        P.append(f"home page references no image on {b['image_host']}, so the image project "
                 "could not be checked at all")
    else:
        P += judge_image(imgs[0], fetch(imgs[0]), b)

    # 7) Deploys that STOP. A site no longer receiving deploys is byte-identical
    # to a healthy one and every assert above stays green while the content ages.
    # deploy.sh writes deploy-id.txt as "<UTC timestamp>-<random>", so its own
    # timestamp dates the last deploy and no state has to be carried between runs.
    d = fetch(site + "/deploy-id.txt")
    M["deploy_id"] = d.body.strip()[:40] if d.status == 200 else f"HTTP {d.status}"
    if d.status != 200:
        P.append(f"deploy-id.txt: HTTP {d.status} {d.error}".strip() + ", so the deploy age is unknown")
    else:
        age = deploy_age_days(d.body.strip(), time.time())
        M["deploy_age_days"] = None if age is None else round(age, 1)
        if age is None:
            P.append(f"deploy-id.txt reads {d.body.strip()[:40]!r}, not '<YYYYMMDDTHHMMSSZ>-<id>'; "
                     "its format changed and this check must be updated")
        elif age > b["deploy_max_age_days"]:
            P.append(f"the live site was last deployed {age:.0f} days ago, over the "
                     f"{b['deploy_max_age_days']}-day limit: deploys have stopped, so new "
                     "titles and fixes are not reaching readers")

    return P, M


_CARD = re.compile(r'<a\b[^>]*class="card[^"]*"[^>]*href="([^"]+)"'
                   r'|<a\b[^>]*href="([^"]+)"[^>]*class="card[^"]*"', re.I)
_HERO = re.compile(r'<section[^>]*class="hero\b[\s\S]*?</section>', re.I)


def home_card_links(body: str) -> list[str]:
    """Every title card's link on the page, duplicates kept, so a repeat is countable."""
    return [a or b for a, b in _CARD.findall(body)]


def hero_links(body: str) -> set[str]:
    """Titles the hero links to: one section.hero today, several once it rotates."""
    return {u for sec in _HERO.findall(body) for u in re.findall(r'href="(watch/[^"]+)"', sec)}


def deploy_age_days(deploy_id: str, now: float) -> float | None:
    """Days since the timestamp that leads a deploy id, or None if it does not parse."""
    import datetime as _dt
    m = re.match(r"^(\d{8}T\d{6}Z)", deploy_id)
    if not m:
        return None
    ts = _dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    return (now - ts.timestamp()) / 86400


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--baseline", default=str(ROOT / "baseline.json"))
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    out = {"suite": "Live site", "ok": False, "problems": [], "measured": {}}
    try:
        b = json.loads(Path(a.baseline).read_text())
        problems, measured = run(b, random.Random(a.seed))
        out.update(ok=not problems, problems=problems, measured=measured)
    except Exception as e:                                       # noqa: BLE001
        # The check reached its own code and then broke. Say THAT, not "never ran".
        out["problems"] = [f"live check crashed: {type(e).__name__}: {e}"]
        traceback.print_exc()
    Path(a.summary).write_text(json.dumps(out, indent=2))

    for k, v in out["measured"].items():
        print(f"  {k:<24} {v}")
    for p in out["problems"]:
        print(f"  PROBLEM {p}")
    print("OK" if out["ok"] else f"FAILED: {len(out['problems'])} problem(s)")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
