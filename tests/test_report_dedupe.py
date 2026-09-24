"""Mail on change, not on every red run. The run's red/green never changes."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import report as R                                                # noqa: E402

FLOOR_12 = "sitemap holds 12 URLs, under the committed floor of 7900: a collapsed or partial deploy"
FLOOR_40 = "sitemap holds 40 URLs, under the committed floor of 7900: a collapsed or partial deploy"
PAGE_A = "https://flixshows.me/watch/a: serves the not-found page ('Page not found - FlixShows') while advertised"
PAGE_B = "https://flixshows.me/watch/b: serves the not-found page ('Page not found - FlixShows') while advertised"
DOWN = "home page unreachable: URLError: <urlopen error timed out>"
NOW = 1_800_000_000.0


def test_class_ignores_counts_urls_and_quoted_values():
    assert R.problem_class(FLOOR_12) == R.problem_class(FLOOR_40)
    assert R.problem_class(PAGE_A) == R.problem_class(PAGE_B)
    assert R.problem_class(FLOOR_12) != R.problem_class(DOWN)


def test_first_failure_mails():
    assert R.decide(None, True, [FLOOR_12], NOW)[0] == "new"
    assert R.decide({"red": False}, True, [FLOOR_12], NOW)[0] == "new"


def test_same_failure_an_hour_later_is_not_re_mailed():
    """The flood this exists to stop: 24 identical mails a day."""
    prev = {"red": True, "classes": [R.problem_class(FLOOR_12)], "last_mail": NOW - 3600}
    assert R.decide(prev, True, [FLOOR_40], NOW)[0] == "quiet"


def test_a_new_kind_of_failure_breaks_through_a_standing_one():
    """A minor standing fault must never hide the site going down."""
    prev = {"red": True, "classes": [R.problem_class(PAGE_A)], "last_mail": NOW - 600}
    verdict, lead = R.decide(prev, True, [PAGE_B, DOWN], NOW)
    assert verdict == "worse" and lead[0] == DOWN


def test_unchanged_failure_is_reminded_once_a_day():
    prev = {"red": True, "classes": [R.problem_class(FLOOR_12)], "last_mail": NOW - 25 * 3600}
    assert R.decide(prev, True, [FLOOR_12], NOW)[0] == "still"


def test_recovery_is_announced_once():
    assert R.decide({"red": True, "classes": ["x"]}, False, [], NOW)[0] == "recovered"
    assert R.decide({"red": False}, False, [], NOW)[0] == "quiet"


def _run(tmp_path, monkeypatch, problems, dry=True):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"suite": "Live site", "ok": not problems,
                             "problems": problems, "measured": {}}))
    argv = ["report.py", "--summary", str(p), "--suite", "Live site",
            "--state", str(tmp_path / "st" / "mail.json")] + (["--dry-run"] if dry else [])
    monkeypatch.setattr(sys, "argv", argv)
    return R.main()


def test_quiet_run_still_exits_red(tmp_path, monkeypatch, capsys):
    """Deduping the mail must never turn a failing run green."""
    for k in ("RESEND_API_KEY", "ALERT_EMAIL", "ALERT_FROM"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "st").mkdir()
    (tmp_path / "st" / "mail.json").write_text(json.dumps(
        {"red": True, "classes": [R.problem_class(FLOOR_12)], "last_mail": time.time() - 60}))
    assert _run(tmp_path, monkeypatch, [FLOOR_40]) == 1
    assert "not re-mailed" in capsys.readouterr().out


def test_first_red_writes_state_and_a_failed_send_does_not_move_the_clock(tmp_path, monkeypatch):
    """No mail secrets: the send fails, so the next run must try again, not wait a day."""
    for k in ("RESEND_API_KEY", "ALERT_EMAIL", "ALERT_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert _run(tmp_path, monkeypatch, [FLOOR_12], dry=False) == 1
    st = json.loads((tmp_path / "st" / "mail.json").read_text())
    assert st["red"] is True and st["classes"] and st["last_mail"] == 0


def test_dry_run_leaves_state_alone(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, [FLOOR_12]) == 1
    assert not (tmp_path / "st" / "mail.json").exists()


def test_green_after_red_announces_recovery(tmp_path, monkeypatch, capsys):
    (tmp_path / "st").mkdir()
    (tmp_path / "st" / "mail.json").write_text(json.dumps({"red": True, "classes": ["x"], "last_mail": 1}))
    assert _run(tmp_path, monkeypatch, []) == 0
    assert "recovered, all checks pass again" in capsys.readouterr().out
