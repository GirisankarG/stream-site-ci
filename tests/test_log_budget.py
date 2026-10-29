"""
Break one thing at the network edge, assert the log budget check goes red and
names it. The healthy answers are the shapes the telemetry API and the relay
gave on 2026-10-29.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import log_budget as LB                                           # noqa: E402

ENV = {"CLOUDFLARE_API_TOKEN": "tok-SECRET", "CLOUDFLARE_ACCOUNT_ID": "acct", "PROXY_SECRET": "relay-SECRET"}
DAY = {"cf-worker-event flixshows-hls": 5319, "cf-worker-event flixshows-episode": 502,
       "cf-worker-event flixshows-tmdb": 87}


def answer(counts):
    aggs = [{"groups": [{"key": "$metadata.type", "value": k.split()[0]},
                        {"key": "$workers.scriptName", "value": k.split()[1]}], "value": n}
            for k, n in counts.items()]
    return 200, json.dumps({"success": True, "result": {"calculations": [{"aggregates": aggs}]}}).encode()


def fake(monkeypatch, probe=502, since=None, day=None, telemetry_status=200):
    """The relay answers `probe`; telemetry answers `since` for the short window
    after the probe and `day` for the last 24 h."""
    since = {"cf-worker flixshows-hls": 1} if since is None else since
    day = DAY if day is None else day
    seen = []

    def http(req):
        seen.append(req)
        if req.full_url.startswith(LB.RELAY):
            return probe, b'{"error":"upstream 404"}'
        if telemetry_status != 200:
            return telemetry_status, b'{"success":false}'
        tf = json.loads(req.data)["timeframe"]
        return answer(day if tf["to"] - tf["from"] >= 86_400_000 else since)

    monkeypatch.setattr(LB, "http", http)
    clock = iter(range(1_790_000_000, 1_790_100_000, 15))
    probs, m = LB.run(ENV, random.Random(1), now=lambda: next(clock), sleep=lambda s: None)
    return probs, m, seen


def test_healthy_account_is_silent(monkeypatch):
    probs, m, seen = fake(monkeypatch)
    assert probs == [], probs
    assert m["events_24h"] == 5908 and m["events_since_probe"] == 1 and m["probe_status"] == 502
    relay = [r for r in seen if r.full_url.startswith(LB.RELAY)]
    assert len(relay) == 1 and "/m?u=https%3A%2F%2Fflixshows.me%2Fci-log-probe-" in relay[0].full_url


def test_a_probe_502_that_never_lands_fires(monkeypatch):
    """Invocation records off and the 5xx line not deployed: the error leaves nothing."""
    probs, m, seen = fake(monkeypatch, since={})
    assert any("left no event in Workers Logs" in p for p in probs), probs
    assert sum(1 for r in seen if not r.full_url.startswith(LB.RELAY)) == LB.POLLS + 1


def test_a_quiet_day_is_not_a_failure(monkeypatch):
    """Only error lines are logged, so a day with none is healthy once the probe lands."""
    probs, _, _ = fake(monkeypatch, day={"cf-worker flixshows-hls": 1})
    assert probs == [], probs


def test_a_relay_that_does_not_answer_502_fires(monkeypatch):
    probs, _, _ = fake(monkeypatch, probe=403)
    assert any("answered the log probe with HTTP 403" in p for p in probs), probs


def test_unreadable_telemetry_fires_and_never_reads_as_zero(monkeypatch):
    probs, m, _ = fake(monkeypatch, telemetry_status=403)
    assert any("unreadable (telemetry API answered HTTP 403)" in p for p in probs), probs
    assert any("limit is unchecked today" in p for p in probs), probs
    assert "events_24h" not in m


def test_a_day_past_half_the_plan_fires(monkeypatch):
    probs, _, _ = fake(monkeypatch, day={"cf-worker-event flixshows-hls": LB.DAY_ALERT})
    assert any(f"stored {LB.DAY_ALERT:,} events in the last 24 h" in p for p in probs), probs


def test_no_secret_or_signed_url_reaches_the_output(monkeypatch, tmp_path, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(LB, "http", lambda req: (502, b"") if req.full_url.startswith(LB.RELAY) else answer(DAY))
    monkeypatch.setattr(LB.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["log_budget.py", "--summary", str(tmp_path / "s.json")])
    assert LB.main() == 0
    printed = capsys.readouterr().out + (tmp_path / "s.json").read_text()
    for secret in ("SECRET", "ci-log-probe", "s=", "acct"):
        assert secret not in printed, secret
