"""Digest: report what MOVED, never the same standing backlog every morning."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import digest as D                                                # noqa: E402

F1 = {"missing_ingestable": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}],
      "behind_on_episodes": [{"id": 9, "title": "I Live Alone", "have": 584, "source": 664}],
      "disappeared": [], "tmdb_missing": [{"tmdb_id": 555, "title": "Neagley", "kind": "tv"}]}


def summary(findings=F1, problems=None):
    return {"suite": "Discovery", "ok": not problems, "problems": problems or [],
            "measured": {"source_titles": 12866}, "findings": findings}


def test_first_run_is_labelled_a_baseline_not_all_new():
    rep, state = D.build_report(summary(), None)
    assert rep["ok"] and rep["notify"][0].startswith("first run, backlog baseline:")
    assert state is not None


def test_unchanged_backlog_is_silent():
    """The whole point: 400 standing lines must not arrive every day."""
    _, s1 = D.build_report(summary(), None)
    rep, _ = D.build_report(summary(), s1)
    assert rep["ok"] and rep["notify"] == []


def test_a_new_title_is_reported_and_only_it():
    _, s1 = D.build_report(summary(), None)
    f2 = json.loads(json.dumps(F1))
    f2["missing_ingestable"].append({"id": 3, "title": "Brand New Drama"})
    rep, _ = D.build_report(summary(f2), s1)
    assert rep["notify"][0] == "since the last run: 1 new source title(s) with episodes, not on the site"
    assert "  Brand New Drama" in rep["notify"] and "  A" not in rep["notify"]


def test_another_episode_on_a_known_behind_series_is_news():
    _, s1 = D.build_report(summary(), None)
    f2 = json.loads(json.dumps(F1))
    f2["behind_on_episodes"][0]["source"] = 665
    rep, _ = D.build_report(summary(f2), s1)
    assert any("I Live Alone: we have 584, source has 665" in l for l in rep["notify"])


def test_unmeasurable_run_is_red_and_keeps_yesterdays_state():
    """An untrustworthy run must never become the comparison baseline."""
    rep, state = D.build_report(summary(problems=["could not measure: list page 1: HTTP 403"]), {"seen": {}})
    assert not rep["ok"] and state is None


def test_missing_findings_is_a_contract_failure_not_all_clear():
    rep, state = D.build_report({"suite": "Discovery", "ok": True, "problems": [], "measured": {}}, None)
    assert not rep["ok"] and "no 'findings'" in rep["problems"][0] and state is None


def test_main_writes_counts_only_to_the_log(tmp_path, monkeypatch, capsys):
    d = tmp_path / "d.json"; d.write_text(json.dumps(summary()))
    monkeypatch.setattr(sys, "argv", ["digest.py", "--discovery", str(d),
                                      "--state", str(tmp_path / "st" / "s.json"),
                                      "--out", str(tmp_path / "r.json")])
    assert D.main() == 0
    out = capsys.readouterr().out
    assert "Neagley" not in out and "I Live Alone" not in out
    assert (tmp_path / "st" / "s.json").exists()


# ----------------------------------------------- stream liveness through the digest

H = lambda host, dead=8: {"host": host, "checked": 8, "alive": 8 - dead, "dead": dead,
                          "unverified": 0, "urls_published": 5580, "why": "HTTP 500"}


def live(dead_hosts):
    return {"suite": "StreamLiveness", "ok": True, "problems": [], "measured": {},
            "findings": {"dead_hosts": dead_hosts, "degraded_hosts": [], "unverified_hosts": []}}


def test_newly_dead_host_is_reported_under_its_own_suite():
    _, s1 = D.build_report(live([]), None)
    rep, _ = D.build_report(live([H("hls16.example")]), s1)
    assert rep["suite"] == "StreamLiveness"
    assert rep["notify"][0] == "since the last run: 1 stream host(s) newly dead"
    assert any("hls16.example: 8 of 8 sampled dead, 5580 streams published (HTTP 500)" in l
               for l in rep["notify"])


def test_host_still_dead_tomorrow_is_silent():
    _, s1 = D.build_report(live([H("hls16.example")]), None)
    rep, _ = D.build_report(live([H("hls16.example")]), s1)
    assert rep["notify"] == []


def test_host_that_plays_again_is_news():
    """Anime_CI_Sentry's rule: mail when a server is newly demoted OR plays again."""
    _, s1 = D.build_report(live([H("hls16.example")]), None)
    rep, _ = D.build_report(live([]), s1)
    assert any("playing again" in l for l in rep["notify"])
