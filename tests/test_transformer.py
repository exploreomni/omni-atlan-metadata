"""Tests for app/transformer.py"""

import pytest

from app.transformer import OmniMetadataTransformer

WF_ID = "test-workflow"
RUN_ID = "test-run"

SNAPSHOT = {
    "connections": [
        {"id": "conn1", "name": "Snowflake", "dialect": "snowflake", "database": "analytics"},
    ],
    "models": [
        {"id": "mod1", "name": "Sales Model", "modelKind": "base", "connectionId": "conn1", "baseModelId": None, "updatedAt": "2024-01-01T00:00:00+00:00"},
        {"id": "mod2", "name": "Derived", "modelKind": "derived", "connectionId": "conn1", "baseModelId": "mod1", "updatedAt": None},
    ],
    "topics": [
        {"modelId": "mod1", "name": "orders", "label": "Orders", "baseViewName": "orders_view"},
        {"modelId": "mod1", "name": "customers", "label": None, "baseViewName": "customers_view"},
    ],
    "folders": [
        {"id": "fold1", "name": "Marketing", "path": "/Marketing", "scope": "shared", "owner": {"id": "u1", "name": "Alice"}},
        {"id": "fold2", "name": "Finance", "path": "/Finance", "scope": "personal", "owner": None},
    ],
    "documents": [
        {
            "identifier": "doc1",
            "name": "Revenue Dashboard",
            "hasDashboard": True,
            "scope": "shared",
            "url": "https://app.omni.co/doc1",
            "updatedAt": "2024-06-01T00:00:00+00:00",
            "type": "WORKBOOK",
            "connectionId": "conn1",
            "owner": {"id": "u2", "name": "Bob"},
            "folder": {"id": "fold1", "path": "/Marketing"},
        },
        {
            "identifier": "doc2",
            "name": "Data Workbook",
            "hasDashboard": False,
            "scope": "personal",
            "url": None,
            "updatedAt": None,
            "type": "WORKBOOK",
            "connectionId": None,
            "owner": None,
            "folder": None,
        },
    ],
}


def transform(tenant_id: str = "omni") -> list[dict]:
    t = OmniMetadataTransformer(tenant_id=tenant_id)
    return t.transform(SNAPSHOT, WF_ID, RUN_ID)


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def test_total_entity_count():
    entities = transform()
    assert len(entities) == 9  # 1 conn + 2 models + 2 topics + 2 folders + 1 dashboard + 1 workbook


def test_entity_type_counts():
    entities = transform()
    by_type = {}
    for e in entities:
        by_type[e["typeName"]] = by_type.get(e["typeName"], 0) + 1
    assert by_type["omni_connection"] == 1
    assert by_type["omni_model"] == 2
    assert by_type["omni_topic"] == 2
    assert by_type["omni_folder"] == 2
    assert by_type["omni_dashboard"] == 1
    assert by_type["omni_workbook"] == 1


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def test_connection_qualified_name():
    entities = transform()
    conn = next(e for e in entities if e["typeName"] == "omni_connection")
    assert conn["attributes"]["qualifiedName"] == "omni/connection/conn1"


def test_connection_attributes():
    entities = transform()
    conn = next(e for e in entities if e["typeName"] == "omni_connection")
    attrs = conn["attributes"]
    assert attrs["name"] == "Snowflake"
    assert attrs["dialect"] == "snowflake"
    assert attrs["database"] == "analytics"


def test_connection_no_relationship_attributes_key():
    # Connections have no outgoing cross-references so no relationship attributes expected.
    entities = transform()
    conn = next(e for e in entities if e["typeName"] == "omni_connection")
    assert "relationshipAttributes" not in conn


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_model_connection_ref_in_attributes():
    entities = transform()
    models = [e for e in entities if e["typeName"] == "omni_model"]
    base_model = next(m for m in models if m["attributes"]["omniId"] == "mod1")
    assert base_model["attributes"]["connectionQualifiedName"] == "omni/connection/conn1"
    assert base_model["attributes"]["baseModelQualifiedName"] is None


def test_derived_model_base_model_ref():
    entities = transform()
    models = [e for e in entities if e["typeName"] == "omni_model"]
    derived = next(m for m in models if m["attributes"]["omniId"] == "mod2")
    assert derived["attributes"]["baseModelQualifiedName"] == "omni/model/mod1"


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def test_topic_qualified_name():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    assert orders["attributes"]["qualifiedName"] == "omni/model/mod1/topic/orders"


def test_topic_uses_label_as_name():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    assert orders["attributes"]["name"] == "Orders"


def test_topic_falls_back_to_name_when_no_label():
    entities = transform()
    customers = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "customers")
    assert customers["attributes"]["name"] == "customers"


def test_topic_model_ref_in_attributes():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    assert orders["attributes"]["modelQualifiedName"] == "omni/model/mod1"


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

def test_folder_with_owner():
    entities = transform()
    mkt = next(e for e in entities if e["typeName"] == "omni_folder" and e["attributes"]["omniId"] == "fold1")
    assert mkt["attributes"]["ownerId"] == "u1"
    assert mkt["attributes"]["ownerName"] == "Alice"


