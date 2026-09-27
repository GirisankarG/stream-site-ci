"""
Mutation tests: break exactly one thing, assert the check goes red and names it.

A check that can only go green or time out is not a check. The healthy fixtures
are the markup flixshows.me actually served on 2026-09-24, so a regex that
stops matching the real page fails here instead of passing forever.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import live_check as L                                            # noqa: E402

B = json.loads((Path(__file__).resolve().parents[1] / "baseline.json").read_text())
URL = "https://flixshows.me/watch/iron-man-2008"
GOOD = ('<html><head><title>Iron Man (2008) - FlixShows</title>'
        '<meta name="robots" content="index,follow">'
        f'<link rel="canonical" href="{URL}">'
        '<script src="https://scripts.simpleanalyticscdn.com/latest.js"></script>'
        '<link rel="preload" href="https://flixshows.me/static/app.css">'
        '</head><body><img src="https://img.flixshows.me/static/img/b1.jpg"></body></html>')


def resp(status=200, url=URL, body=GOOD, headers=None):
    return L.Resp(status, url, headers or {}, body)


def test_healthy_page_is_silent():
    assert L.judge_page(URL, resp(), B) == []


def test_soft_404_under_200_fires():
    body = GOOD.replace("Iron Man (2008) - FlixShows", "Page not found - FlixShows")
    assert any("not-found page" in p for p in L.judge_page(URL, resp(body=body), B))


def test_non_200_fires():
    assert any("HTTP 500" in p for p in L.judge_page(URL, resp(status=500), B))


def test_redirect_fires():
    assert any("redirected" in p for p in L.judge_page(URL, resp(url=URL + ".html"), B))


def test_noindex_in_sitemap_fires():
    body = GOOD.replace("index,follow", "noindex,follow")
    assert any("noindex" in p for p in L.judge_page(URL, resp(body=body), B))


def test_foreign_canonical_fires():
    body = GOOD.replace(f'href="{URL}"', 'href="https://flixshows.me/"')
    assert any("canonical" in p for p in L.judge_page(URL, resp(body=body), B))


def test_missing_canonical_fires():
    body = GOOD.replace(f'<link rel="canonical" href="{URL}">', "")
    assert any("no canonical" in p for p in L.judge_page(URL, resp(body=body), B))


def test_iframe_in_html_fires():
    body = GOOD.replace("</body>", '<iframe src="https://www.viduki.net/1/movie/1726"></iframe></body>')
    probs = L.judge_page(URL, resp(body=body), B)
    assert any("<iframe>" in p for p in probs)
    assert any("viduki" in p for p in probs), "the player host must also fail the allowlist"


def test_unapproved_third_party_fires():
    body = GOOD.replace("</head>", '<script src="https://evil-ads.example/x.js"></script></head>')
    assert any("evil-ads.example" in p for p in L.judge_page(URL, resp(body=body), B))


def test_approved_hosts_and_own_subdomains_pass():
    assert L.external_hosts(GOOD, "flixshows.me") == {"scripts.simpleanalyticscdn.com"}


def test_non_ascii_loc_matches_its_wire_form():
    """MEASURED NEGATIVE: raw-UTF-8 and percent-encoded forms are the same URL."""
    raw = "https://flixshows.me/watch/pokémon-horizons-the-series-2023"
    wire = "https://flixshows.me/watch/pok%C3%A9mon-horizons-the-series-2023"
    assert L.same_url(raw, wire)
    body = GOOD.replace(URL, raw)
    assert L.judge_page(raw, resp(url=wire, body=body), B) == []


def test_canonical_entity_is_not_a_mismatch():
    """The &#x27; false positive that hit the sister site's first live run."""
    u = "https://flixshows.me/watch/ocean's-eleven-2001"
    assert L.same_url("https://flixshows.me/watch/ocean&#x27;s-eleven-2001", u)


def test_challenge_page_is_unverified_not_dead():
    wall = "<html><title>Just a moment...</title>challenge-platform</html>"
    probs = L.judge_page(URL, resp(status=403, body=wall), B)
    assert len(probs) == 1 and "UNVERIFIED" in probs[0]


def test_unreachable_is_a_problem_not_a_crash():
    r = L.Resp(0, URL, {}, "", error="ConnectionError: refused")
    assert any("unreachable" in p for p in L.judge_page(URL, r, B))


# ------------------------------------------------------------------ 404s

NF = "<html><title>Page not found - FlixShows</title></html>"
HOME_T = "FlixShows - Find it. Press play."


def test_real_404_is_silent():
    assert L.judge_404(URL, resp(status=404, body=NF), B, HOME_T) == []


def test_soft_404_fires_on_status_even_with_right_body():
    assert any("soft 404" in p for p in L.judge_404(URL, resp(status=200, body=NF), B, HOME_T))


def test_404_serving_the_homepage_fires():
    body = f"<html><title>{HOME_T}</title></html>"
    probs = L.judge_404(URL, resp(status=404, body=body), B, HOME_T)
    assert any("HOMEPAGE" in p for p in probs)


# ---------------------------------------------------------------- images

