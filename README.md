# stream-site-ci

Workflows for FlixShows (flixshows.me). The code lives in `akv2011/stream-site`,
which is private.

## Why two repos

Actions minutes bill to whoever owns the repo the **workflow file** sits in, not
the account that pushed and not the account in the checkout step. So "code
private on akv2011, minutes on GirisankarG" cannot be one repo.

This repo is **public** on purpose: GitHub-hosted runners are unmetered on
public repos, so no quota can be exceeded. Nothing secret belongs in a workflow
file or a log here, and the scripts print no addresses and no source names.

## What runs

| Workflow | Cadence | Needs private code | Asserts |
|---|---|---|---|
| `live-check.yml` | hourly | **no** | the served site: home, robots, sitemap band, stratified sample of advertised pages, real 404s, image project cache |
| `checks.yml` | daily | yes (`CODE_REPO_PAT`) | build, `verify.py`, `phone_audit.py`, `behaviour_test.py` |
| `watchdog.yml` | every 6h | no | each check's latest run reached its own code, and keeps the schedules enabled |
| `discovery.yml` | **manual for now** | yes (`CODE_REPO_PAT`, `TMDB_API_KEY`) | what landed at the source or on TMDB that we do not carry; mails only what moved since the last run |

`checks.yml` also compares the search index it built from `origin/main` with
the one the live site serves. Deploys run from a laptop, so these drift: on
2026-09-24, 98 live titles existed in no pushed commit and the oldest unpushed
commit was 10 days old, so the build checks were testing a site nobody served.
Built from the deployed code the two indexes match exactly, so any difference is
real.

`discovery.yml` is a **notification**, green when it finds something: the
backlog is a to-do list, not a fault. It goes red only when the measurement
itself cannot be trusted, including when the source walls GitHub's runner,
which is reported as "not measured", never as "no new titles". It gets a cron
once `kisskh_crawl.py` lives in the code repo at `scripts/crawl/`.

`live-check.yml` needs no private code so the live signal survives whatever
happens to the token. That split exists because of what happened next.

## What went wrong, so it is not repeated

**From 2026-09-13 to 09-23, all ten runs of `checks.yml` died at step one** with
"Input required and not supplied: token". `CODE_REPO_PAT` had never been
created. GitHub's failure notice went to the account that owns this repo, which
nobody reads, so the four build checks never ran once and nothing said so. Now:

- `checks.yml` refuses to start and names every missing secret.
- Every workflow ends in a `Report` step (`if: always()`) that mails the
  failing step by name. A missing summary is mailed as "never reached its own
  assertions", never read as "nothing wrong".
- `watchdog.yml` reads each latest run's **step list**, not its badge, and
  requires the probe step to have concluded. A skipped probe step is "did not
  run", whatever colour the run is.

**GitHub disables scheduled workflows on a public repo after 60 days without
repository activity.** This repo is rarely pushed. The watchdog re-enables every
workflow on each run, but GitHub does not document whether that resets the
timer, and the watchdog cannot report its own disablement. An outside watch is
still an open item.

## Rules for this repo

- One cron per workflow file. Never gate a job on `github.event.schedule`: on
  the sister site a job gated that way was skipped on every run for four days
  while the workflow reported success.
- A check writes `{"suite", "ok", "problems", "measured"}` and exits non-zero on
  any problem. "Measured nothing" is a problem, never a pass.
- Compare against `baseline.json` (committed, raised deliberately with a reason),
  never against yesterday's output.
- Mail subject is `[FlixShows] <suite>: <first problem>`, built from the finding,
  never a bare count.
- Each check ships with mutation tests in `tests/` that break one thing and
  assert it goes red. The workflow runs them before the check.

## Setup still needed (Arun)

Repository secrets on **GirisankarG/stream-site-ci**, Settings > Secrets and
variables > Actions:

| Secret | Value |
|---|---|
| `CODE_REPO_PAT` | fine-grained token, scoped to `akv2011/stream-site`, **Contents: read** only |
| `RESEND_API_KEY` | the Resend key already used by manhwa-reader |
| `ALERT_EMAIL` | where alerts go |
| `ALERT_FROM` | a sender on a domain verified in Resend, e.g. `FlixShows CI <sync@specterscans.com>` |
| `TMDB_API_KEY` | for `discovery.yml` only |

Until they exist every run is red and says which ones are missing.
