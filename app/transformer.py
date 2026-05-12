from __future__ import annotations

from typing import Any


class OmniMetadataTransformer:
    def __init__(
        self,
        tenant_id: str,
        atlan_source_connection_map: dict[str, str] | None = None,
    ):
        self.tenant_id = tenant_id or "omni"
        # Maps an Omni connection ID to the Atlan qualifiedName of the
        # corresponding source-database connection (Snowflake, Redshift, etc.).
        # Used to emit Source-Table -> Topic lineage; empty map disables it.
        self.atlan_source_connection_map = atlan_source_connection_map or {}

    def transform(
        self,
        snapshot: dict[str, Any],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        document_model_ids: set[str] = snapshot.get("document_model_ids", set())
        documents = snapshot.get("documents", [])
        connections = snapshot.get("connections", [])
        models = snapshot.get("models", [])
        topics = snapshot.get("topics", [])

        # Build lookups for cross-referencing topics back to their connection
        # so we can resolve the Atlan source-connection qualifiedName.
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

        entities: list[dict[str, Any]] = []
        entities.extend(self._connections(connections, workflow_id, workflow_run_id))
        entities.extend(self._models(models, workflow_id, workflow_run_id, document_model_ids))
        entities.extend(self._topics(topics, workflow_id, workflow_run_id))
        entities.extend(self._folders(snapshot.get("folders", []), workflow_id, workflow_run_id))
        entities.extend(self._documents(documents, workflow_id, workflow_run_id))
        entities.extend(self._processes_topic_to_dashboard(documents))
        entities.extend(
            self._processes_source_to_topic(
                topics,
                model_to_connection,
                connection_to_database,
            )
        )
        return entities

    def _base_custom_attributes(self, workflow_id: str, workflow_run_id: str) -> dict[str, str]:
        return {
            "last_sync_workflow_name": workflow_id,
            "last_sync_run": workflow_run_id,
            "connector_name": "omni",
        }

    @staticmethod
    def _rel_ref(type_name: str, qualified_name: str) -> dict[str, Any]:
        """Build an Atlas relationship reference by qualified name."""
        return {
            "typeName": type_name,
            "uniqueAttributes": {"qualifiedName": qualified_name},
        }

    def _connections(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            omni_id = row.get("id")
            if not omni_id:
                continue
            entities.append(
                {
                    "typeName": "omni_connection",
                    "attributes": {
                        "qualifiedName": f"{self.tenant_id}/connection/{omni_id}",
                        "name": row.get("name") or omni_id,
                        "omniId": omni_id,
                        "dialect": row.get("dialect"),
                        "database": row.get("database"),
                        **self._base_custom_attributes(workflow_id, workflow_run_id),
                    },
                }
            )
        return entities

    def _models(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
        document_model_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            model_id = row.get("id")
            if not model_id:
                continue
            if row.get("modelKind") == "SCHEMA":
                continue
            # Exclude unnamed WORKBOOK models that aren't backing a document.
            if row.get("modelKind") == "WORKBOOK" and not row.get("name"):
                if document_model_ids is None or model_id not in document_model_ids:
                    continue
            conn_id = row.get("connectionId")
            base_model_id = row.get("baseModelId")
            rel_attrs: dict[str, Any] = {}
            if conn_id:
                rel_attrs["connectionQualifiedName"] = self._rel_ref(
                    "omni_connection", f"{self.tenant_id}/connection/{conn_id}"
                )
            if base_model_id:
                rel_attrs["baseModelQualifiedName"] = self._rel_ref(
                    "omni_model", f"{self.tenant_id}/model/{base_model_id}"
                )
            entity: dict[str, Any] = {
                "typeName": "omni_model",
                "attributes": {
                    "qualifiedName": f"{self.tenant_id}/model/{model_id}",
                    "name": row.get("name") or model_id,
                    "omniId": model_id,
                    "modelKind": row.get("modelKind"),
                    "updatedAt": row.get("updatedAt"),
                    "connectionQualifiedName": (
                        f"{self.tenant_id}/connection/{conn_id}" if conn_id else None
                    ),
                    "baseModelQualifiedName": (
                        f"{self.tenant_id}/model/{base_model_id}" if base_model_id else None
                    ),
                    **self._base_custom_attributes(workflow_id, workflow_run_id),
                },
            }
            if rel_attrs:
                entity["relationshipAttributes"] = rel_attrs
            entities.append(entity)
        return entities

    def _topics(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            model_id = row.get("modelId")
            topic_name = row.get("name")
            if not model_id or not topic_name:
                continue
            entities.append(
                {
                    "typeName": "omni_topic",
                    "attributes": {
                        "qualifiedName": f"{self.tenant_id}/model/{model_id}/topic/{topic_name}",
                        "name": row.get("label") or topic_name,
                        "omniName": topic_name,
                        "baseViewName": row.get("baseViewName"),
                        "modelQualifiedName": f"{self.tenant_id}/model/{model_id}",
                        "sourceTableName": row.get("sourceTableName"),
                        "sourceSchema": row.get("sourceSchema"),
                        "sourceCatalog": row.get("sourceCatalog"),
                        "joinedViewNames": row.get("joinedViewNames") or None,
                        "dimensionNames": row.get("dimensionNames") or None,
                        "measureNames": row.get("measureNames") or None,
                        **self._base_custom_attributes(workflow_id, workflow_run_id),
                    },
                    "relationshipAttributes": {
                        "modelQualifiedName": self._rel_ref(
                            "omni_model", f"{self.tenant_id}/model/{model_id}"
                        ),
                    },
                }
            )
        return entities

    def _folders(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            folder_id = row.get("id")
            if not folder_id:
                continue
            owner = row.get("owner") or {}
            entities.append(
                {
                    "typeName": "omni_folder",
                    "attributes": {
                        "qualifiedName": f"{self.tenant_id}/folder/{folder_id}",
                        "name": row.get("name") or folder_id,
                        "omniId": folder_id,
                        "path": row.get("path"),
                        "scope": row.get("scope"),
                        "ownerId": owner.get("id"),
                        "ownerName": owner.get("name"),
                        **self._base_custom_attributes(workflow_id, workflow_run_id),
                    },
                }
            )
        return entities

    def _documents(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            identifier = row.get("identifier")
            if not identifier:
                continue
            owner = row.get("owner") or {}
            folder = row.get("folder") or {}
            doc_type = "omni_dashboard" if row.get("hasDashboard") else "omni_workbook"
            conn_id = row.get("connectionId")
            folder_id = folder.get("id")

            topic_qns = sorted({
                f"{self.tenant_id}/model/{t['modelId']}/topic/{t['topicName']}"
                for t in (row.get("tileTopics") or [])
                if t.get("modelId") and t.get("topicName")
            })

            rel_attrs = {}
            if conn_id:
                rel_attrs["connectionQualifiedName"] = self._rel_ref(
                    "omni_connection", f"{self.tenant_id}/connection/{conn_id}"
                )
            if folder_id:
                rel_attrs["folderQualifiedName"] = self._rel_ref(
                    "omni_folder", f"{self.tenant_id}/folder/{folder_id}"
                )
            entity = {
                "typeName": doc_type,
                "attributes": {
                    "qualifiedName": f"{self.tenant_id}/document/{identifier}",
                    "name": row.get("name") or identifier,
                    "omniId": identifier,
                    "scope": row.get("scope"),
                    "url": row.get("url"),
                    "updatedAt": row.get("updatedAt"),
                    "sourceType": row.get("type"),
                    "ownerId": owner.get("id"),
                    "ownerName": owner.get("name"),
                    "folderPath": folder.get("path"),
                    "connectionQualifiedName": (
                        f"{self.tenant_id}/connection/{conn_id}" if conn_id else None
                    ),
                    "folderQualifiedName": (
                        f"{self.tenant_id}/folder/{folder_id}" if folder_id else None
                    ),
                    "topicQualifiedNames": topic_qns or None,
                    **self._base_custom_attributes(workflow_id, workflow_run_id),
                },
            }
            if rel_attrs:
                entity["relationshipAttributes"] = rel_attrs
            entities.append(entity)
        return entities

    def _processes_topic_to_dashboard(
        self,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Emit Atlan Process entities for each (topic -> document) lineage edge.

        Atlan renders a Process in the lineage graph when its `inputs` and
        `outputs` reference assets that exist in the catalog. We emit one
        Process per (topic, document) pair derived from the document's
        `tileTopics` (already deduplicated upstream in the client).

        Sync-tracking attributes (last_sync_run, etc.) are intentionally
        omitted — those are registered on our custom typedefs only, not on
        Atlan's built-in Process supertype.
        """
        entities: list[dict[str, Any]] = []
        for doc in documents:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            doc_qn = f"{self.tenant_id}/document/{identifier}"
            doc_type = "omni_dashboard" if doc.get("hasDashboard") else "omni_workbook"
            doc_label = doc.get("name") or identifier
            seen: set[tuple[str, str]] = set()
            for tile in doc.get("tileTopics") or []:
                model_id = tile.get("modelId")
                topic_name = tile.get("topicName")
                if not model_id or not topic_name:
                    continue
                key = (model_id, topic_name)
                if key in seen:
                    continue
                seen.add(key)
                topic_qn = f"{self.tenant_id}/model/{model_id}/topic/{topic_name}"
                process_qn = (
                    f"{self.tenant_id}/process/topic/{model_id}/{topic_name}"
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
                            "inputs": [self._rel_ref("omni_topic", topic_qn)],
                            "outputs": [self._rel_ref(doc_type, doc_qn)],
                        },
                    }
                )
        return entities

    def _processes_source_to_topic(
        self,
        topics: list[dict[str, Any]],
        model_to_connection: dict[str, str],
        connection_to_database: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Emit Atlan Process entities for each (source-table(s) -> topic) edge.

        Each topic gets at most one Process whose inputs are the source database
        tables backing all of the topic's views (base + joined). The source-table
        qualifiedName is built from the user-supplied `atlan_source_connection_map`
        (Omni connection -> Atlan source-connection qualifiedName) plus each view's
        catalog/schema/table_name. When a view has no catalog (single-database
        connectors), the Omni connection's `database` is used as the catalog.

        The Process is skipped if:
        - no `atlan_source_connection_map` is configured
        - the topic's model has no connection, or its connection isn't in the map
        - none of the topic's views resolve to a complete table qualifiedName
        """
        if not self.atlan_source_connection_map:
            return []

        entities: list[dict[str, Any]] = []
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
                input_refs.append(self._rel_ref("Table", table_qn))

            if not input_refs:
                continue

            topic_qn = f"{self.tenant_id}/model/{model_id}/topic/{topic_name}"
            process_qn = (
                f"{self.tenant_id}/process/source/topic/{model_id}/{topic_name}"
            )
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
                        "outputs": [self._rel_ref("omni_topic", topic_qn)],
                    },
                }
            )
        return entities
