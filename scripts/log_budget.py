"""
Workers Logs on the FlixShows Cloudflare account: under the Free plan's
200,000 events a day, and still recording errors.

Arun, 2026-10-29: "pause all logs, always do it under limit, add CI check, log
in such a way so only get needed info". Per-request records are off; each
Worker writes one "[worker] <status> <method> <path>" line per 5xx it returns,
and a throw logs on its own. Two things can then go wrong, both silently:

- Too many events. Past 200,000 a day the Free plan drops the rest, error
  lines included. Measured 2026-10-29: 5,914 in 24 h, all per-request records.
- Too few. A quiet day can log nothing: 47 5xx in the 7 days to 10-29, 25 of
  them in one day. So a count of 0 proves nothing, and the check makes its own
  error: one signed relay request for a page our site does not have, which the
  relay answers 502, and that event must arrive. It shows in the logs once a
  day as "[worker] 502 GET /m" with the reason "upstream 404".

An unreadable count fails: "measured nothing" is never a pass. Nothing secret
is printed: no token, no signature, no signed URL.

    python scripts/log_budget.py --summary summary.json
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4/accounts/{}/workers/observability/telemetry/query"
RELAY = "https://hls.flixshows.me"
SITE = "https://flixshows.me"
UA = "flixshows-ci-logbudget/1.0 (+https://github.com/GirisankarG/stream-site-ci)"
DAY_LIMIT = 200_000          # Free plan: Cloudflare drops every event past this, errors included
DAY_ALERT = DAY_LIMIT // 2   # mail with room to act before anything is dropped
WAIT_S, POLLS = 15, 12       # Workers Logs land within seconds; give the probe 3 minutes


def http(req: urllib.request.Request) -> tuple[int, bytes]:
    """The network edge. Never raises: status 0 is an unreachable host."""
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                       # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}".encode()


def count(env: dict, t_from: int, t_to: int) -> dict[str, int] | str:
    """'<event type> <script>' -> events stored in [t_from, t_to] ms, every Worker
    on the account, no filter (a filter the API cannot apply answers 0, not an
    error). A string is the reason the count could not be read."""
    body = {"queryId": "flixshows-log-budget", "timeframe": {"from": t_from, "to": t_to}, "limit": 100,
            "parameters": {"datasets": ["cloudflare-workers"], "filters": [],
                           "calculations": [{"operator": "COUNT", "alias": "n"}],
                           "groupBys": [{"type": "string", "value": "$metadata.type"},
                                        {"type": "string", "value": "$workers.scriptName"}],
                           "orderBy": {"value": "n", "order": "desc"}}}
    status, raw = http(urllib.request.Request(
        API.format(env["CLOUDFLARE_ACCOUNT_ID"]), data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}",
                 "Content-Type": "application/json", "User-Agent": UA}))
    if status != 200:
        return f"telemetry API answered HTTP {status}"
    try:
        d = json.loads(raw)
        if not d.get("success"):
            return f"telemetry API refused: {[e.get('message') for e in d.get('errors', [])][:2]}"
        out: dict[str, int] = {}
        for c in d["result"]["calculations"]:
            for a in c["aggregates"]:
                key = " ".join(str(g["value"]) for g in a.get("groups", []))
                out[key] = out.get(key, 0) + int(a["value"])
        return out
    except (ValueError, KeyError, TypeError) as e:
        return f"telemetry answer not understood ({type(e).__name__})"


def probe(env: dict, rng: random.Random) -> int:
    """Ask the relay for a page our own site does not have; it must answer 502."""
    target = f"{SITE}/ci-log-probe-{rng.randrange(10**8)}"
    sig = hmac.new(env["PROXY_SECRET"].encode(), target.encode(), hashlib.sha256).hexdigest()[:32]
    status, _ = http(urllib.request.Request(
        f"{RELAY}/m?u={urllib.parse.quote(target, safe='')}&s={sig}", headers={"User-Agent": UA}))
    return status


def run(env: dict, rng: random.Random, now=None, sleep=None) -> tuple[list[str], dict]:
    now, sleep = now or time.time, sleep or time.sleep
    P: list[str] = []
    M: dict = {}
    ms = lambda: int(now() * 1000)

    # 1) The probe's 502 must reach Workers Logs, or a 5xx is no longer recorded.
    t0 = ms()
    M["probe_status"] = probe(env, rng)
    if M["probe_status"] != 502:
        P.append(f"the relay answered the log probe with HTTP {M['probe_status']}, not 502, "
                 "so no error was made to look for")
    seen: dict[str, int] | str = {}
    for _ in range(POLLS):
        sleep(WAIT_S)
        seen = count(env, t0 - 30_000, ms())
        if isinstance(seen, str) or sum(seen.values()):
            break
    M["events_since_probe"] = seen if isinstance(seen, str) else sum(seen.values())
    if isinstance(seen, str):
        P.append(f"Workers Logs unreadable ({seen}), so whether errors are recorded is unknown")
    elif M["probe_status"] == 502 and not sum(seen.values()):
        P.append(f"the log probe's 502 left no event in Workers Logs within {WAIT_S * POLLS // 60} "
                 "minutes: a 5xx the Workers return is no longer recorded")

    # 2) The day's events against the plan.
    t1 = ms()
    day = count(env, t1 - 86_400_000, t1)
    if isinstance(day, str):
        P.append(f"Workers Logs events unreadable ({day}): the {DAY_LIMIT:,}-a-day limit is unchecked today")
        return P, M
    total = sum(day.values())
    M["events_24h"], M["events_by"] = total, dict(sorted(day.items(), key=lambda kv: -kv[1]))
    if total >= DAY_ALERT:
        top = ", ".join(f"{k} {n:,}" for k, n in list(M["events_by"].items())[:4])
        P.append(f"Workers Logs stored {total:,} events in the last 24 h, past {DAY_ALERT:,}: the Free plan "
                 f"drops everything past {DAY_LIMIT:,} a day, error lines included. Largest: {top}")
    return P, M


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    out = {"suite": "Log budget", "ok": False, "problems": [], "measured": {}}
    try:
        missing = [k for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "PROXY_SECRET") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"not set: {missing}")
        problems, measured = run(dict(os.environ), random.Random())
        out.update(ok=not problems, problems=problems, measured=measured)
    except SystemExit as e:
        out["problems"] = [f"log budget check could not start: {e}"]
    except Exception as e:                                       # noqa: BLE001
        out["problems"] = [f"log budget check crashed: {type(e).__name__}: {e}"]
        traceback.print_exc()
    Path(a.summary).write_text(json.dumps(out, indent=2))
    for k, v in out["measured"].items():
        print(f"  {k:<20} {v}")
    for p in out["problems"]:
        print(f"  PROBLEM {p}")
    print("OK" if out["ok"] else f"FAILED: {len(out['problems'])} problem(s)")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
