# sourcey-tracker — delivery report

## What was built

`sourcey-tracker` is a zero-dependency Python CLI that tracks [Sourcey](https://sourcey.com) — the open registry of startup credits, deals, and Agent Readiness report cards — as signed immutable releases. Sourcey publishes the record; this tool stores verifiable local copies, diffs release-to-release, renders changelogs from the public feed, and watches for the next release.

## Why it exists

- Sourcey's own guidance tells consumers to record `release_id` and `artifact_sha256` with every stored result — this tool does that automatically and re-verifies on demand.
- No official tooling exists for release-to-release diffing of the three datasets (companies / startup-credits / agent-readiness) or for watching the signed change feed with CI-friendly exit codes.

## Verified behavior (all commands exercised live, 2026-10-02)

- `status` — reports release `sha256:8094c042…`, consistent across all 3 datasets; counts: 543 companies, 530 credits vendors, 596 offers, 25 readiness profiles.
- `snapshot` — stores 4 artifacts (3 datasets + feed) under a content-addressed dir with manifest; local SHA-256 anchors recorded.
- `verify` — re-checks stored bytes; `immutable: true` on the stored snapshot.
- `diff` — synthetic mutation test detected: company addition (TestNewCo), company field change (Devin/category), offer removal (596 -> 595), Agent Readiness grade move (Microsoft A -> F).
- `changelog` — markdown output from feed items between two stored releases.
- `watch --once` — baseline release polling works; exit code 2 is reserved for release change (CI-friendly).

## Trust boundary

- Read-only: GET requests only; never applies for, redeems, ranks, or purchases an offer.
- The registry's `artifact_sha256` is recorded, never recomputed; local hashes are labeled as ours.
- Independent tool — not an official Sourcey product; datasets and APIs belong to Sourcey.

## Files

- `tracker.py` — the tool (single file, stdlib only, Python 3.10+)
- `README.md` — usage, verification table, data sources
- `evidence.json` — machine-readable evidence packet (this report's companion)
- `LICENSE` — MIT
