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
        {
            "modelId": "mod1",
            "name": "orders",
            "label": "Orders",
            "baseViewName": "orders_view",
            "sourceTableName": "orders",
            "sourceSchema": "public",
            "sourceCatalog": "analytics",
            "joinedViewNames": ["customers_view", "products_view"],
            "dimensionNames": ["orders_view.id", "orders_view.created_at"],
            "measureNames": ["orders_view.total_revenue", "orders_view.count"],
            "viewSources": [
                {"viewName": "orders_view", "tableName": "orders", "schema": "public", "catalog": "analytics"},
                {"viewName": "customers_view", "tableName": "customers", "schema": "public", "catalog": "analytics"},
                {"viewName": "products_view", "tableName": "products", "schema": "public", "catalog": None},  # falls back to conn.database
            ],
        },
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
            "tileTopics": [
                {"modelId": "mod1", "topicName": "orders"},
                {"modelId": "mod1", "topicName": "customers"},
                {"modelId": "mod1", "topicName": "orders"},  # duplicate — should be deduped
            ],
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
            "tileTopics": [],
        },
    ],
}


def transform(
    tenant_id: str = "omni",
    atlan_source_connection_map: dict[str, str] | None = None,
) -> list[dict]:
    t = OmniMetadataTransformer(
        tenant_id=tenant_id,
        atlan_source_connection_map=atlan_source_connection_map,
    )
    return t.transform(SNAPSHOT, WF_ID, RUN_ID)


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def test_total_entity_count():
    entities = transform()
    # 1 conn + 2 models + 2 topics + 2 folders + 1 dashboard + 1 workbook
    # + 2 Process entities (doc1's two unique tile topics)
    assert len(entities) == 11


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
    assert by_type["Process"] == 2


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


def test_topic_source_table_attrs():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    attrs = orders["attributes"]
    assert attrs["sourceTableName"] == "orders"
    assert attrs["sourceSchema"] == "public"
    assert attrs["sourceCatalog"] == "analytics"


def test_topic_joined_views_and_fields():
    entities = transform()
    orders = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "orders")
    attrs = orders["attributes"]
    assert attrs["joinedViewNames"] == ["customers_view", "products_view"]
    assert attrs["dimensionNames"] == ["orders_view.id", "orders_view.created_at"]
    assert attrs["measureNames"] == ["orders_view.total_revenue", "orders_view.count"]


def test_topic_without_enrichment_has_null_source_fields():
    entities = transform()
    customers = next(e for e in entities if e["typeName"] == "omni_topic" and e["attributes"]["omniName"] == "customers")
    attrs = customers["attributes"]
    assert attrs["sourceTableName"] is None
    assert attrs["sourceSchema"] is None
    assert attrs["sourceCatalog"] is None
    assert attrs["joinedViewNames"] is None
    assert attrs["dimensionNames"] is None
    assert attrs["measureNames"] is None


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


def test_dashboard_topic_qualified_names_deduped():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc1")
    qns = doc["attributes"]["topicQualifiedNames"]
    assert sorted(qns) == [
        "omni/model/mod1/topic/customers",
        "omni/model/mod1/topic/orders",
    ]


def test_workbook_no_tile_topics_is_none():
    entities = transform()
    doc = next(e for e in entities if e.get("attributes", {}).get("omniId") == "doc2")
    assert doc["attributes"]["topicQualifiedNames"] is None


# ---------------------------------------------------------------------------
# Topic -> Dashboard lineage processes
# ---------------------------------------------------------------------------

def test_process_emitted_per_unique_topic_dashboard_pair():
    entities = transform()
    processes = [e for e in entities if e["typeName"] == "Process"]
    assert len(processes) == 2
    qns = {p["attributes"]["qualifiedName"] for p in processes}
    assert qns == {
        "omni/process/topic/mod1/orders/document/doc1",
        "omni/process/topic/mod1/customers/document/doc1",
    }


def test_process_inputs_and_outputs():
    entities = transform()
    process = next(
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"]
        == "omni/process/topic/mod1/orders/document/doc1"
    )
    rel = process["relationshipAttributes"]
    assert rel["inputs"] == [
        {
            "typeName": "omni_topic",
            "uniqueAttributes": {"qualifiedName": "omni/model/mod1/topic/orders"},
        }
    ]
    assert rel["outputs"] == [
        {
            "typeName": "omni_dashboard",
            "uniqueAttributes": {"qualifiedName": "omni/document/doc1"},
        }
    ]


def test_process_has_omni_connector_name_and_human_name():
    entities = transform()
    process = next(
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"]
        == "omni/process/topic/mod1/orders/document/doc1"
    )
    assert process["attributes"]["connectorName"] == "omni"
    assert process["attributes"]["name"] == "orders -> Revenue Dashboard"


def test_workbook_with_no_tile_topics_emits_no_process():
    entities = transform()
    processes = [
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["relationshipAttributes"]["outputs"][0]["uniqueAttributes"][
            "qualifiedName"
        ]
        == "omni/document/doc2"
    ]
    assert processes == []


