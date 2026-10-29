"""Omni snapshot -> Atlan entity transformer.

Emits entities aligned with Atlan partner typedef reference v0 (2026-05-15):
- Four concrete types: OmniV01Model, OmniV01Topic, OmniV01Folder, OmniV01Document
- All extend abstract OmniV01 (which extends BI -> Catalog -> Asset)
- Standard Asset.* fields (name, description, sourceURL, sourceUpdatedAt,
  ownerUsers) are populated where Omni exposes the data
- Typed Atlas relationship edges (not string-QN attributes) for model->topic,
  model->baseModel, folder->document, and the built-in Connection edge
- Warehouse->Topic and Topic->Document lineage flow through standard Process
  entities so Atlan's lineage UI/SDK renders them out of the box

The previously-shipped omni_connection, omni_dashboard, and omni_workbook
custom types are retired. The Atlan-side Connection (created out-of-band by
the operator) is referenced via the canonical
default/omni/{connection_epoch_ms} qualifiedName.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application_sdk.observability.logger_adaptor import get_logger

logger = get_logger(__name__)

# Atlan-side enum value sets — defensive normalization for upstream Omni
# strings that may arrive in mixed casing. Values not in these sets are
# dropped rather than emitted as invalid enums. Document type is derived
# deterministically from `hasDashboard`, not normalized from a string.
_MODEL_KINDS = {"SHARED", "WORKBOOK"}
_SCOPES = {"ORGANIZATION", "WORKSPACE", "PRIVATE", "SHARED"}


def _epoch_ms(value: Any) -> int | None:
    """Convert a datetime-ish value to epoch milliseconds.

    Atlan's date attributes (e.g. sourceUpdatedAt) are stored as epoch-ms
    integers. Passing an ISO string causes Atlas to reject the whole
    entity on create — and with `maximum_attempts=1`, one unparseable
    date fails a three-hour crawl. Return None on any parse failure so a
    bad field is a missing attribute, not a lost run.

    A naive datetime is treated as UTC. Reading it in the container's
    local zone would silently mis-timestamp assets by whatever offset the
    pod happens to be running in.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        logger.warning("sourceUpdatedAt: unparseable datetime %r; dropping.", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


class OmniMetadataTransformer:
    def __init__(
        self,
        connection_epoch_ms: str,
        atlan_source_connection_map: dict[str, str] | None = None,
        source_type_resolver: Any = None,
    ):
        if not connection_epoch_ms or not str(connection_epoch_ms).isdigit():
            raise ValueError(
                "connection_epoch_ms is required and must be a digit string."
            )
        self.connection_epoch_ms = str(connection_epoch_ms)
        self.connection_qn = f"default/omni/{self.connection_epoch_ms}"
        # Omni-connection-id -> Atlan source-connection qualifiedName (e.g.
        # the Snowflake/BigQuery connection that backs an Omni model).
        # Drives source-table -> topic Process emission only.
        # Strip trailing slashes and whitespace on operator-supplied paths so a
        # value pasted as `default/snowflake/1700000000/` doesn't produce a
        # double-slash in the table qualifiedName and get rejected by Atlan.
        # Deliberately NO case normalisation — Atlan warehouse qualifiedNames
        # are case-sensitive and vary by warehouse (Snowflake uppercases,
        # Postgres does not).
        self.atlan_source_connection_map = {
            k: str(v).strip().rstrip("/")
            for k, v in (atlan_source_connection_map or {}).items()
            if k and v
        }
        # Resolves warehouse QN -> Atlan typeName (Table / View /
        # MaterialisedView). The hard-coded "Table" that `_processes_source_to_topic`
        # used to emit caused ATLAS-404s on tenants where some sources were
        # views. If None (local dev, no Atlan creds), source-lineage falls
        # back to emitting nothing — we never guess `Table` again.
        self.source_type_resolver = source_type_resolver

    # ------------------------------------------------------------------ #
    # Public entrypoint
    # ------------------------------------------------------------------ #

    def transform(
        self,
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        document_model_ids: list[str] = snapshot.get("document_model_ids", []) or []
        documents = snapshot.get("documents", [])
        connections = snapshot.get("connections", [])
        models = snapshot.get("models", [])
        topics = snapshot.get("topics", [])
        folders = snapshot.get("folders", [])
        # Default to `True` (aggressive) to match `client.fetch_snapshot`'s
        # default, so a snapshot built by an older client without the flag
        # still gets the correct entity filter.
        aggressive_workbook_filter = bool(
            snapshot.get("crawl_only_content_backed_workbooks", True)
        )

        # Lookups for source-table lineage resolution.
        model_to_connection: dict[str, str] = {
            m["id"]: m.get("connectionId")
            for m in models
            if m.get("id") and m.get("connectionId")
        }
        connection_to_database: dict[str, str] = {
            c["id"]: c.get("database")
            for c in connections
            if c.get("id") and c.get("database")
        }

        # (raw_modelId, topic_name) -> owningModelId. A workbook that merely
        # inherits a shared-model topic stamps owningModelId=baseModelId so all
        # entity + Process builders resolve to the shared canonical QN. Topics
        # the workbook actually redefines keep owning==modelId (their own).
        # Used by Process builders to canonicalize tile references pulled from
        # document detail (queryPresentations[].modelId).
        topic_owner: dict[tuple[str, str], str] = {
            (row["modelId"], row["name"]): row.get("owningModelId") or row["modelId"]
            for row in topics
            if row.get("modelId") and row.get("name")
        }

        # Emit-set gating: compute what will actually be emitted BEFORE any
        # relationship gets written, so cross-entity references can be gated
        # on real membership. One rejected record fails Atlan's publish, so a
        # dangling ref to a filtered model/folder/topic is catastrophic.
        emitted_model_ids = {
            str(m["id"])
            for m in models
            if self._should_emit_model(m, document_model_ids, aggressive_workbook_filter)
        }
        emitted_folder_ids = {
            str(f["id"]) for f in folders if f.get("id")
        }
        # Dedup respects emitted_model_ids so an orphaned topic (owner filtered
        # out) never reaches the emit-set. `chosen_topics` is the canonical
        # (qn -> row) map; `emitted_topic_qns` is its key set.
        chosen_topics = self._dedup_topics(topics, emitted_model_ids)
        emitted_topic_qns = set(chosen_topics.keys())

        # Order models parent-first so Atlan's publisher — which commits in
        # batches of 20 and resolves `omniV01BaseModel` as it goes — always has
        # the referent already landed by the time the referrer arrives.
        # Topological order on the `baseModelId` chain; models whose base is
        # NOT in emitted_model_ids (SHARED-on-SCHEMA shape, or any dangling
        # reference we'd otherwise skip in `_models`) are treated as roots.
        ordered_models = self._topologically_sort_models(models, emitted_model_ids)

        entities: list[dict[str, Any]] = []
        entities.extend(self._models(ordered_models, emitted_model_ids))
        entities.extend(self._topics_from_chosen(chosen_topics))
        entities.extend(self._folders(folders))
        entities.extend(self._documents(documents, emitted_folder_ids))
        entities.extend(
            self._processes_topic_to_document(documents, topic_owner, emitted_topic_qns)
        )
        entities.extend(
            self._processes_source_to_topic(
                topics,
                model_to_connection,
                connection_to_database,
                emitted_topic_qns,
            )
        )
        return entities

    @staticmethod
    def _topologically_sort_models(
        models: list[dict[str, Any]],
        emitted_model_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Order models parent-first, following `baseModelId` within the
        emitted set. Non-emitted parents (SHARED-on-SCHEMA shape, or a
        base model the filter dropped) are treated as roots.

        Atlan's publisher commits in batches of ~20 and resolves
        `omniV01BaseModel` as it goes — if a child arrives before its
        parent, the parent QN is unresolvable and the record is
        rejected (ATLAS-404-00-00A). Observed on CCI's 2026-10-28 run:
        4 models missed, cascading to 38 total rejections (topics /
        documents that pointed at them). API order from `/v1/models`
        is not safe; we have to make it safe here.

        Uses Kahn's algorithm so arbitrary chain depth works
        (shared → shared_extension → workbook, etc.). On a cycle —
        shouldn't happen in Omni, but a defective API could — falls
        back to the input order with a WARN rather than returning
        a partial list.
        """
        # Dependency edge: model -> parent (if parent is emitted). Only
        # emitted parents count: if the base will NOT be emitted, our
        # `_models` builder won't write the `omniV01BaseModel` ref either,
        # so there's no ordering constraint from it.
        remaining_deps: dict[str, int] = {}
        children_of: dict[str, list[str]] = {}
        by_id: dict[str, dict[str, Any]] = {}

        for m in models:
            model_id = m.get("id")
            if not model_id:
                continue
            model_id = str(model_id)
            by_id[model_id] = m
            base = m.get("baseModelId")
            if base and base in emitted_model_ids and base != model_id:
                remaining_deps[model_id] = remaining_deps.get(model_id, 0) + 1
                children_of.setdefault(str(base), []).append(model_id)
            else:
                remaining_deps.setdefault(model_id, 0)

        # Roots first — stable within tier so the output is deterministic
        # across runs (same tenant should produce byte-identical NDJSON).
        ready = [mid for mid in by_id if remaining_deps.get(mid, 0) == 0]
        ordered_ids: list[str] = []
        while ready:
            # Preserve input order within a tier.
            tier = sorted(ready, key=lambda mid: list(by_id).index(mid))
            ready = []
            for mid in tier:
                ordered_ids.append(mid)
                for child in children_of.get(mid, []):
                    remaining_deps[child] -= 1
                    if remaining_deps[child] == 0:
                        ready.append(child)

        if len(ordered_ids) != len(by_id):
            missing = [m for m in models if m.get("id") and str(m["id"]) not in ordered_ids]
            logger.warning(
                "model topological sort found a cycle or orphan; "
                f"falling back to input order for {len(missing)} model(s). "
                "This should never happen on real Omni data — investigate."
            )
            # Append the leftovers in input order so we still emit everything.
            for m in missing:
                ordered_ids.append(str(m["id"]))

        return [by_id[mid] for mid in ordered_ids]

    @staticmethod
    def _should_emit_model(
        row: dict[str, Any],
        document_model_ids: list[str] | None,
        aggressive_workbook_filter: bool,
    ) -> bool:
        """Predicate shared by the pre-computation and the emitter — one truth."""
        model_id = row.get("id")
        if not model_id:
            return False
        if row.get("modelKind") == "SCHEMA":
            return False
        content_backed = set(document_model_ids or [])
        if row.get("modelKind") == "WORKBOOK" and model_id not in content_backed:
            if aggressive_workbook_filter or not row.get("name"):
                return False
        # Fails the enum guard? Not emittable.
        return OmniMetadataTransformer._normalize_enum(row.get("modelKind"), _MODEL_KINDS) is not None

    # ------------------------------------------------------------------ #
    # Qualified-name + relationship helpers
    # ------------------------------------------------------------------ #

    def _model_qn(self, model_id: str) -> str:
        return f"{self.connection_qn}/model/{model_id}"

    def _topic_qn(self, model_id: str, topic_name: str) -> str:
        return f"{self.connection_qn}/model/{model_id}/topic/{topic_name}"

    def _folder_qn(self, folder_id: str) -> str:
        return f"{self.connection_qn}/folder/{folder_id}"

    def _document_qn(self, identifier: str) -> str:
        return f"{self.connection_qn}/document/{identifier}"

    @staticmethod
    def _rel_ref(type_name: str, qualified_name: str) -> dict[str, Any]:
        return {
            "typeName": type_name,
            "uniqueAttributes": {"qualifiedName": qualified_name},
        }

    @staticmethod
    def _normalize_enum(value: Any, allowed: set[str]) -> str | None:
        if not value:
            return None
        normalized = str(value).strip().upper()
        return normalized if normalized in allowed else None

    @staticmethod
    def _owner_users(owner: dict[str, Any] | None) -> list[str] | None:
        if not owner:
            return None
        # Prefer email/username over display name for Atlan owner refs.
        candidate = owner.get("email") or owner.get("username") or owner.get("name")
        return [candidate] if candidate else None

    # ------------------------------------------------------------------ #
    # Entity builders
    # ------------------------------------------------------------------ #

    def _models(
        self,
        records: list[dict[str, Any]],
        emitted_model_ids: set[str],
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            model_id = row.get("id")
            if not model_id or model_id not in emitted_model_ids:
                continue
            # emitted_model_ids already applied _should_emit_model, so the
            # kind is guaranteed non-SCHEMA and in {SHARED, WORKBOOK}.
            model_kind = self._normalize_enum(row.get("modelKind"), _MODEL_KINDS)

            qn = self._model_qn(model_id)
            attrs: dict[str, Any] = {
                "qualifiedName": qn,
                "name": row.get("name") or model_id,
                "connectorName": "omni",
                # Inherited plain-string attribute — access policies key on it.
                # There is no `connection` relationship on OmniV01 types; the
                # Connection linkage is expressed via this attribute alone.
                "connectionQualifiedName": self.connection_qn,
                "omniV01Id": model_id,
                "omniV01ModelKind": model_kind,
                "sourceUpdatedAt": _epoch_ms(row.get("updatedAt")),
            }
            description = row.get("description")
            if description:
                attrs["description"] = description
            # No `scope` on /v1/models records (verified against the live API:
            # baseModelId, connectionId, createdAt, deletedAt, id, modelKind,
            # name, updatedAt — that is the whole record). The read could only
            # ever yield None. Folders and documents keep theirs.
            owner_users = self._owner_users(row.get("owner") or {"name": row.get("ownerName")})
            if owner_users:
                attrs["ownerUsers"] = owner_users

            rel_attrs: dict[str, Any] = {}
            base_model_id = row.get("baseModelId")
            # Gate the edge on emit-set membership: the ordinary shape has a
            # SHARED model whose baseModelId points at a SCHEMA (filtered), so
            # emitting the ref would ATLAS-404 on publish for every shared
            # model. Only wire the ref when the base will actually be emitted.
            if base_model_id and base_model_id in emitted_model_ids:
                # Relationship name is the typedef-declared key on this side of
                # the edge (omniV01BaseModel, not baseModel — Atlan drops
                # unknown relationship names silently on write).
                rel_attrs["omniV01BaseModel"] = self._rel_ref(
                    "OmniV01Model", self._model_qn(base_model_id)
                )

            entities.append(
                {
                    "typeName": "OmniV01Model",
                    "attributes": attrs,
                    "relationshipAttributes": rel_attrs,
                }
            )
        return entities

    def _dedup_topics(
        self,
        records: list[dict[str, Any]],
        emitted_model_ids: set[str],
    ) -> dict[str, dict[str, Any]]:
        """Return {canonical_qn: canonical_row}.

        Topics whose OWNING model won't be emitted (SCHEMA / SHARED_EXTENSION /
        filtered workbook / chain fell back to a workbook that was itself
        filtered) are dropped. Otherwise the emitted topic would ATLAS-404
        against its own `omniV01Model` edge.
        """
        chosen: dict[str, dict[str, Any]] = {}
        for row in records:
            model_id = row.get("modelId")
            topic_name = row.get("name")
            if not model_id or not topic_name:
                continue
            owning = row.get("owningModelId") or model_id
            if owning not in emitted_model_ids:
                continue
            qn = self._topic_qn(owning, topic_name)
            row_is_canonical = owning == model_id
            existing = chosen.get(qn)
            if existing is None:
                chosen[qn] = row
                continue
            existing_owning = existing.get("owningModelId") or existing["modelId"]
            existing_is_canonical = existing_owning == existing["modelId"]
            if row_is_canonical and not existing_is_canonical:
                chosen[qn] = row
        return chosen

    def _topics_from_chosen(
        self,
        chosen: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Emit OmniV01Topic entities from the deduped canonical map."""
        entities: list[dict[str, Any]] = []
        for qn, row in chosen.items():
            topic_name = row["name"]
            owning = row.get("owningModelId") or row["modelId"]
            attrs: dict[str, Any] = {
                "qualifiedName": qn,
                "name": row.get("label") or topic_name,
                "connectorName": "omni",
                "connectionQualifiedName": self.connection_qn,
                "omniV01Id": topic_name,
                "omniV01BaseViewName": row.get("baseViewName"),
                "sourceUpdatedAt": _epoch_ms(row.get("updatedAt")),
            }
            description = row.get("description")
            if description:
                attrs["description"] = description

            entities.append(
                {
                    "typeName": "OmniV01Topic",
                    "attributes": attrs,
                    "relationshipAttributes": {
                        # omniV01Model, not `model` — the typedef's declared key.
                        "omniV01Model": self._rel_ref(
                            "OmniV01Model", self._model_qn(owning)
                        ),
                    },
                }
            )
        return entities

    def _folders(
        self,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            folder_id = row.get("id")
            if not folder_id:
                continue
            qn = self._folder_qn(folder_id)
            owner = row.get("owner") or {}
            attrs: dict[str, Any] = {
                "qualifiedName": qn,
                "name": row.get("name") or folder_id,
                "connectorName": "omni",
                "connectionQualifiedName": self.connection_qn,
                "omniV01Id": folder_id,
                "omniV01Path": row.get("path"),
            }
            scope = self._normalize_enum(row.get("scope"), _SCOPES)
            if scope:
                attrs["omniV01Scope"] = scope
            owner_users = self._owner_users(
                owner if owner else {"name": row.get("ownerName")}
            )
            if owner_users:
                attrs["ownerUsers"] = owner_users

            # Empty dict, not omitted: without the key the serializer writes
            # `relationshipAttributes: null` and Atlan's calculate-diff step
            # crashes on subsequent runs (PART-1290).
            entities.append(
                {
                    "typeName": "OmniV01Folder",
                    "attributes": attrs,
                    "relationshipAttributes": {},
                }
            )
        return entities

    def _documents(
        self,
        records: list[dict[str, Any]],
        emitted_folder_ids: set[str],
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            identifier = row.get("identifier")
            if not identifier:
                continue

            doc_type = "DASHBOARD" if row.get("hasDashboard") else "WORKBOOK"
            qn = self._document_qn(identifier)
            owner = row.get("owner") or {}
            folder = row.get("folder") or {}

            attrs: dict[str, Any] = {
                "qualifiedName": qn,
                "name": row.get("name") or identifier,
                "connectorName": "omni",
                "connectionQualifiedName": self.connection_qn,
                "omniV01Id": identifier,
                "omniV01DocumentType": doc_type,
                # omniV01Url is not on the typedef and is dropped; sourceURL
                # (inherited) carries the same value and renders as a link.
                "omniV01FolderPath": folder.get("path"),
                "sourceURL": row.get("url"),
                "sourceUpdatedAt": _epoch_ms(row.get("updatedAt")),
            }
            description = row.get("description")
            if description:
                attrs["description"] = description
            scope = self._normalize_enum(row.get("scope"), _SCOPES)
            if scope:
                attrs["omniV01Scope"] = scope
            owner_users = self._owner_users(
                owner if owner else {"name": row.get("ownerName")}
            )
            if owner_users:
                attrs["ownerUsers"] = owner_users

            rel_attrs: dict[str, Any] = {}
            folder_id = folder.get("id")
            # Gate on emit-set membership: private / personal folders don't
            # appear in /v1/folders, so a doc that lives in one would emit a
            # dangling omniV01Folder relationship and ATLAS-404 the publish.
            if folder_id and str(folder_id) in emitted_folder_ids:
                # omniV01Folder, not `folder` — the typedef's declared key.
                rel_attrs["omniV01Folder"] = self._rel_ref(
                    "OmniV01Folder", self._folder_qn(folder_id)
                )

            entities.append(
                {
                    "typeName": "OmniV01Document",
                    "attributes": attrs,
                    "relationshipAttributes": rel_attrs,
                }
            )
        return entities

    # ------------------------------------------------------------------ #
    # Process entities (warehouse -> topic, topic -> document)
    # ------------------------------------------------------------------ #

    def _processes_topic_to_document(
        self,
        documents: list[dict[str, Any]],
        topic_owner: dict[tuple[str, str], str],
        emitted_topic_qns: set[str],
    ) -> list[dict[str, Any]]:
        """Emit Process entities for each (topic -> document) lineage edge.

        Topic-to-document edges come from `tileTopics` (deduped upstream in
        client._fetch_document_detail). We canonicalize each tile's raw
        `modelId` to its `owningModelId` via `topic_owner` so an inherited
        workbook topic reuses the shared model's canonical topic QN. One
        Process per unique (owning_model, topic, doc).

        A tile that references a topic the run never emitted (topic filtered,
        or a snapshot mismatch) is skipped rather than backfilled — emitting
        would create a Process input that dangles and fails publish.
        """
        entities: list[dict[str, Any]] = []
        for doc in documents:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            doc_qn = self._document_qn(identifier)
            doc_label = doc.get("name") or identifier
            seen: set[tuple[str, str]] = set()
            for tile in doc.get("tileTopics") or []:
                model_id = tile.get("modelId")
                topic_name = tile.get("topicName")
                if not model_id or not topic_name:
                    continue
                # No fallback to the raw model_id — that was the exact bug
                # (Atlan feedback item 2 case 4). If the topic wasn't
                # enumerated, don't fabricate a QN that never resolves.
                owning = topic_owner.get((model_id, topic_name))
                if owning is None:
                    continue
                topic_qn = self._topic_qn(owning, topic_name)
                if topic_qn not in emitted_topic_qns:
                    continue
                key = (owning, topic_name)
                if key in seen:
                    continue
                seen.add(key)
                process_qn = (
                    f"{self.connection_qn}/process/topic/{owning}/{topic_name}"
                    f"/document/{identifier}"
                )
                entities.append(
                    {
                        "typeName": "Process",
                        "attributes": {
                            "qualifiedName": process_qn,
                            "name": f"{topic_name} -> {doc_label}",
                            "connectorName": "omni",
                        },
                        "relationshipAttributes": {
                            "inputs": [self._rel_ref("OmniV01Topic", topic_qn)],
                            "outputs": [self._rel_ref("OmniV01Document", doc_qn)],
                        },
                    }
                )
        return entities

    def _processes_source_to_topic(
        self,
        topics: list[dict[str, Any]],
        model_to_connection: dict[str, str],
        connection_to_database: dict[str, str],
        emitted_topic_qns: set[str],
    ) -> list[dict[str, Any]]:
        """Emit Process entities for each (source-table(s) -> topic) edge.

        Warehouse resolution keys on the ROW's own `modelId` (the workbook or
        shared model that produced the topic) so we resolve the correct
        atlan_source_connection_map entry / fallback database. The topic and
        process QNs, however, are keyed on `owningModelId` — matching the
        canonical OmniV01Topic emitted by `_topics`. Multiple workbook copies
        of the same inherited topic dedup to a single Process.
        """
        if not self.atlan_source_connection_map:
            return []

        entities: list[dict[str, Any]] = []
        seen_process_qns: set[str] = set()
        for row in topics:
            model_id = row.get("modelId")
            topic_name = row.get("name")
            if not model_id or not topic_name:
                continue
            connection_id = model_to_connection.get(model_id)
            if not connection_id:
                continue
            atlan_source_qn = self.atlan_source_connection_map.get(connection_id)
            if not atlan_source_qn:
                continue

            fallback_db = connection_to_database.get(connection_id)
            input_refs: list[dict[str, Any]] = []
            seen_qns: set[str] = set()
            for view in row.get("viewSources") or []:
                table_name = view.get("tableName")
                schema = view.get("schema")
                catalog = view.get("catalog") or fallback_db
                if not table_name or not schema or not catalog:
                    continue
                table_qn = f"{atlan_source_qn}/{catalog}/{schema}/{table_name}"
                if table_qn in seen_qns:
                    continue
                seen_qns.add(table_qn)
                # Resolve the source's typeName via Atlan's catalog. The old
                # hard-coded "Table" caused ATLAS-404s on tenants where the
                # physical object was actually a View or MaterialisedView —
                # Omni's `.view` YAML doesn't carry the object kind, Atlan's
                # catalog does. If the resolver returns None (not configured,
                # not found, lookup errored) we SKIP this source rather than
                # guess, so a dangling ref never reaches publish.
                type_name = (
                    self.source_type_resolver.resolve_type(table_qn)
                    if self.source_type_resolver is not None
                    else None
                )
                if not type_name:
                    continue
                input_refs.append(self._rel_ref(type_name, table_qn))

            if not input_refs:
                continue

            owning = row.get("owningModelId") or model_id
            topic_qn = self._topic_qn(owning, topic_name)
            # Gate on the emit-set: if the canonical topic was dropped (owning
            # model filtered out, or no owning entry from a partial fetch),
            # don't emit a Process pointing at a QN that will ATLAS-404.
            if topic_qn not in emitted_topic_qns:
                continue
            process_qn = (
                f"{self.connection_qn}/process/source/topic/{owning}/{topic_name}"
            )
            if process_qn in seen_process_qns:
                continue
            seen_process_qns.add(process_qn)
            topic_label = row.get("label") or topic_name
            entities.append(
                {
                    "typeName": "Process",
                    "attributes": {
                        "qualifiedName": process_qn,
                        "name": f"sources -> {topic_label}",
                        "connectorName": "omni",
                    },
                    "relationshipAttributes": {
                        "inputs": input_refs,
                        "outputs": [self._rel_ref("OmniV01Topic", topic_qn)],
                    },
                }
            )
        return entities