def test_folder_null_owner():
    entities = transform()
    fin = next(e for e in entities if e["typeName"] == "omni_folder" and e["attributes"]["omniId"] == "fold2")
    assert fin["attributes"]["ownerId"] is None
    assert fin["attributes"]["ownerName"] is None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_dashboard_type():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc1")
    assert doc["typeName"] == "omni_dashboard"


def test_workbook_type():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc2")
    assert doc["typeName"] == "omni_workbook"


def test_dashboard_connection_ref():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc1")
    assert doc["attributes"]["connectionQualifiedName"] == "omni/connection/conn1"
    assert doc["attributes"]["folderQualifiedName"] == "omni/folder/fold1"


def test_workbook_null_refs():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc2")
    assert doc["attributes"]["connectionQualifiedName"] is None
    assert doc["attributes"]["folderQualifiedName"] is None


# ---------------------------------------------------------------------------
# Relationship attributes
# ---------------------------------------------------------------------------

def test_model_connection_relationship_attr():
    entities = transform()
    models = [e for e in entities if e["typeName"] == "omni_model"]
    base_model = next(m for m in models if m["attributes"]["omniId"] == "mod1")
    rel = base_model["relationshipAttributes"]["connectionQualifiedName"]
    assert rel["typeName"] == "omni_connection"
    assert rel["uniqueAttributes"]["qualifiedName"] == "omni/connection/conn1"


def test_model_without_connection_has_no_relationship_attributes():
    t = OmniMetadataTransformer(tenant_id="omni")
    result = t.transform(
        {"connections": [], "models": [{"id": "m1", "name": "M", "modelKind": "base", "connectionId": None, "baseModelId": None}],
         "topics": [], "folders": [], "documents": [], "document_model_ids": set()},
        WF_ID, RUN_ID,
    )
    model = next(e for e in result if e["typeName"] == "omni_model")
    assert "relationshipAttributes" not in model


def test_derived_model_base_model_relationship_attr():
    entities = transform()
    models = [e for e in entities if e["typeName"] == "omni_model"]
    derived = next(m for m in models if m["attributes"]["omniId"] == "mod2")
    rel = derived["relationshipAttributes"]["baseModelQualifiedName"]
    assert rel["typeName"] == "omni_model"
    assert rel["uniqueAttributes"]["qualifiedName"] == "omni/model/mod1"


def test_topic_model_relationship_attr():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    rel = orders["relationshipAttributes"]["modelQualifiedName"]
    assert rel["typeName"] == "omni_model"
    assert rel["uniqueAttributes"]["qualifiedName"] == "omni/model/mod1"


def test_dashboard_relationship_attrs():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc1")
    rel_attrs = doc["relationshipAttributes"]
    assert rel_attrs["connectionQualifiedName"]["typeName"] == "omni_connection"
    assert rel_attrs["connectionQualifiedName"]["uniqueAttributes"]["qualifiedName"] == "omni/connection/conn1"
    assert rel_attrs["folderQualifiedName"]["typeName"] == "omni_folder"
    assert rel_attrs["folderQualifiedName"]["uniqueAttributes"]["qualifiedName"] == "omni/folder/fold1"


def test_workbook_no_refs_has_no_relationship_attributes():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc2")
    assert "relationshipAttributes" not in doc


# ---------------------------------------------------------------------------
# Sync attributes
# ---------------------------------------------------------------------------

def test_sync_attributes_present_on_all_entities():
    entities = transform()
    for e in entities:
        attrs = e["attributes"]
        assert attrs["connector_name"] == "omni", f"Missing connector_name on {e['typeName']}"
        assert attrs["last_sync_workflow_name"] == WF_ID
        assert attrs["last_sync_run"] == RUN_ID


# ---------------------------------------------------------------------------
# Custom tenant_id
# ---------------------------------------------------------------------------

def test_custom_tenant_id():
    t = OmniMetadataTransformer(tenant_id="acme")
    entities = t.transform(SNAPSHOT, WF_ID, RUN_ID)
    conn = next(e for e in entities if e["typeName"] == "omni_connection")
    assert conn["attributes"]["qualifiedName"].startswith("acme/")


# ---------------------------------------------------------------------------
# Missing required fields → entity skipped
# ---------------------------------------------------------------------------

def test_connection_without_id_skipped():
    t = OmniMetadataTransformer(tenant_id="omni")
    result = t.transform({"connections": [{"name": "no-id"}], "models": [], "topics": [], "folders": [], "documents": []}, WF_ID, RUN_ID)
    assert not any(e["typeName"] == "omni_connection" for e in result)


def test_document_without_identifier_skipped():
    t = OmniMetadataTransformer(tenant_id="omni")
    result = t.transform({"connections": [], "models": [], "topics": [], "folders": [], "documents": [{"name": "no-id"}]}, WF_ID, RUN_ID)
    assert not any(e["typeName"] in ("omni_dashboard", "omni_workbook") for e in result)
