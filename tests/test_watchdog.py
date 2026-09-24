"""The watchdog's judgement: a run that never reached its code is not a run."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import watchdog as W                                              # noqa: E402

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)


def run(hours_ago=1, status="completed", conclusion="failure"):
    t = (NOW - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": 1, "created_at": t, "status": status, "conclusion": conclusion}


def steps(build="success"):
    return [{"name": "Set up job", "conclusion": "success"},
            {"name": "Check out akv2011/stream-site", "conclusion": "success"},
            {"name": "Build", "conclusion": build}]


def test_recent_run_that_reached_its_step_is_silent_even_when_red():
    """Red means the checker worked. That is not the watchdog's business."""
    assert W.judge("checks.yml", "Build", 50, run(conclusion="failure"), steps("failure"), NOW) == []


def test_run_that_died_before_its_step_fires():
    """The 10-of-10 dead-at-checkout runs look exactly like this."""
    out = W.judge("checks.yml", "Build", 50, run(), steps("skipped"), NOW)
    assert out and "never reached its 'Build' step" in out[0]


def test_stale_workflow_fires_and_names_the_60_day_rule():
    out = W.judge("live-check.yml", "Build", 8, run(hours_ago=30), steps(), NOW)
    assert any("60 days" in p for p in out)


def test_never_run_fires():
    assert W.judge("checks.yml", "Build", 50, None, None, NOW)


def test_renamed_step_fires_rather_than_passing():
    out = W.judge("checks.yml", "Build the site", 50, run(), steps(), NOW)
    assert out and "no step named" in out[0]


def test_in_progress_run_is_not_judged_on_its_partial_steps():
    assert W.judge("checks.yml", "Build", 50, run(status="in_progress"), None, NOW) == []
