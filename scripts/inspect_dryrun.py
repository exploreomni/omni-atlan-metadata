#!/usr/bin/env python3
"""Inspect an NDJSON dry-run output and surface the validations that matter.

Usage:
    python scripts/inspect_dryrun.py [path/to/omni_entities.ndjson]

Reads the NDJSON file produced by a local workflow run with `save_output_local=true`
and prints a structured report covering:

  - Entity counts by type
  - One sample per type
  - Phase 1 (topic enrichment): coverage of sourceTable/Schema/Catalog,
    joined views, dimensions, measures, viewSources
  - Phase 2 (topic -> dashboard lineage): tile-topic capture and Process emission
  - Phase 3 (source -> topic lineage): Process emission, sample table QN
  - Red flags: entities with missing qualifiedName, null required attrs,
    Process entities without inputs/outputs, etc.

Exits non-zero if a red flag is found so this can gate a CI dry run.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _h1(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def _h2(text: str) -> None:
    print(f"\n--- {text} ---")


def _kv(label: str, value: Any, indent: int = 2) -> None:
    print(f"{' ' * indent}{label}: {value}")


def _sample(obj: Any, max_chars: int = 600) -> str:
    s = json.dumps(obj, indent=2, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n  ... [truncated]"
    return s


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        sys.exit(f"ERROR: file not found: {path}")
    entities: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entities.append(json.loads(line))
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: line {i} is not valid JSON: {e}")
    return entities


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section_counts(entities: list[dict[str, Any]]) -> Counter:
    _h1("Entity counts by type")
    counts = Counter(e.get("typeName", "<missing>") for e in entities)
    width = max(len(t) for t in counts) if counts else 10
    for type_name, count in sorted(counts.items()):
        print(f"  {type_name:<{width}}  {count}")
    print(f"  {'TOTAL':<{width}}  {sum(counts.values())}")
    return counts


def section_samples(entities: list[dict[str, Any]]) -> None:
    _h1("Sample entity per type (first occurrence)")
    seen: set[str] = set()
    for e in entities:
        type_name = e.get("typeName", "<missing>")
        if type_name in seen:
            continue
        seen.add(type_name)
        _h2(type_name)
        print(_sample(e))


def section_topic_enrichment(entities: list[dict[str, Any]]) -> list[str]:
    """Phase 1 validation. Returns list of warnings."""
    _h1("Phase 1 — Topic enrichment")
    topics = [e for e in entities if e.get("typeName") == "omni_topic"]
    if not topics:
        print("  (no omni_topic entities found)")
        return ["no topics emitted"]

    has_source = sum(1 for t in topics if t["attributes"].get("sourceTableName"))
    has_schema = sum(1 for t in topics if t["attributes"].get("sourceSchema"))
    has_catalog = sum(1 for t in topics if t["attributes"].get("sourceCatalog"))
    has_joined = sum(1 for t in topics if t["attributes"].get("joinedViewNames"))
    has_dims = sum(1 for t in topics if t["attributes"].get("dimensionNames"))
    has_measures = sum(1 for t in topics if t["attributes"].get("measureNames"))
    n = len(topics)

    _kv("topics total", n)
    _kv(f"with sourceTableName", f"{has_source}/{n}")
    _kv(f"with sourceSchema",    f"{has_schema}/{n}")
    _kv(f"with sourceCatalog",   f"{has_catalog}/{n}  (often null for single-DB connectors — OK)")
    _kv(f"with joinedViewNames", f"{has_joined}/{n}")
    _kv(f"with dimensionNames",  f"{has_dims}/{n}")
    _kv(f"with measureNames",    f"{has_measures}/{n}")

    enriched = next((t for t in topics if t["attributes"].get("sourceTableName")), None)
    if enriched:
        _h2("Sample enriched topic")
        attrs = enriched["attributes"]
        _kv("name", attrs.get("name"))
        _kv("baseViewName", attrs.get("baseViewName"))
        _kv("source", f"{attrs.get('sourceCatalog')}.{attrs.get('sourceSchema')}.{attrs.get('sourceTableName')}")
        _kv("joinedViewNames", attrs.get("joinedViewNames"))
        _kv("dimensions count", len(attrs.get("dimensionNames") or []))
        _kv("measures count", len(attrs.get("measureNames") or []))

    warnings = []
    if has_source == 0:
        warnings.append("ZERO topics have sourceTableName — topic API call may be failing or response shape is unexpected")
    elif has_source < n:
        warnings.append(f"{n - has_source}/{n} topics missing source table (some failed enrichment)")
    return warnings


def section_dashboard_tile_topics(entities: list[dict[str, Any]]) -> list[str]:
    """Phase 2 — tile topic capture on documents."""
    _h1("Phase 2a — Dashboard / Workbook tile-topic capture")
    docs = [e for e in entities if e.get("typeName") in ("omni_dashboard", "omni_workbook")]
    if not docs:
        print("  (no documents found)")
        return []

    dashes = [d for d in docs if d.get("typeName") == "omni_dashboard"]
    with_topics = [d for d in dashes if d["attributes"].get("topicQualifiedNames")]
    _kv("documents total", len(docs))
    _kv("dashboards", len(dashes))
    _kv("dashboards with topicQualifiedNames", f"{len(with_topics)}/{len(dashes)}")

    if with_topics:
        sample = with_topics[0]
        _h2("Sample dashboard with tile topics")
        _kv("name", sample["attributes"].get("name"))
        _kv("topicQualifiedNames", sample["attributes"].get("topicQualifiedNames"))

    warnings = []
    if dashes and not with_topics:
        warnings.append("ZERO dashboards have topicQualifiedNames — queryPresentations parsing may be wrong")
    return warnings


def section_topic_to_dashboard_processes(entities: list[dict[str, Any]]) -> list[str]:
    """Phase 2b — Process entities for topic -> dashboard lineage."""
    _h1("Phase 2b — Topic -> Dashboard Process entities")
    procs = [
        e for e in entities
        if e.get("typeName") == "Process"
        and "/process/topic/" in e["attributes"].get("qualifiedName", "")
    ]
    _kv("topic-to-document Process entities", len(procs))

    if procs:
        sample = procs[0]
        _h2("Sample Process")
        _kv("qualifiedName", sample["attributes"].get("qualifiedName"))
        _kv("name", sample["attributes"].get("name"))
        rel = sample.get("relationshipAttributes", {})
        _kv("inputs[0]", rel.get("inputs", [None])[0])
        _kv("outputs[0]", rel.get("outputs", [None])[0])

    warnings = []
    if not procs:
        warnings.append("ZERO topic-to-document Process entities — lineage will not render in Atlan")
    return warnings


def section_source_to_topic_processes(entities: list[dict[str, Any]]) -> list[str]:
    """Phase 3 — Process entities for source -> topic lineage."""
    _h1("Phase 3 — Source-Table -> Topic Process entities")
    procs = [
        e for e in entities
        if e.get("typeName") == "Process"
        and "/process/source/" in e["attributes"].get("qualifiedName", "")
    ]
    _kv("source-to-topic Process entities", len(procs))
    if not procs:
        print("  (none — atlan_source_connection_map likely not configured, which is OK for first dry run)")
        return []

    sample = procs[0]
    _h2("Sample Process")
    _kv("qualifiedName", sample["attributes"].get("qualifiedName"))
    _kv("name", sample["attributes"].get("name"))
    inputs = sample.get("relationshipAttributes", {}).get("inputs", [])
    _kv("inputs count", len(inputs))
    if inputs:
        _kv("first input table QN", inputs[0].get("uniqueAttributes", {}).get("qualifiedName"))
        print("    ^ verify this matches an existing Atlan Table qualifiedName!")
    return []


def section_red_flags(entities: list[dict[str, Any]]) -> list[str]:
    """Hard correctness checks. Anything found here is a bug."""
    _h1("Red-flag checks")
    issues: list[str] = []

    # Missing qualifiedName
    no_qn = [e for e in entities if not e.get("attributes", {}).get("qualifiedName")]
    if no_qn:
        issues.append(f"{len(no_qn)} entities have no qualifiedName")

    # Process entities missing inputs/outputs
    bad_processes = []
    for e in entities:
        if e.get("typeName") != "Process":
            continue
        rel = e.get("relationshipAttributes", {})
        if not rel.get("inputs") or not rel.get("outputs"):
            bad_processes.append(e["attributes"].get("qualifiedName"))
    if bad_processes:
        issues.append(f"{len(bad_processes)} Process entities have no inputs or outputs")
        for qn in bad_processes[:3]:
            print(f"    - {qn}")

    # Process entities should not have snake_case sync attrs
    leaked = []
    for e in entities:
        if e.get("typeName") != "Process":
            continue
        attrs = e.get("attributes", {})
        if "connector_name" in attrs or "last_sync_run" in attrs:
            leaked.append(e["attributes"].get("qualifiedName"))
    if leaked:
        issues.append(f"{len(leaked)} Process entities have snake_case sync attrs (should be camelCase only)")

    # Duplicate qualifiedNames
    qn_counts = Counter(e.get("attributes", {}).get("qualifiedName") for e in entities)
    dupes = [qn for qn, c in qn_counts.items() if c > 1 and qn]
    if dupes:
        issues.append(f"{len(dupes)} duplicate qualifiedNames")
        for qn in dupes[:3]:
            print(f"    - {qn} (x{qn_counts[qn]})")

    if not issues:
        print("  ✓ no red flags")
    else:
        for issue in issues:
            print(f"  ✗ {issue}")
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "omni_entities.ndjson")
    entities = load(path)
    print(f"Loaded {len(entities)} entities from {path}")

    section_counts(entities)
    section_samples(entities)

    warnings: list[str] = []
    warnings += section_topic_enrichment(entities)
    warnings += section_dashboard_tile_topics(entities)
    warnings += section_topic_to_dashboard_processes(entities)
    warnings += section_source_to_topic_processes(entities)
    red_flags = section_red_flags(entities)

    _h1("Summary")
    if warnings:
        print(f"  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"    ⚠ {w}")
    else:
        print("  ✓ no warnings")
    if red_flags:
        print(f"  {len(red_flags)} red flag(s) — this is a bug, do not deploy")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
