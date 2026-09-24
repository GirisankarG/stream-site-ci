"""The mailer's three states, none of them quiet."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import report as R                                                # noqa: E402


def test_subject_names_product_suite_and_the_failure():
    s = R.subject_for("Live site", ["sitemap holds 12 URLs, under the floor", "b", "c"])
    assert s.startswith("[FlixShows] Live site: sitemap holds 12 URLs")
    assert s.endswith("(+2 more)")


def test_missing_summary_means_the_check_never_ran(tmp_path, monkeypatch, capsys):
    """Ten days of runs died at checkout. That must mail, not stay silent."""
    for k in ("RESEND_API_KEY", "ALERT_EMAIL", "ALERT_FROM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(tmp_path / "nope.json"),
                                      "--suite", "Build checks", "--dry-run"])
    assert R.main() == 1
    out = capsys.readouterr().out
    assert "[FlixShows] Build checks:" in out and "never reached its own" in out


def test_ok_summary_is_silent_and_green(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"suite": "Live site", "ok": True, "problems": [], "measured": {}}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(p), "--suite", "Live site"])
    assert R.main() == 0


def test_garbage_summary_is_a_failure(tmp_path, monkeypatch, capsys):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(p), "--suite", "X", "--dry-run"])
    assert R.main() == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_missing_mail_secret_is_a_failure_not_a_skip(monkeypatch, capsys):
    for k in ("RESEND_API_KEY", "ALERT_EMAIL", "ALERT_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert R.send("s", "<p>b</p>") is False
    assert "cannot mail: missing RESEND_API_KEY, ALERT_EMAIL, ALERT_FROM" in capsys.readouterr().out


def test_missing_summary_names_the_step_that_failed(tmp_path, monkeypatch, capsys):
    """The 10-of-10 dead runs, as they should have been reported."""
    monkeypatch.setenv("STEPS_JSON", json.dumps({
        "checkout-code": {"outcome": "failure"}, "tests": {"outcome": "skipped"}}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(tmp_path / "x.json"),
                                      "--suite", "Live site", "--dry-run"])
    assert R.main() == 1
    out = capsys.readouterr().out
    assert "CODE_REPO_PAT" in out, "the mail must say what to do, not just 'failure'"


def test_step_only_mode_green_when_every_step_passed(monkeypatch):
    monkeypatch.setenv("STEPS_JSON", json.dumps({
        "checkout-code": {"outcome": "success"}, "build": {"outcome": "success"}}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--suite", "Build checks"])
    assert R.main() == 0


def test_step_only_mode_red_names_each_failed_step(monkeypatch, capsys):
    monkeypatch.setenv("STEPS_JSON", json.dumps({
        "checkout-code": {"outcome": "success"}, "build": {"outcome": "success"},
        "phone-audit": {"outcome": "failure"}, "behaviour": {"outcome": "failure"}}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--suite", "Build checks", "--dry-run"])
    assert R.main() == 1
    out = capsys.readouterr().out
    assert "[FlixShows] Build checks: step phone-audit: failure (+1 more)" in out


def test_no_step_outcomes_at_all_is_not_green(monkeypatch):
    """Measured nothing is a failure: an empty STEPS_JSON must not read as ok."""
    monkeypatch.delenv("STEPS_JSON", raising=False)
    monkeypatch.setattr(sys, "argv", ["report.py", "--suite", "Build checks", "--dry-run"])
    assert R.main() == 1


def test_missing_secrets_are_named_and_skips_do_not_bury_the_cause(monkeypatch, capsys):
    """What every one of the ten dead runs should have mailed."""
    monkeypatch.setenv("STEPS_JSON", json.dumps({
        "require-secrets": {"outcome": "failure", "outputs": {"missing": "CODE_REPO_PAT ALERT_FROM"}},
        "checkout-code": {"outcome": "skipped"}, "install": {"outcome": "skipped"},
        "build": {"outcome": "skipped"}, "verify": {"outcome": "skipped"}}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--suite", "Build checks", "--dry-run"])
    assert R.main() == 1
    out = capsys.readouterr().out
    subject = [l for l in out.splitlines() if l.startswith("[report] subject:")][0]
    assert "require-secrets: failure, not set: CODE_REPO_PAT ALERT_FROM" in subject
    assert subject.endswith("(+1 more)"), "four skips must collapse into one line"


def test_private_detail_keeps_findings_out_of_the_public_log(tmp_path, monkeypatch, capsys):
    """A discovery finding names the source. This repo's logs are public."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"suite": "Discovery", "ok": False, "measured": {},
                             "problems": ["source-host.example lists 100 titles we do not carry"]}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(p), "--suite", "Discovery",
                                      "--private-detail", "--dry-run"])
    assert R.main() == 1
    out = capsys.readouterr().out
    assert "source-host.example" not in out
    assert "Discovery: 1 problem(s), detail in the mail only" in out


def test_notification_mails_and_stays_green(tmp_path, monkeypatch, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"suite": "Discovery", "ok": True, "problems": [], "measured": {},
                             "notify": ["since the last run: 3 new titles", "  X"]}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(p), "--suite", "Discovery",
                                      "--dry-run"])
    assert R.main() == 0
    assert "[FlixShows] Discovery: since the last run: 3 new titles (+1 more)" in capsys.readouterr().out


def test_notification_nobody_can_receive_is_red(tmp_path, monkeypatch):
    for k in ("RESEND_API_KEY", "ALERT_EMAIL", "ALERT_FROM"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"suite": "Discovery", "ok": True, "problems": [], "notify": ["x"]}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--summary", str(p), "--suite", "Discovery"])
    assert R.main() == 1
