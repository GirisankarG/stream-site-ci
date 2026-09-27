"""Mutation tests: each inert-feature shape, and the measured-nothing cases."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import live_behaviour as B                                        # noqa: E402

# What the live site measured on 2026-09-24.
LIVE = {"home_title": "FlixShows - Find it. Press play.", "watch_title": "Iron Man (2008) - FlixShows",
        "rails": {"rails": 17, "unwired": 0, "scrollable": 14, "dots_empty": 0, "left_enabled_at_start": 0},
        "step": {"pitch": 188, "scrollLeft": 1316}, "search_results": 13,
        "search_tiers": {"search-hot.json": 200, "search-index.json": 200},
        "home_errors": [], "watch_errors": [], "series_errors": [], "watch_iframes": 0,
        "sa_event": "function",
        "trailer_button": 1, "trailer_iframes": 1,
        "trailer_referrerpolicy": "strict-origin-when-cross-origin", "trailer_frame_text": None,
        "trailer_errors": [],
        "phone_watch": {"stage_bottom": 438, "vh": 844},
        "phone_sheet": {"position": "fixed", "left": 0, "width": 390, "vw": 390, "bottom": 844,
                        "vh": 844, "rows": 7, "in_view": 7, "min_row_h": 48},
        "phone_captions": {"caps": 164, "bad": 0},
        "hero": {"gates": {"wide": True, "hover": True, "motion_ok": True, "save_data_off": True,
                           "net_4g": True},
                 "mounted": True, "host": "www.youtube-nocookie.com", "muted": True, "aria_hidden": "true"},
        "phone_hero_mounted": False,
        "peek_before": 0, "peek": {"complete": True, "width": 780},
        "watch_page": {"chip": True, "chip_hidden": True, "chip_display": "none", "frame_iframes": 0},
        "series_page": {"chip": True, "chip_hidden": True, "chip_display": "none", "frame_iframes": 0},
        "home_hidden_visible": [], "watch_hidden_visible": [], "series_hidden_visible": [],
        "ep_before": {"epanel_hidden": True, "epopen_expanded": "false", "epq": True, "srcs_open": False},
        "ep_after": {"epanel_hidden": False, "rows": 7, "generic_names": 0, "no_name": 0,
                     "no_runtime": 0, "watching": 1}}


def m(**over):
    d = {**LIVE, **{k: v for k, v in over.items() if k != "rails"}}
    if "rails" in over:
        d["rails"] = {**LIVE["rails"], **over["rails"]}
    return d


def test_the_live_site_as_measured_is_silent():
    assert B.judge(LIVE) == []


def test_unwired_rails_fire():
    """The shipped-dead-and-green shape: markup present, script wired nothing."""
    assert any("NOT wired" in p for p in B.judge(m(rails={"unwired": 17})))


def test_zero_rails_is_measured_nothing_not_a_pass():
    assert any("0 rails" in p for p in B.judge(m(rails={"rails": 0, "scrollable": 0})))


def test_arrow_that_does_not_move_fires():
    assert any("did not move" in p for p in B.judge(m(step={"pitch": 188, "scrollLeft": 0})))


def test_arrow_that_leaves_a_half_card_fires():
    """scrollLeft > 0 alone passed this real bug: 90% of a viewport, not whole cards."""
    assert any("not a multiple" in p for p in B.judge(m(step={"pitch": 188, "scrollLeft": 1229})))


def test_subpixel_landing_on_a_card_boundary_passes():
    assert B.judge(m(step={"pitch": 188, "scrollLeft": 1316.5})) == []


def test_missing_dots_and_enabled_left_arrow_fire():
    probs = B.judge(m(rails={"dots_empty": 3, "left_enabled_at_start": 2}))
    assert any("no dots" in p for p in probs) and any("ENABLED left arrow" in p for p in probs)


def test_search_with_no_results_fires():
    assert any("0 results" in p for p in B.judge(m(search_results=0)))


def test_page_error_fires_and_quotes_it():
    probs = B.judge(m(home_errors=["TypeError: Cannot read properties of null (reading 'addEventListener')"]))
    assert any("TypeError" in p for p in probs)


def test_iframe_before_click_fires():
    assert any("before any click" in p for p in B.judge(m(watch_iframes=1)))


def test_challenge_page_is_unverified_and_nothing_else():
    probs = B.judge(m(home_title="Just a moment...", search_results=0))
    assert len(probs) == 1 and "UNVERIFIED" in probs[0]


def test_full_index_failing_fires_even_though_the_hot_tier_answers():
    """The gap the first version had: 1 result from the hot tier read as working search."""
    probs = B.judge(m(search_results=1, search_tiers={"search-hot.json": 200, "search-index.json": 404}))
    assert any("only the hot tier" in p for p in probs)


def test_search_that_requests_no_index_fires():
    assert any("never requested" in p for p in B.judge(m(search_tiers={})))


# ------------------------------------------------------------ hero trailer

def hero(**kw):
    return m(hero={**LIVE["hero"], **kw})


def test_trailer_that_mounted_but_never_played_passes():
    """MS_UI's trap: .playing and a visible mute button come from YouTube's own load
    handler, which never fires in headless. Neither is part of the measurement."""
    assert B.judge(LIVE) == []


def test_trailer_that_never_mounted_fires():
    assert any("never mounted" in p for p in B.judge(hero(mounted=False, host=None, muted=None)))


def test_a_gate_the_runner_fails_names_the_runner_not_the_site():
    gates = {**LIVE["hero"]["gates"], "net_4g": False}
    probs = B.judge(hero(gates=gates, mounted=False))
    assert len([p for p in probs if "hero" in p]) == 1
    assert any("runner fails its gate" in p and "net_4g" in p for p in probs)


def test_trailer_with_sound_or_wrong_host_fires():
    assert any("mute=1" in p for p in B.judge(hero(muted=False)))
    assert any("youtube-nocookie" in p for p in B.judge(hero(host="www.youtube.com")))


def test_trailer_on_a_phone_fires():
    assert any("390px" in p for p in B.judge(m(phone_hero_mounted=True)))


# ----------------------------------------------------------- hover preview

def test_no_peek_after_hover_fires():
    assert any(".peek" in p for p in B.judge(m(peek=None)))


def test_peek_with_unloaded_backdrop_fires():
    assert any("did not load" in p for p in B.judge(m(peek={"complete": True, "width": 0})))


def test_peek_before_hover_fires():
    assert any("before anything was hovered" in p for p in B.judge(m(peek_before=3)))


# ------------------------------------------------------ pill and [hidden]

def test_pill_visible_despite_hidden_attribute_fires():
    """The real bug: hidden=true while a class forced display:inline-flex."""
    page = {**LIVE["watch_page"], "chip_display": "inline-flex"}
    assert any("VISIBLE before play" in p for p in B.judge(m(watch_page=page)))


def test_any_hidden_element_that_renders_fires():
    assert any("[hidden] element" in p for p in B.judge(m(home_hidden_visible=["#heromute"])))


def test_missing_pill_fires():
    assert any("no #chip" in p for p in B.judge(m(series_page={"chip": False})))


# ---------------------------------------------------------- episode panel

def test_panel_open_on_load_fires():
    before = {**LIVE["ep_before"], "epanel_hidden": False}
    assert any("not shut on load" in p for p in B.judge(m(ep_before=before)))


def test_generic_episode_names_fire_on_the_named_fixture():
    after = {**LIVE["ep_after"], "generic_names": 7}
    assert any("have no real name" in p for p in B.judge(m(ep_after=after)))


def test_panel_that_does_not_open_fires():
    after = {**LIVE["ep_after"], "epanel_hidden": True}
    assert any("did not open" in p for p in B.judge(m(ep_after=after)))


def test_watching_mark_must_be_exactly_one():
    after = {**LIVE["ep_after"], "watching": 0}
    assert any("WATCHING" in p for p in B.judge(m(ep_after=after)))


def test_series_page_error_fires():
    assert any("series page threw" in p for p in B.judge(m(series_errors=["ReferenceError: x"])))


def test_analytics_that_loaded_but_is_not_running_fires():
    """MS_Seo: a 200 from the analytics host is not analytics running."""
    assert any("analytics is not running" in p for p in B.judge(m(sa_event="undefined")))


def test_trailer_showing_youtubes_embed_error_fires():
    """Live 2026-09-27: every visitor saw this; the mount check passed it."""
    probs = B.judge(m(hero_frame_text="Video player configuration error\nError 153",
                      referrer_policy="no-referrer"))
    assert any("shows YouTube's error" in p and "no-referrer" in p for p in probs)


def test_trailer_frame_not_yet_rendered_is_not_a_failure():
    """An empty frame is YouTube being slow, not a misconfiguration."""
    assert B.judge(m(hero_frame_text=None)) == []


# ----------------------------------------------------- watch-page trailer

def test_trailer_iframe_without_a_referrer_policy_fires():
    """The live state on 2026-09-27: attribute absent, page policy no-referrer."""
    probs = B.judge(m(trailer_referrerpolicy=None))
    assert any("referrerpolicy is None" in p for p in probs)


def test_any_policy_that_sends_a_referrer_passes():
    """The requirement is 'YouTube gets a referrer', not one exact string."""
    assert B.judge(m(trailer_referrerpolicy="origin")) == []


def test_watch_trailer_showing_the_embed_error_fires():
    probs = B.judge(m(trailer_frame_text="Video player configuration error"))
    assert any("watch-page Trailer shows" in p for p in probs)


def test_trailer_click_that_mounts_nothing_fires():
    assert any("mounted no iframe" in p for p in B.judge(m(trailer_iframes=0)))


# ----------------------------------------------------------------- phone

def test_player_below_the_fold_fires():
    assert any("below the" in p for p in B.judge(m(phone_watch={"stage_bottom": 900, "vh": 844})))


def test_panel_that_is_not_a_bottom_sheet_fires():
    sheet = {**LIVE["phone_sheet"], "position": "absolute", "bottom": 700}
    assert any("not a bottom sheet" in p for p in B.judge(m(phone_sheet=sheet)))


def test_unreachable_episode_rows_fire():
    sheet = {**LIVE["phone_sheet"], "in_view": 4}
    assert any("4 of 7" in p for p in B.judge(m(phone_sheet=sheet)))


def test_small_tap_targets_fire():
    sheet = {**LIVE["phone_sheet"], "min_row_h": 30}
    assert any("44px tap target" in p for p in B.judge(m(phone_sheet=sheet)))


def test_clipped_card_titles_fire():
    """The real bug: inline span captions clipped under overflow:hidden."""
    assert any("card titles do not render" in p for p in B.judge(m(phone_captions={"caps": 164, "bad": 164})))


def test_zero_card_titles_is_measured_nothing():
    assert any("0 card titles" in p for p in B.judge(m(phone_captions={"caps": 0, "bad": 0})))
