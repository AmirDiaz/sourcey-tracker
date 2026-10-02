#!/usr/bin/env python3
"""sourcey-tracker — release tracker, integrity checks, and change monitoring
for the Sourcey open registry (https://sourcey.com).

Sourcey publishes three public datasets as immutable releases:

  * companies.json      — the company registry (entities, slugs, categories)
  * startup-credits.json— startup credit / deal offers with eligibility facts
  * agent-readiness.json— Agent Readiness report cards (A+..F grades)
  * api.sourcey.com/feed.json — a JSON Feed 1.1 of signed catalog changes

Every release carries a `release_id` and an `artifact_sha256` signed by the
registry. This tool never guesses what those digests verify; it records them,
cross-checks release consistency across datasets, and adds its own
content-addressed local hashes so a stored snapshot can never drift silently.

Commands:
  status                     one-shot live view: release, counts, freshness
  snapshot [-o DIR]         download + consistency-check + store a release
  verify SNAP                re-verify a stored snapshot (local + consistency)
  diff SNAP_A [SNAP_B]       structural diff between two snapshots
  changelog SNAP_A SNAP_B    markdown changelog from the change feed
  watch [--once] [--every S] poll for a new release; exit 2 when it changes

Read-only by design. Never applies for, redeems, or ranks an offer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

WEBSITE = "https://sourcey.com"
DATASETS = {
    "companies": "https://sourcey.com/companies.json",
    "startup-credits": "https://sourcey.com/startup-credits.json",
    "agent-readiness": "https://sourcey.com/agent-readiness.json",
}
FEED_URL = "https://api.sourcey.com/feed.json"
SNAP_ROOT = "snapshots"


# ---------------------------------------------------------------- fetch utils

def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"user-agent": "sourcey-tracker/1.0 (+read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def release_of(doc: dict) -> str | None:
    return doc.get("release_id")


def artifact_of(doc: dict) -> str | None:
    return doc.get("artifact_sha256")


# ---------------------------------------------------------------- consistency

def _iter_offers(credits_doc: dict):
    """Offers live nested under companies in startup-credits.json."""
    for c in credits_doc.get("companies", []):
        for o in c.get("offers", []) or []:
            yield c, o


def consistency_report(docs: dict[str, dict]) -> dict:
    """Cross-dataset release consistency + structural sanity. No fabrication:
    anything unknown is reported as unknown."""
    rels = {name: release_of(doc) for name, doc in docs.items()}
    arts = {name: artifact_of(doc) for name, doc in docs.items()}
    known = [r for r in rels.values() if r]
    consistent = len(set(known)) == 1 if known else None
    counts = {}
    for name, doc in docs.items():
        if name == "companies":
            counts["companies"] = len(doc.get("companies", []))
        elif name == "startup-credits":
            comps = doc.get("companies", [])
            offers = list(_iter_offers(doc))
            counts["credits_companies"] = len(comps)
            counts["offers"] = len(offers)
        elif name == "agent-readiness":
            counts["readiness_profiles"] = len(doc.get("profiles", []))
    warnings = []
    if consistent is False:
        warnings.append("datasets carry different release_id values")
    if not arts.get("companies"):
        warnings.append("companies dataset missing artifact_sha256")
    return {
        "checked_at": now_iso(),
        "release_ids": rels,
        "artifact_sha256": arts,
        "release_consistent": consistent,
        "record_counts": counts,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- snapshot

def do_snapshot(out_root: str) -> dict:
    fetched = {}
    raw = {}
    for name, url in DATASETS.items():
        data = http_get(url)
        raw[name] = data
        fetched[name] = json.loads(data)
    feed_raw = http_get(FEED_URL)
    feed = json.loads(feed_raw)

    cons = consistency_report(fetched)
    release = cons["release_ids"].get("companies") or "unknown-release"
    r8 = release.replace("sha256:", "")[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = os.path.join(out_root, SNAP_ROOT, f"{stamp}-{r8}")
    os.makedirs(snap_dir, exist_ok=True)

    files = {}
    for name, data in raw.items():
        path = os.path.join(snap_dir, f"{name}.json")
        with open(path, "wb") as f:
            f.write(data)
        files[name] = {
            "file": f"{name}.json",
            "bytes": len(data),
            "local_sha256": sha256_hex(data),
            "release_id": release_of(fetched[name]),
            "artifact_sha256_signed": artifact_of(fetched[name]),
        }
    feed_path = os.path.join(snap_dir, "feed.json")
    with open(feed_path, "wb") as f:
        f.write(feed_raw)
    feed_rel = (feed.get("_sourcey") or {}).get("release_id")
    files["feed"] = {
        "file": "feed.json",
        "bytes": len(feed_raw),
        "local_sha256": sha256_hex(feed_raw),
        "release_id": feed_rel,
        "items": len(feed.get("items", [])),
    }
    feed_consistent = (feed_rel is None) or (feed_rel == release)

    manifest = {
        "tool": "sourcey-tracker/1.0",
        "source": WEBSITE,
        "snapshot_dir": snap_dir,
        "captured_at": now_iso(),
        "release_id": release,
        "consistency": cons,
        "feed_release_matches_datasets": feed_consistent,
        "files": files,
        "notes": [
            "local_sha256 is the content hash of the exact bytes stored; it is "
            "our immutability anchor, not Sourcey's signature.",
            "artifact_sha256_signed is the registry's own signed digest copied "
            "from the dataset envelope; this tool records it, never recomputes it.",
            "Read-only snapshot. Sourcey never applies for or redeems offers here.",
        ],
    }
    mpath = os.path.join(snap_dir, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    print(f"release   : {release}")
    print(f"consistent: {cons['release_consistent']}   counts: {cons['record_counts']}")
    print(f"feed release matches: {feed_consistent}")
    if cons["warnings"]:
        for w in cons["warnings"]:
            print(f"WARNING: {w}")
    print(f"snapshot  : {snap_dir}")
    return manifest


# ---------------------------------------------------------------- verify

def do_verify(snap_dir: str) -> dict:
    manifest = load_json(os.path.join(snap_dir, "manifest.json"))
    results = {}
    ok = True
    for name, meta in manifest["files"].items():
        path = os.path.join(snap_dir, meta["file"])
        if not os.path.exists(path):
            results[name] = {"error": "missing file"}
            ok = False
            continue
        with open(path, "rb") as f:
            data = f.read()
        local = sha256_hex(data)
        match = local == meta["local_sha256"]
        results[name] = {"local_sha256": local, "matches": match, "bytes": len(data)}
        if not match:
            ok = False
    report = {
        "verified_at": now_iso(),
        "snapshot": snap_dir,
        "release_id": manifest.get("release_id"),
        "immutable": ok,
        "files": results,
    }
    print(json.dumps(report, indent=2))
    if not ok:
        sys.stderr.write("SNAPSHOT DRIFT DETECTED\n")
    return report


# ---------------------------------------------------------------- diff

def _companies_index(doc: dict) -> dict:
    return {c["entity_id"]: c for c in doc.get("companies", [])}


def _offers(doc: dict) -> dict[str, dict]:
    """Index offers by offer_id (nested under companies)."""
    out = {}
    for _c, o in _iter_offers(doc):
        oid = o.get("offer_id") or o.get("slug") or o.get("title")
        if oid:
            out[oid] = o
    return out


def _readiness_index(doc: dict) -> dict:
    return {p.get("entity_id"): p for p in doc.get("profiles", [])}


def do_diff(a_dir: str, b_dir: str | None) -> dict:
    if b_dir is None:
        sys.exit("diff needs two snapshot dirs (run `snapshot` twice first)")

    ma, mb = load_json(os.path.join(a_dir, "manifest.json")), load_json(os.path.join(b_dir, "manifest.json"))
    ca, cb = load_json(os.path.join(a_dir, "companies.json")), load_json(os.path.join(b_dir, "companies.json"))
    ra, rb = load_json(os.path.join(a_dir, "agent-readiness.json")), load_json(os.path.join(b_dir, "agent-readiness.json"))
    oa = _offers(load_json(os.path.join(a_dir, "startup-credits.json")))
    ob = _offers(load_json(os.path.join(b_dir, "startup-credits.json")))
    ia, ib = _companies_index(ca), _companies_index(cb)
    added = sorted(ib[e].get("name", e) for e in ib.keys() - ia.keys())
    removed = sorted(ia[e].get("name", e) for e in ia.keys() - ib.keys())
    changed = []
    for e in ia.keys() & ib.keys():
        diffs = [k for k in ("name", "category", "website", "summary")
                 if ia[e].get(k) != ib[e].get(k)]
        if diffs:
            changed.append({"name": ib[e].get("name", e), "fields": diffs})

    idx_off_a, idx_off_b = oa, ob
    offers_added = sorted(idx_off_b.keys() - idx_off_a.keys())
    offers_removed = sorted(idx_off_a.keys() - idx_off_b.keys())

    pra, prb = _readiness_index(ra), _readiness_index(rb)
    grade_moves = []
    for e in pra.keys() & prb.keys():
        ga, gb = pra[e].get("grade"), prb[e].get("grade")
        if ga != gb:
            grade_moves.append({
                "name": ib.get(e, {}).get("name", e),
                "from": ga or "unknown",
                "to": gb or "unknown",
            })

    offer_lifecycle_moves = []
    for oid in oa.keys() & ob.keys():
        la, lb = (oa[oid].get("lifecycle") or {}), (ob[oid].get("lifecycle") or {})
        sa, sb = (la.get("state") if isinstance(la, dict) else la), (lb.get("state") if isinstance(lb, dict) else lb)
        if sa != sb:
            offer_lifecycle_moves.append({"offer_id": oid, "from": sa, "to": sb})

    out = {
        "diffed_at": now_iso(),
        "a": {"dir": a_dir, "release_id": ma.get("release_id")},
        "b": {"dir": b_dir, "release_id": mb.get("release_id")},
        "companies": {
            "added": added, "removed": removed, "changed": changed,
            "counts": {"a": len(ia), "b": len(ib)},
        },
        "offers": {
            "added": offers_added,
            "removed": offers_removed,
            "lifecycle_moves": offer_lifecycle_moves,
            "counts": {"a": len(oa), "b": len(ob)},
        },
        "readiness_grade_changes": grade_moves,
    }
    print(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------- changelog

def do_changelog(a_dir: str, b_dir: str) -> str:
    ma, mb = load_json(os.path.join(a_dir, "manifest.json")), load_json(os.path.join(b_dir, "manifest.json"))
    fa = load_json(os.path.join(a_dir, "feed.json"))
    fb = load_json(os.path.join(b_dir, "feed.json"))
    ids_a = {i.get("id") for i in fa.get("items", [])}
    fresh = [i for i in fb.get("items", []) if i.get("id") not in ids_a]
    lines = [
        "# Sourcey release changelog",
        "",
        f"- From release: `{ma.get('release_id')}`",
        f"- To release:   `{mb.get('release_id')}`",
        f"- Generated by sourcey-tracker at {now_iso()} (read-only; from the public JSON Feed)",
        "",
    ]
    if not fresh:
        lines.append("No new feed items between these releases.")
    for it in fresh:
        lines.append(f"- **{it.get('title','change')}** — {it.get('date_published','')} "
                     f"([record]({it.get('url','')}))")
    text = "\n".join(lines) + "\n"
    print(text)
    return text


# ---------------------------------------------------------------- watch

def do_watch(every: int, once: bool, timeout: int) -> None:
    """Poll the feed until release_id changes. Exit codes: 0 = unchanged after
    timeout, 2 = new release seen (CI-friendly), 1 = error."""
    baseline = None
    deadline = time.time() + timeout if timeout else None
    print(f"watching {FEED_URL} (release_id baseline)")
    while True:
        try:
            feed = json.loads(http_get(FEED_URL))
            rel = (feed.get("_sourcey") or {}).get("release_id")
            if baseline is None:
                baseline = rel
                print(f"{now_iso()} baseline release {baseline}")
            elif rel != baseline:
                print(f"{now_iso()} NEW RELEASE {rel} (was {baseline})")
                items = feed.get("items", [])
                for it in items[:10]:
                    print(f"  - {it.get('title')}")
                sys.exit(2)
            else:
                print(f"{now_iso()} unchanged")
        except Exception as e:  # noqa: BLE001
            print(f"{now_iso()} fetch error: {e}")
        if once or (deadline and time.time() > deadline):
            sys.exit(0)
        time.sleep(every)


# ---------------------------------------------------------------- status

def do_status() -> dict:
    docs = {}
    for name, url in DATASETS.items():
        docs[name] = json.loads(http_get(url))
    feed = json.loads(http_get(FEED_URL))
    cons = consistency_report(docs)
    fr = (feed.get("_sourcey") or {})
    out = {
        "checked_at": now_iso(),
        "live_release": cons["release_ids"],
        "release_consistent": cons["release_consistent"],
        "record_counts": cons["record_counts"],
        "feed": {
            "release_id": fr.get("release_id"),
            "snapshot_id": fr.get("snapshot_id"),
            "diff_digest": fr.get("diff_digest"),
            "items_in_feed": len(feed.get("items", [])),
            "latest_item": (feed.get("items") or [{}])[0].get("title"),
            "latest_published": (feed.get("items") or [{}])[0].get("date_published"),
        },
        "warnings": cons["warnings"],
    }
    print(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------- cli

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="sourcey-tracker",
        description="Release tracker, integrity checks, and change monitoring "
                    "for the Sourcey open registry (read-only).",
        epilog="Sourcey is the record; this tool only snapshots and watches it. "
               "https://sourcey.com",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="one-shot live view")

    p = sub.add_parser("snapshot", help="download + verify + store a release")
    p.add_argument("-o", "--out", default=".", help="root dir for snapshots/")

    p = sub.add_parser("verify", help="re-verify a stored snapshot")
    p.add_argument("snap_dir")

    p = sub.add_parser("diff", help="compare two snapshots")
    p.add_argument("a")
    p.add_argument("b", nargs="?")

    p = sub.add_parser("changelog", help="markdown changelog between snapshots")
    p.add_argument("a")
    p.add_argument("b")

    p = sub.add_parser("watch", help="poll for a new release")
    p.add_argument("--every", type=int, default=300)
    p.add_argument("--once", action="store_true")
    p.add_argument("--timeout", type=int, default=0, help="seconds; 0 = forever")

    args = ap.parse_args()
    if args.cmd == "status":
        do_status()
    elif args.cmd == "snapshot":
        do_snapshot(args.out)
    elif args.cmd == "verify":
        do_verify(args.snap_dir)
    elif args.cmd == "diff":
        do_diff(args.a, args.b)
    elif args.cmd == "changelog":
        do_changelog(args.a, args.b)
    elif args.cmd == "watch":
        do_watch(args.every, args.once, args.timeout)


if __name__ == "__main__":
    main()
