from __future__ import annotations

from typing import Any


class OmniMetadataTransformer:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id or "omni"

    def transform(
        self,
        snapshot: dict[str, Any],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        entities.extend(self._connections(snapshot.get("connections", []), workflow_id, workflow_run_id))
        entities.extend(self._models(snapshot.get("models", []), workflow_id, workflow_run_id))
        entities.extend(self._topics(snapshot.get("topics", []), workflow_id, workflow_run_id))
        entities.extend(self._folders(snapshot.get("folders", []), workflow_id, workflow_run_id))
        entities.extend(self._documents(snapshot.get("documents", []), workflow_id, workflow_run_id))
        return entities

    def _base_custom_attributes(self, workflow_id: str, workflow_run_id: str) -> dict[str, str]:
        return {
            "last_sync_workflow_name": workflow_id,
            "last_sync_run": workflow_run_id,
            "connector_name": "omni",
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
                    },
                    "customAttributes": self._base_custom_attributes(workflow_id, workflow_run_id),
                }
            )
        return entities

    def _models(
        self,
        records: list[dict[str, Any]],
        workflow_id: str,
        workflow_run_id: str,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for row in records:
            model_id = row.get("id")
            if not model_id:
                continue
            conn_id = row.get("connectionId")
            base_model_id = row.get("baseModelId")
            entities.append(
                {
                    "typeName": "omni_model",
                    "attributes": {
                        "qualifiedName": f"{self.tenant_id}/model/{model_id}",
                        "name": row.get("name") or model_id,
                        "omniId": model_id,
                        "modelKind": row.get("modelKind"),
                        "updatedAt": row.get("updatedAt"),
                    },
                    "relationshipAttributes": {
                        "connectionQualifiedName": (
                            f"{self.tenant_id}/connection/{conn_id}" if conn_id else None
                        ),
                        "baseModelQualifiedName": (
                            f"{self.tenant_id}/model/{base_model_id}" if base_model_id else None
                        ),
                    },
                    "customAttributes": self._base_custom_attributes(workflow_id, workflow_run_id),
                }
            )
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
                    },
                    "relationshipAttributes": {
                        "modelQualifiedName": f"{self.tenant_id}/model/{model_id}",
                    },
                    "customAttributes": self._base_custom_attributes(workflow_id, workflow_run_id),
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
                    },
                    "customAttributes": self._base_custom_attributes(workflow_id, workflow_run_id),
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
            entities.append(
                {
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
                    },
                    "relationshipAttributes": {
                        "connectionQualifiedName": (
                            f"{self.tenant_id}/connection/{row.get('connectionId')}"
                            if row.get("connectionId")
                            else None
                        ),
                        "folderQualifiedName": (
                            f"{self.tenant_id}/folder/{folder.get('id')}" if folder.get("id") else None
                        ),
                    },
                    "customAttributes": self._base_custom_attributes(workflow_id, workflow_run_id),
                }
            )
        return entities