def test_workbook_process_uses_workbook_output_type():
    """If a workbook (not dashboard) had tile topics, its Process outputs would
    reference omni_workbook, not omni_dashboard."""
    snapshot = dict(SNAPSHOT)
    snapshot["documents"] = [
        {
            "identifier": "wb1",
            "name": "Some Workbook",
            "hasDashboard": False,
            "tileTopics": [{"modelId": "mod1", "topicName": "orders"}],
        }
    ]
    t = OmniMetadataTransformer(tenant_id="omni")
    result = t.transform(snapshot, WF_ID, RUN_ID)
    process = next(e for e in result if e["typeName"] == "Process")
    assert (
        process["relationshipAttributes"]["outputs"][0]["typeName"] == "omni_workbook"
    )


# ---------------------------------------------------------------------------
# Sync attributes
# ---------------------------------------------------------------------------

def test_sync_attributes_present_on_all_omni_entities():
    """Sync attrs are registered on our custom typedefs only — not on built-in Process."""
    entities = transform()
    for e in entities:
        if e["typeName"] == "Process":
            continue
        attrs = e["attributes"]
        assert attrs["connector_name"] == "omni", f"Missing connector_name on {e['typeName']}"
        assert attrs["last_sync_workflow_name"] == WF_ID
        assert attrs["last_sync_run"] == RUN_ID


def test_process_entities_have_no_custom_sync_attrs():
    """Process is Atlan's built-in supertype; emitting unregistered attrs risks rejection."""
    entities = transform()
    for e in entities:
        if e["typeName"] != "Process":
            continue
        attrs = e["attributes"]
        assert "connector_name" not in attrs  # snake_case (custom) — should NOT be present
        assert "last_sync_run" not in attrs
        assert "last_sync_workflow_name" not in attrs
        assert attrs["connectorName"] == "omni"  # camelCase (standard Atlas) — IS present


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


# ---------------------------------------------------------------------------
# Source Table -> Topic lineage processes
# ---------------------------------------------------------------------------

SOURCE_MAP = {"conn1": "default/snowflake/1700000000"}


def test_no_source_processes_when_map_missing():
    entities = transform()  # no map configured
    assert not any(
        e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"].startswith("omni/process/source/")
        for e in entities
    )


def test_source_to_topic_process_emitted():
    entities = transform(atlan_source_connection_map=SOURCE_MAP)
    sources = [
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"].startswith("omni/process/source/")
    ]
    assert len(sources) == 1
    process = sources[0]
    assert (
        process["attributes"]["qualifiedName"]
        == "omni/process/source/topic/mod1/orders"
    )
    assert process["attributes"]["name"] == "sources -> Orders"
    assert process["attributes"]["connectorName"] == "omni"


def test_source_process_inputs_use_atlan_qn_format():
    entities = transform(atlan_source_connection_map=SOURCE_MAP)
    process = next(
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"] == "omni/process/source/topic/mod1/orders"
    )
    inputs = process["relationshipAttributes"]["inputs"]
    assert all(i["typeName"] == "Table" for i in inputs)
    qns = {i["uniqueAttributes"]["qualifiedName"] for i in inputs}
    assert qns == {
        "default/snowflake/1700000000/analytics/public/orders",
        "default/snowflake/1700000000/analytics/public/customers",
        # products_view has catalog=None, falls back to conn1.database = "analytics"
        "default/snowflake/1700000000/analytics/public/products",
    }


def test_source_process_output_is_topic():
    entities = transform(atlan_source_connection_map=SOURCE_MAP)
    process = next(
        e
        for e in entities
        if e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"] == "omni/process/source/topic/mod1/orders"
    )
    outputs = process["relationshipAttributes"]["outputs"]
    assert outputs == [
        {
            "typeName": "omni_topic",
            "uniqueAttributes": {"qualifiedName": "omni/model/mod1/topic/orders"},
        }
    ]


def test_source_process_skipped_when_connection_not_in_map():
    # Map points to a different Omni connection, so 'orders' topic gets no source process.
    entities = transform(atlan_source_connection_map={"some-other-conn": "default/redshift/x"})
    assert not any(
        e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"].startswith("omni/process/source/")
        for e in entities
    )


def test_source_process_skipped_when_topic_has_no_view_sources():
    # 'customers' topic has no viewSources in the SNAPSHOT.
    entities = transform(atlan_source_connection_map=SOURCE_MAP)
    assert not any(
        e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"]
        == "omni/process/source/topic/mod1/customers"
        for e in entities
    )


def test_source_process_skipped_when_view_missing_schema_or_catalog():
    """A view with no schema and no fallback catalog produces no input ref."""
    snapshot = {
        "connections": [{"id": "c1", "name": "C", "database": None}],
        "models": [{"id": "m1", "name": "M", "modelKind": "base", "connectionId": "c1"}],
        "topics": [
            {
                "modelId": "m1",
                "name": "t1",
                "label": "T1",
                "baseViewName": "v1",
                "viewSources": [{"viewName": "v1", "tableName": "t", "schema": None, "catalog": None}],
            }
        ],
        "folders": [],
        "documents": [],
    }
    t = OmniMetadataTransformer(
        tenant_id="omni",
        atlan_source_connection_map={"c1": "default/postgres/1"},
    )
    result = t.transform(snapshot, WF_ID, RUN_ID)
    assert not any(
        e["typeName"] == "Process"
        and e["attributes"]["qualifiedName"].startswith("omni/process/source/")
        for e in result
    )
