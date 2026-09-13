# stream-site-ci

Workflows only. The code lives in `akv2011/stream-site`, which is private.

## Why two repos

Actions minutes bill to whoever owns the repo the **workflow file** sits in, not
the account that pushed and not the account in the checkout step. So "code
private on akv2011, minutes on GirisankarG" cannot be one repo.

This repo is **public** on purpose: GitHub-hosted runners are unmetered on
public repos, so no quota can be exceeded. Nothing secret belongs in a workflow
file here.

## What it runs

The four checks from the code repo, cheapest gate first, each earning its place
by catching something the others missed:

| Check | Found |
|---|---|
| Python syntax | a mangled import line, twice in one day |
| `verify.py` | 1,045 pages announcing the wrong catalogue |
| `phone_audit.py` | every watch page scrolling 528px sideways on a phone |
| `behaviour_test.py` | a status pill that could never appear |

## Setup still needed

`CODE_REPO_PAT` as a repository secret here: a fine-grained token scoped to
`akv2011/stream-site` with **Contents: read** only. Arun creates and rotates it;
without it the checkout step cannot read the private code repo.

Worth adding later: a failure mail step. GitHub's own failure notice goes to the
account owning this repo, which is not an inbox anyone reads. See
`specter-wiki/docs/ci.md` for the pattern.