def img(status=200, ctype="image/jpeg", cc="public, max-age=31536000, immutable", n=83911):
    return L.Resp(status, "u", {"content-type": ctype, "cache-control": cc}, "x" * n)


def test_healthy_image_is_silent():
    assert L.judge_image("u", img(), B) == []


def test_inert_immutable_rule_fires():
    """The real 09-20 bug: the rule shipped in the wrong Pages project."""
    assert any("immutable rule" in p for p in L.judge_image("u", img(cc="max-age=14400"), B))


def test_html_served_as_image_fires():
    assert any("not an image" in p for p in L.judge_image("u", img(ctype="text/html"), B))


def test_truncated_image_fires():
    assert any("bytes" in p for p in L.judge_image("u", img(n=40), B))


# ------------------------------------------------------------- sampling

def test_sample_covers_every_path_type_and_a_non_ascii_loc():
    locs = ([f"https://flixshows.me/watch/t{i}" for i in range(500)]
            + [f"https://flixshows.me/genre/g{i}" for i in range(5)]
            + ["https://flixshows.me/", "https://flixshows.me/watch/pokémon-1997"])
    s = L.stratified_sample(locs, 12, random.Random(1))
    types = {u.split("/")[3] or "(root)" for u in s}
    assert {"watch", "genre", "(root)"} <= types
    assert any(not u.isascii() for u in s), "the non-ASCII class must be sampled every run"
    assert len(s) == len(set(s)) and len(s) <= 12 + 1


def test_empty_sitemap_samples_nothing():
    assert L.stratified_sample([], 12, random.Random(1)) == []


# ---------------------------------------------------------- deploy staleness

NOW = 1790500000.0   # 2026-09-27 roughly


def test_deploy_age_parses_the_real_id_format():
    """The live value on 2026-09-27."""
    age = L.deploy_age_days("20260924T132732Z-539513605", NOW)
    assert age is not None and 2 < age < 4


def test_unparseable_deploy_id_is_none_not_zero_days():
    """A format change must never read as 'deployed just now'."""
    assert L.deploy_age_days("abc123", NOW) is None
    assert L.deploy_age_days("", NOW) is None


# --------------------------------------------- served half of the identity

def _fake_site(monkeypatch, left_out_robots="noindex,follow"):
    """A tiny served site: 3 watch pages, 2 in the sitemap, 1 left out."""
    home = ('<html><head><title>FlixShows - Find it.</title></head>'
            '<body><img src="https://img.flixshows.me/static/img/b1.jpg"></body></html>')
    page = lambda slug, robots: (
        f'<html><head><title>{slug} - FlixShows</title><meta name="robots" content="{robots}">'
        f'<link rel="canonical" href="https://flixshows.me/watch/{slug}"></head></html>')
    routes = {
        "https://flixshows.me/": L.Resp(200, "https://flixshows.me/", {}, home),
        "https://flixshows.me/robots.txt": L.Resp(200, "u", {}, "Sitemap: https://flixshows.me/sitemap.xml\n"),
        "https://flixshows.me/sitemap.xml": L.Resp(200, "u", {},
            "<urlset><loc>https://flixshows.me/watch/a</loc><loc>https://flixshows.me/watch/b</loc></urlset>"),
        "https://flixshows.me/search-index.json": L.Resp(200, "u", {},
            '[{"s":"a"},{"s":"b"},{"s":"c"}]'),
        "https://flixshows.me/watch/a": L.Resp(200, "https://flixshows.me/watch/a", {}, page("a", "index,follow")),
        "https://flixshows.me/watch/b": L.Resp(200, "https://flixshows.me/watch/b", {}, page("b", "index,follow")),
        "https://flixshows.me/watch/c": L.Resp(200, "https://flixshows.me/watch/c", {}, page("c", left_out_robots)),
        "https://img.flixshows.me/static/img/b1.jpg": L.Resp(200, "u", {"content-type": "image/jpeg",
            "cache-control": "public, max-age=31536000, immutable"}, "x" * 500),
        "https://flixshows.me/deploy-id.txt": L.Resp(200, "u", {}, "20260926T000000Z-1"),
    }
    nf = L.Resp(404, "u", {}, "<title>Page not found - FlixShows</title>")
    monkeypatch.setattr(L, "fetch", lambda url: routes.get(url, nf))
    import time
    monkeypatch.setattr(time, "time", lambda: 1790500000.0)
    b = {**B, "sitemap_min_locs": 1, "left_out_sample": 5, "home_title_prefix": "FlixShows"}
    return L.run(b, random.Random(1))


def test_served_identity_holds_when_left_out_pages_are_noindex(monkeypatch):
    probs, m = _fake_site(monkeypatch)
    assert m["watch_left_out"] == 1 and m["left_out_indexable"] == 0
    assert not [p for p in probs if "LEFT OUT" in p], probs


def test_left_out_page_that_is_indexable_fires(monkeypatch):
    """The completeness failure a floor cannot see, at any size."""
    probs, m = _fake_site(monkeypatch, left_out_robots="index,follow")
    assert m["left_out_indexable"] == 1
    assert any("LEFT OUT of the sitemap are indexable" in p for p in probs)
