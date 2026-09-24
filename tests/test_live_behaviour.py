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
        "home_errors": [], "watch_errors": [], "watch_iframes": 0}


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
