#!/usr/bin/env python3
"""Inspect an NDJSON dry-run output against the OmniV01* typedef contract.

Usage:
    python scripts/inspect_dryrun.py [path/to/omni_entities.ndjson]

Reads the NDJSON file produced by a local workflow run with
`save_output_local=true` and prints a structured report covering:

  - Entity counts by type
  - One sample per type
  - Topic detail API coverage (viewSources, baseViewName)
  - Topic -> Document Process emission (lineage)
  - Source-Table -> Topic Process emission (lineage)
  - Red flags: missing qualifiedName, missing enum discriminators, retired
    typeNames sneaking back in, Process without inputs/outputs, etc.

Exits non-zero if a red flag is found so this can gate a CI dry run.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Types this connector is allowed to emit. Anything else is a red flag.
ALLOWED_TYPES = {
    "OmniV01Model",
    "OmniV01Topic",
    "OmniV01Folder",
    "OmniV01Document",
    "Process",
}
# Types from the pre-v0.2 schema. If they show up, the transformer regressed.
RETIRED_TYPES = {
    "omni_connection",
    "omni_model",
    "omni_topic",
    "omni_folder",
    "omni_dashboard",
    "omni_workbook",
    "OmniV01",  # abstract supertype — should never be instantiated
}


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


def section_topic_detail(entities: list[dict[str, Any]]) -> list[str]:
    """Verify the topic detail API ran. viewSources drive source lineage,
    baseViewName + label provide topic context."""
    _h1("Topic detail API coverage")
    topics = [e for e in entities if e.get("typeName") == "OmniV01Topic"]
    if not topics:
        print("  (no OmniV01Topic entities found)")
        return ["no topics emitted"]

    with_baseview = sum(
        1 for t in topics if t["attributes"].get("omniV01BaseViewName")
    )
    n = len(topics)
    _kv("topics total", n)
    _kv("with omniV01BaseViewName", f"{with_baseview}/{n}")

    sample = next((t for t in topics if t["attributes"].get("omniV01BaseViewName")), topics[0])
    _h2("Sample topic")
    print(_sample(sample))

    warnings: list[str] = []
    if with_baseview == 0:
        warnings.append(
            "ZERO topics have omniV01BaseViewName — topic detail API or "
            "YAML parsing may be failing"
        )
    return warnings


def section_topic_to_document_processes(entities: list[dict[str, Any]]) -> list[str]:
    _h1("Topic -> Document Process entities")
    procs = [
        e for e in entities
        if e.get("typeName") == "Process"
        and "/process/topic/" in e["attributes"].get("qualifiedName", "")
    ]
    _kv("topic->document Process entities", len(procs))

    if procs:
        sample = procs[0]
        _h2("Sample Process")
        _kv("qualifiedName", sample["attributes"].get("qualifiedName"))
        _kv("name", sample["attributes"].get("name"))
        rel = sample.get("relationshipAttributes", {})
        inputs = rel.get("inputs", [None])
        outputs = rel.get("outputs", [None])
        _kv("inputs[0]", inputs[0] if inputs else None)
        _kv("outputs[0]", outputs[0] if outputs else None)
        # Validate I/O typeNames match the contract.
        if inputs and inputs[0] and inputs[0].get("typeName") != "OmniV01Topic":
            return [f"Process inputs[0] typeName must be OmniV01Topic, got {inputs[0].get('typeName')}"]
        if outputs and outputs[0] and outputs[0].get("typeName") != "OmniV01Document":
            return [f"Process outputs[0] typeName must be OmniV01Document, got {outputs[0].get('typeName')}"]
        return []

    return ["ZERO topic->document Process entities — lineage will not render in Atlan"]


def section_source_to_topic_processes(entities: list[dict[str, Any]]) -> list[str]:
    _h1("Source-Table -> Topic Process entities")
    procs = [
        e for e in entities
        if e.get("typeName") == "Process"
        and "/process/source/" in e["attributes"].get("qualifiedName", "")
    ]
    _kv("source->topic Process entities", len(procs))
    if not procs:
        print(
            "  (none — atlan_source_connection_map likely not configured, "
            "which is OK for first dry run)"
        )
        return []

    sample = procs[0]
    _h2("Sample Process")
    _kv("qualifiedName", sample["attributes"].get("qualifiedName"))
    _kv("name", sample["attributes"].get("name"))
    inputs = sample.get("relationshipAttributes", {}).get("inputs", [])
    outputs = sample.get("relationshipAttributes", {}).get("outputs", [])
    _kv("inputs count", len(inputs))
    if inputs:
        _kv("first input table QN", inputs[0].get("uniqueAttributes", {}).get("qualifiedName"))
        print("    ^ verify this matches an existing Atlan Table qualifiedName!")

    warnings: list[str] = []
    if outputs and outputs[0].get("typeName") != "OmniV01Topic":
        warnings.append(
            f"Source-to-topic Process outputs[0] typeName must be OmniV01Topic, "
            f"got {outputs[0].get('typeName')}"
        )
    return warnings


def section_red_flags(entities: list[dict[str, Any]]) -> list[str]:
    """Hard correctness checks against the typedef contract."""
    _h1("Red-flag checks")
    issues: list[str] = []

    # 1. Retired type names should never appear.
    retired_hits: Counter = Counter()
    for e in entities:
        if e.get("typeName") in RETIRED_TYPES:
            retired_hits[e["typeName"]] += 1
    if retired_hits:
        for t, n in retired_hits.items():
            issues.append(f"{n} entities use retired typeName '{t}' — transformer regression")

    # 2. Unknown type names.
    unknown = [
        e for e in entities
        if e.get("typeName") not in ALLOWED_TYPES
        and e.get("typeName") not in RETIRED_TYPES
    ]
    if unknown:
        issues.append(
            f"{len(unknown)} entities use unexpected typeName: "
            f"{sorted({e.get('typeName') for e in unknown})}"
        )

    # 3. Missing qualifiedName.
    no_qn = [e for e in entities if not e.get("attributes", {}).get("qualifiedName")]
    if no_qn:
        issues.append(f"{len(no_qn)} entities have no qualifiedName")

    # 4. QN pattern check — must start with default/omni/{digits}/
    bad_qn_prefix = []
    for e in entities:
        qn = e.get("attributes", {}).get("qualifiedName", "")
        if not qn:
            continue
        if not qn.startswith("default/omni/"):
            bad_qn_prefix.append(qn)
            continue
        rest = qn[len("default/omni/"):]
        if "/" not in rest:
            continue
        epoch = rest.split("/", 1)[0]
        if not epoch.isdigit():
            bad_qn_prefix.append(qn)
    if bad_qn_prefix:
        issues.append(
            f"{len(bad_qn_prefix)} qualifiedNames don't match default/omni/{{epoch_ms}}/..."
        )
        for qn in bad_qn_prefix[:3]:
            print(f"    - {qn}")

    # 5. Required enum discriminators.
    docs_missing_type = [
        e for e in entities
        if e.get("typeName") == "OmniV01Document"
        and not e.get("attributes", {}).get("omniV01DocumentType")
    ]
    if docs_missing_type:
        issues.append(
            f"{len(docs_missing_type)} OmniV01Document entities missing required omniV01DocumentType"
        )
    models_missing_kind = [
        e for e in entities
        if e.get("typeName") == "OmniV01Model"
        and not e.get("attributes", {}).get("omniV01ModelKind")
    ]
    if models_missing_kind:
        issues.append(
            f"{len(models_missing_kind)} OmniV01Model entities missing required omniV01ModelKind"
        )

    # 6. Process inputs/outputs sanity.
    bad_processes = []
    for e in entities:
        if e.get("typeName") != "Process":
            continue
        rel = e.get("relationshipAttributes", {})
        if not rel.get("inputs") or not rel.get("outputs"):
            bad_processes.append(e["attributes"].get("qualifiedName"))
    if bad_processes:
        issues.append(
            f"{len(bad_processes)} Process entities have no inputs or outputs"
        )
        for qn in bad_processes[:3]:
            print(f"    - {qn}")

    # 7. Duplicate qualifiedNames.
    qn_counts = Counter(e.get("attributes", {}).get("qualifiedName") for e in entities)
    dupes = [qn for qn, c in qn_counts.items() if c > 1 and qn]
    if dupes:
        issues.append(f"{len(dupes)} duplicate qualifiedNames")
        for qn in dupes[:3]:
            print(f"    - {qn} (x{qn_counts[qn]})")

    # 8. Legacy snake_case sync attrs should be gone.
    legacy_attrs = []
    for e in entities:
        attrs = e.get("attributes", {})
        if any(k in attrs for k in ("connector_name", "last_sync_run", "last_sync_workflow_name")):
            legacy_attrs.append(e.get("typeName"))
    if legacy_attrs:
        issues.append(
            f"{len(legacy_attrs)} entities still carry retired snake_case sync attrs"
        )

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
    warnings += section_topic_detail(entities)
    warnings += section_topic_to_document_processes(entities)
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
