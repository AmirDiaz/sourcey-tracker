# sourcey-tracker

**Release tracker, integrity checker, and change monitor for the [Sourcey](https://sourcey.com) open registry — with zero dependencies (Python 3 stdlib only).**

[Sourcey](https://sourcey.com) is the open registry of startup credits, deals, and Agent Readiness report cards. As of October 2, 2026 it publishes **543 companies**, **596 startup-credit offers** across 530 vendors, and **25 Agent Readiness profiles** as signed, immutable releases — every record carries a `release_id`, `revision_digest`, and provenance, and the catalog moves through a signed change feed.

Sourcey gives you the record. This tool watches it move:

- **`status`** — one-shot live view: current release, record counts, feed freshness, consistency warnings
- **`snapshot`** — download all three datasets + the change feed, cross-check release consistency, store an immutable, content-addressed local copy
- **`verify`** — re-verify a stored snapshot later; local SHA-256 anchors make silent drift impossible
- **`diff`** — structural comparison of two snapshots: companies added/removed/changed, offers added/withdrawn, offer lifecycle moves, Agent Readiness grade changes
- **`changelog`** — markdown changelog between two releases, built from Sourcey's public JSON Feed
- **`watch`** — poll for the next signed release; exits with code `2` when the release changes (CI/cron friendly)

```text
$ python3 tracker.py status
live_release: sha256:8094c042ec14… (consistent across all 3 datasets)
record_counts: {companies: 543, credits_companies: 530, offers: 596, readiness_profiles: 25}

$ python3 tracker.py snapshot
release   : sha256:8094c042ec14…
consistent: True    feed release matches: True
snapshot  : snapshots/20261002T184036Z-8094c042ec14/

$ python3 tracker.py diff snapshots/A snapshots/B
companies.added: ["…"], offers.removed: […], readiness_grade_changes: [{name: "…", from: "A", to: "B"}]
```

## Why

Sourcey treats every answer as **a projection of one immutable release, not timeless truth** — and tells agents to record `release_id` and `artifact_sha256` with every stored result. If you consume Sourcey data in pipelines, research, or agent memory, you still need three things Sourcey's read surface intentionally leaves to you:

1. **A verifiable local copy** — so your stored numbers can be re-checked later against the exact bytes you saw.
2. **Release-to-release diffs** — "what changed between the release I cited and the one live now?" for companies, offers, lifecycle, and readiness grades.
3. **A watcher** — alert when the signed release moves, without hand-rolling polling against three endpoints.

`sourcey-tracker` does exactly those three, read-only, with no API key, and no dependencies beyond Python 3.

## Install

```bash
git clone https://github.com/AmirDiaz/sourcey-tracker.git
cd sourcey-tracker
python3 tracker.py status
```

That's it — no `pip install`, no virtualenv. Works on any Python 3.10+.

## Usage

### Take a snapshot

```bash
python3 tracker.py snapshot            # stores under ./snapshots/<utc>-<release12>/
python3 tracker.py snapshot -o /data   # or choose a root
```

Each snapshot directory contains the four artifacts plus a `manifest.json`:

```json
{
  "release_id": "sha256:8094c042…",
  "consistency": { "release_consistent": true, "record_counts": { … } },
  "files": {
    "companies": { "local_sha256": "sha256:d2f4976b…", "artifact_sha256_signed": "sha256:abfbd3a1…" },
    …
  }
}
```

### Verify a snapshot is untouched

```bash
python3 tracker.py verify snapshots/20261002T184036Z-8094c042ec14
```

Exits non-zero and prints `SNAPSHOT DRIFT DETECTED` if any stored file no longer matches its recorded local hash.

### Diff two releases

```bash
python3 tracker.py diff snapshots/<old> snapshots/<new>
```

Reports company additions/removals/field changes, offer additions/removals/lifecycle moves, and Agent Readiness grade transitions, each tied to the two `release_id`s.

### Generate a changelog

```bash
python3 tracker.py changelog snapshots/<old> snapshots/<new> > CHANGES.md
```

### Watch for the next release

```bash
python3 tracker.py watch                # poll every 5 minutes, forever
python3 tracker.py watch --once          # single check, exit 0
python3 tracker.py watch --every 60 --timeout 3600
```

Exit code `2` = new signed release detected (print the first feed items). Drop it in cron, GitHub Actions, or a systemd timer.

## What is (and is not) verified

Being precise about the trust boundary, because Sourcey is:

| What | How |
|---|---|
| `local_sha256` | SHA-256 of the exact bytes stored — our immutability anchor |
| `artifact_sha256_signed` | Copied from the dataset envelope; recorded, **never recomputed** |
| Release consistency | All 3 datasets + feed must agree on `release_id` |
| Offer/company/grade diffs | Computed only between stored snapshots, always labelled with both releases |

This tool never applies for, redeems, ranks, or purchases an offer, and never converts unknown eligibility into approval. For tool-native discovery prefer [Sourcey's hosted MCP server](https://mcp.sourcey.com/mcp); for deterministic integration use [their HTTP API](https://api.sourcey.com/openapi.yml). `sourcey-tracker` is an independent read-only consumer of the public datasets and JSON Feed — not an official Sourcey product.

## Data sources

- Datasets: [companies.json](https://sourcey.com/companies.json) · [startup-credits.json](https://sourcey.com/startup-credits.json) · [agent-readiness.json](https://sourcey.com/agent-readiness.json)
- Change feed (JSON Feed 1.1): [api.sourcey.com/feed.json](https://api.sourcey.com/feed.json) · [changes.ndjson](https://sourcey.com/changes.ndjson)
- Registry: [sourcey.com](https://sourcey.com) · repository: [github.com/sourcey/startup-credits](https://github.com/sourcey/startup-credits)

## License

MIT — same as this repo's LICENSE file. Data belongs to Sourcey and its publishers; this tool only reads their public endpoints and clearly labels every release it touches.
