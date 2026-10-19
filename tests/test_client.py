"""Tests for app/client.py"""

import pytest
import respx
import httpx

from app.client import ClientClass, OmniApiError, NonRetryableOmniApiError


CREDS = {
    "omni_base_url": "https://test.omniapp.co/api",
    "omni_api_token": "tok-test",
}


def make_client() -> ClientClass:
    # rpm=0 disables the rate limiter so tests don't pay the 1s/request floor.
    return ClientClass(credentials=CREDS, rpm=0)


# ---------------------------------------------------------------------------
# load_credentials
# ---------------------------------------------------------------------------

def test_load_credentials_requires_base_url():
    with pytest.raises(ValueError, match="omni_base_url"):
        ClientClass(credentials={"omni_api_token": "tok"})


def test_load_credentials_requires_token():
    with pytest.raises(ValueError, match="omni_api_token"):
        ClientClass(credentials={"omni_base_url": "https://x.com/api"})


def test_load_credentials_requires_protocol():
    with pytest.raises(ValueError, match="protocol"):
        ClientClass(credentials={"omni_base_url": "x.com/api", "omni_api_token": "t"})


def test_rate_limiter_is_shared_across_clients_for_same_host():
    """Item 3: throttling is a property of the Omni host, not the run. Two
    concurrent activities against the same tenant must share one gate — five
    per-run 60 rpm limiters is 300 rpm at Omni's door."""
    creds = {"omni_base_url": "https://a.omniapp.co/api", "omni_api_token": "t"}
    a = ClientClass(credentials=creds, rpm=0)
    b = ClientClass(credentials=creds, rpm=0)
    assert a._rate_limiter is b._rate_limiter


def test_swallow_populates_failure_counters():
    """Item 5: silently-swallowed errors must land in the per-run counters."""
    client = ClientClass(credentials=CREDS, rpm=0)
    assert client._failures["model_yaml"] == 0
    client._swallow("model_yaml", "model_id=m1", RuntimeError("boom"))
    client._swallow("model_yaml", "model_id=m2", RuntimeError("boom"))
    client._swallow("topic_detail", "model_id=m1 topic=orders", RuntimeError("x"))
    assert client._failures["model_yaml"] == 2
    assert client._failures["topic_detail"] == 1
    assert client._failures["override_probe"] == 0


@respx.mock
def test_fetch_snapshot_aborts_when_model_yaml_failure_rate_exceeds_threshold():
    """Item 5 threshold: if >20% of model-YAML calls fail, abort before the
    transform pass rather than publish a partial crawl. The check runs at end
    of model pass (~1 min in), not end of fetch_snapshot — with
    maximum_attempts=1 a late abort costs a full three-hour re-crawl."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [{"id": f"m{i}", "modelKind": "SHARED"} for i in range(5)],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    # 3 of 5 models 500 -> 60% failure rate, well above the 20% floor.
    for i in range(3):
        respx.get(
            f"https://test.omniapp.co/api/v1/models/m{i}/yaml", params={"mode": "combined"}
        ).mock(return_value=httpx.Response(500, text="boom"))
    for i in range(3, 5):
        respx.get(
            f"https://test.omniapp.co/api/v1/models/m{i}/yaml", params={"mode": "combined"}
        ).mock(return_value=httpx.Response(200, json={"files": {}}))

    with pytest.raises(OmniApiError, match="model-YAML fetch failed"):
        make_client().fetch_snapshot(crawl_only_content_backed_workbooks=False)


def test_rate_limiter_is_distinct_across_hosts():
    """Different tenants share a pod but not a rate quota."""
    a = ClientClass(
        credentials={"omni_base_url": "https://a.omniapp.co/api", "omni_api_token": "t"},
        rpm=0,
    )
    b = ClientClass(
        credentials={"omni_base_url": "https://b.omniapp.co/api", "omni_api_token": "t"},
        rpm=0,
    )
    assert a._rate_limiter is not b._rate_limiter


def test_load_credentials_accepts_wire_shape():
    # Atlan UI → Heracles sends {"host": ..., "password": ..., "authType": "apikey"}.
    # ClientClass must accept these as aliases for omni_base_url / omni_api_token.
    client = ClientClass(
        credentials={
            "host": "https://test.omniapp.co/api",
            "password": "tok-wire",
            "authType": "apikey",
        },
        rpm=0,
    )
    assert client._credentials is not None
    assert client._credentials.base_url == "https://test.omniapp.co/api"
    assert client._credentials.api_token == "tok-wire"


def test_load_credentials_wire_shape_protocol_check():
    with pytest.raises(ValueError, match="protocol"):
        ClientClass(credentials={"host": "x.com/api", "password": "t"})


# ---------------------------------------------------------------------------
# list_connections
# ---------------------------------------------------------------------------

@respx.mock
def test_list_connections_returns_list():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": [{"id": "c1", "name": "Conn1"}]})
    )
    client = make_client()
    result = client.list_connections()
    assert result == [{"id": "c1", "name": "Conn1"}]


@respx.mock
def test_list_connections_empty():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    result = make_client().list_connections()
    assert result == []


@respx.mock
def test_list_connections_401_raises_non_retryable():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    with pytest.raises(NonRetryableOmniApiError):
        make_client().list_connections()


@respx.mock
def test_list_connections_500_raises_retryable():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    with pytest.raises(OmniApiError) as exc_info:
        make_client().list_connections()
    assert exc_info.value.retryable


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

@respx.mock
def test_collect_paginated_follows_cursor():
    page1 = {
        "records": [{"id": "m1"}],
        "pageInfo": {"hasNextPage": True, "nextCursor": "cur2"},
    }
    page2 = {
        "records": [{"id": "m2"}],
        "pageInfo": {"hasNextPage": False, "nextCursor": None},
    }
    route = respx.get("https://test.omniapp.co/api/v1/models")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]
    client = make_client()
    result = client._collect_paginated(client.list_models, page_size=1, max_pages=None)
    assert [r["id"] for r in result] == ["m1", "m2"]


@respx.mock
def test_collect_paginated_respects_max_pages():
    page = {
        "records": [{"id": "m1"}],
        "pageInfo": {"hasNextPage": True, "nextCursor": "cur2"},
    }
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json=page)
    )
    client = make_client()
    result = client._collect_paginated(client.list_models, page_size=1, max_pages=1)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# rate limit retry
# ---------------------------------------------------------------------------

@respx.mock
def test_rate_limit_retries_then_succeeds():
    route = respx.get("https://test.omniapp.co/api/v1/connections")
    route.side_effect = [
        httpx.Response(429, text="Rate limited"),
        httpx.Response(200, json={"connections": [{"id": "c1"}]}),
    ]
    client = make_client()
    result = client.list_connections()
    assert result[0]["id"] == "c1"


# ---------------------------------------------------------------------------
# fetch_snapshot topic parsing
# ---------------------------------------------------------------------------

@respx.mock
def test_fetch_snapshot_parses_topics():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"id": "mod1"}],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml_content = "name: orders\nlabel: Orders\nbase_view_name: orders_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_content}})
    )
    # Topic detail returns 404 — basic YAML data still flows through.
    respx.get("https://test.omniapp.co/api/v1/models/mod1/topic/orders").mock(
        return_value=httpx.Response(404, text="Not found")
    )

    snapshot = make_client().fetch_snapshot()
    assert snapshot["topics"] == [
        {
            "modelId": "mod1",
            "owningModelId": "mod1",
            "name": "orders",
            "label": "Orders",
            "baseViewName": "orders_view",
        }
    ]


@respx.mock
def test_fetch_snapshot_fetches_yaml_for_multiple_models_concurrently():
    """All model YAML calls are made regardless of ordering — concurrent fetch."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"id": "mod1"}, {"id": "mod2"}],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml1 = "label: Orders\nbase_view_name: orders_view\n"
    yaml2 = "label: Customers\nbase_view_name: customers_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml1}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod2/yaml").mock(
        return_value=httpx.Response(200, json={"files": {"customers.topic": yaml2}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod2/topic/customers").mock(
        return_value=httpx.Response(404)
    )

    snapshot = make_client().fetch_snapshot()
    topic_model_ids = {t["modelId"] for t in snapshot["topics"]}
    assert topic_model_ids == {"mod1", "mod2"}
    assert len(snapshot["topics"]) == 2


@respx.mock
def test_fetch_snapshot_yaml_failure_skips_model_but_continues():
    """A failed YAML call for a SMALL fraction of models does not abort the
    batch. 1 of 6 fails = ~17%, safely under the 20% abort threshold; the
    other 5 topics still land."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"id": f"mod{i}"} for i in range(1, 7)],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    # mod1 fails; the other five succeed with one topic apiece.
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    for i in range(2, 7):
        yaml_body = f"label: t{i}\nbase_view_name: t{i}_view\n"
        respx.get(f"https://test.omniapp.co/api/v1/models/mod{i}/yaml").mock(
            return_value=httpx.Response(200, json={"files": {f"t{i}.topic": yaml_body}})
        )
        respx.get(f"https://test.omniapp.co/api/v1/models/mod{i}/topic/t{i}").mock(
            return_value=httpx.Response(404)
        )

    snapshot = make_client().fetch_snapshot()
    assert len(snapshot["topics"]) == 5
    assert {t["modelId"] for t in snapshot["topics"]} == {"mod2", "mod3", "mod4", "mod5", "mod6"}


@respx.mock
def test_fetch_snapshot_resolves_document_model_ids_concurrently():
    """Document detail calls are made for all documents and model IDs collected."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"identifier": "doc1"}, {"identifier": "doc2"}],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc1").mock(
        return_value=httpx.Response(200, json={"modelId": "mod1"})
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc2").mock(
        return_value=httpx.Response(200, json={"modelId": "mod2"})
    )

    snapshot = make_client().fetch_snapshot()
    assert sorted(snapshot["document_model_ids"]) == ["mod1", "mod2"]


@respx.mock
def test_fetch_snapshot_document_detail_failure_skips_but_continues():
    """A failed document detail call does not abort the rest of the batch."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"identifier": "doc1"}, {"identifier": "doc2"}],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc1").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc2").mock(
        return_value=httpx.Response(200, json={"modelId": "mod2"})
    )

    snapshot = make_client().fetch_snapshot()
    assert snapshot["document_model_ids"] == ["mod2"]


@respx.mock
def test_fetch_snapshot_enriches_document_with_tile_topics():
    """Document records are enriched with deduplicated tile topics from queryPresentations."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [{"identifier": "doc1"}],
                "pageInfo": {"hasNextPage": False},
            },
        )
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc1").mock(
        return_value=httpx.Response(
            200,
            json={
                "modelId": "mod1",
                "queryPresentations": [
                    {"topicName": "orders", "query": {"modelId": "mod1"}},
                    {"topicName": "customers", "query": {"modelId": "mod1"}},
                    {"topicName": "orders", "query": {"modelId": "mod1"}},  # duplicate
                    {"topicName": None},  # missing topic — skipped
                ],
            },
        )
    )

    snapshot = make_client().fetch_snapshot()
    doc = snapshot["documents"][0]
    tile_topics = doc["tileTopics"]
    assert len(tile_topics) == 2  # duplicate and null deduped/skipped
    assert {"modelId": "mod1", "topicName": "orders"} in tile_topics
    assert {"modelId": "mod1", "topicName": "customers"} in tile_topics


@respx.mock
def test_fetch_snapshot_falls_back_to_doc_model_id_when_query_missing_model():
    """When a presentation has no inner query.modelId, fall back to the document's modelId."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"identifier": "doc1"}], "pageInfo": {"hasNextPage": False}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/documents/doc1").mock(
        return_value=httpx.Response(
            200,
            json={
                "modelId": "modX",
                "queryPresentations": [{"topicName": "orders"}],
            },
        )
    )

    snapshot = make_client().fetch_snapshot()
    doc = snapshot["documents"][0]
    assert doc["tileTopics"] == [{"modelId": "modX", "topicName": "orders"}]


@respx.mock
def test_fetch_snapshot_enriches_topic_with_source_table_and_fields():
    """Topic API enrichment populates source table, joined views, dimensions, and measures."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"id": "mod1"}], "pageInfo": {"hasNextPage": False}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(
            200,
            json={"files": {"orders.topic": "label: Orders\nbase_view_name: orders_view\n"}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/topic/orders").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "topic": {
                    "name": "orders",
                    "label": "Orders",
                    "base_view_name": "orders_view",
                    "views": [
                        {
                            "name": "orders_view",
                            "table_name": "orders",
                            "schema": "public",
                            "catalog": "analytics",
                            "dimensions": [
                                {"fully_qualified_name": "orders_view.id"},
                                {"fully_qualified_name": "orders_view.created_at"},
                            ],
                            "measures": [
                                {"fully_qualified_name": "orders_view.total_revenue"},
                            ],
                        },
                        {
                            "name": "customers_view",
                            "table_name": "customers",
                            "schema": "public",
                            "dimensions": [
                                {"fully_qualified_name": "customers_view.email"},
                            ],
                            "measures": [],
                        },
                    ],
                },
            },
        )
    )

    snapshot = make_client().fetch_snapshot()
    assert len(snapshot["topics"]) == 1
    topic = snapshot["topics"][0]
    assert topic["sourceTableName"] == "orders"
    assert topic["sourceSchema"] == "public"
    assert topic["sourceCatalog"] == "analytics"
    assert topic["joinedViewNames"] == ["customers_view"]
    assert topic["dimensionNames"] == [
        "orders_view.id",
        "orders_view.created_at",
        "customers_view.email",
    ]
    assert topic["measureNames"] == ["orders_view.total_revenue"]
    # viewSources collects every view that has a table_name (catalog optional).
    assert topic["viewSources"] == [
        {"viewName": "orders_view", "tableName": "orders", "schema": "public", "catalog": "analytics"},
        {"viewName": "customers_view", "tableName": "customers", "schema": "public", "catalog": None},
    ]


@respx.mock
def test_fetch_snapshot_topic_detail_failure_falls_back_to_yaml():
    """If the topic detail API fails, the topic is still emitted with YAML-derived basics."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"id": "mod1"}], "pageInfo": {"hasNextPage": False}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(
            200,
            json={"files": {"orders.topic": "label: Orders\nbase_view_name: orders_view\n"}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/topic/orders").mock(
        return_value=httpx.Response(500, text="Server Error")
    )

    snapshot = make_client().fetch_snapshot()
    assert len(snapshot["topics"]) == 1
    topic = snapshot["topics"][0]
    assert topic["name"] == "orders"
    assert topic["label"] == "Orders"
    assert topic["baseViewName"] == "orders_view"
    # Detail-only fields are absent when the topic API fails.
    assert "sourceTableName" not in topic


# ---------------------------------------------------------------------------
# Workbook topic canonicalization (owningModelId stamping)
# ---------------------------------------------------------------------------

@respx.mock
def test_workbook_inherited_topic_owning_is_shared_model():
    """A workbook whose mode=extension YAML doesn't list a topic file is treated
    as inheriting it — owningModelId points to the base shared model."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"id": "shared1", "modelKind": "SHARED"},
                {"id": "wb1", "name": "Workbook 1", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml_body = "label: Orders\nbase_view_name: orders_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/shared1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    # Workbook's own extension layer is empty => topic is inherited, not overridden.
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "extension"}).mock(
        return_value=httpx.Response(200, json={"files": {}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/topic/orders").mock(
        return_value=httpx.Response(404)
    )

    snapshot = make_client().fetch_snapshot(crawl_only_content_backed_workbooks=False)
    topics_by_model = {t["modelId"]: t for t in snapshot["topics"]}
    assert topics_by_model["shared1"]["owningModelId"] == "shared1"
    assert topics_by_model["wb1"]["owningModelId"] == "shared1"


@respx.mock
def test_workbook_overridden_topic_owning_is_workbook():
    """A workbook whose extension YAML lists the topic file IS overriding it —
    owningModelId stays the workbook so it gets its own canonical entity."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"id": "shared1", "modelKind": "SHARED"},
                {"id": "wb1", "name": "Workbook 1", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml_body = "label: Orders\nbase_view_name: orders_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/shared1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    # Refinement-prefix form (+orders.topic) — should normalize to `orders`.
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "extension"}).mock(
        return_value=httpx.Response(200, json={"files": {"+orders.topic": yaml_body}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/topic/orders").mock(
        return_value=httpx.Response(404)
    )

    snapshot = make_client().fetch_snapshot(crawl_only_content_backed_workbooks=False)
    topics_by_model = {t["modelId"]: t for t in snapshot["topics"]}
    assert topics_by_model["shared1"]["owningModelId"] == "shared1"
    assert topics_by_model["wb1"]["owningModelId"] == "wb1"


@respx.mock
def test_workbook_extension_fetch_failure_collapses_to_shared_owner():
    """Item 4c inversion: a failed extension probe means we don't know which
    topics were overridden. Default to INHERITED (collapse to SHARED ancestor)
    rather than KEPT (workbook as owner). The old default failed toward
    duplication, which was the 170x bug."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"id": "shared1", "modelKind": "SHARED"},
                {"id": "wb1", "name": "Workbook 1", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml_body = "label: Orders\nbase_view_name: orders_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/shared1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "combined"}).mock(
        return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/yaml", params={"mode": "extension"}).mock(
        return_value=httpx.Response(500, text="boom")
    )
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://test.omniapp.co/api/v1/models/wb1/topic/orders").mock(
        return_value=httpx.Response(404)
    )

    snapshot = make_client().fetch_snapshot(crawl_only_content_backed_workbooks=False)
    topics_by_model = {t["modelId"]: t for t in snapshot["topics"]}
    # Both topic rows collapse to the SHARED ancestor's model id.
    assert topics_by_model["wb1"]["owningModelId"] == "shared1"


@respx.mock
def test_workbook_chain_climbs_past_shared_extension_to_shared():
    """Item 4b multi-hop walk: WORKBOOK -> SHARED_EXTENSION -> SHARED. The
    single-hop v0.3.0 walk would have stopped at SHARED_EXTENSION, which is
    not a representable OmniV01 model kind and would have dangled on publish."""
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"id": "shared1", "modelKind": "SHARED"},
                {"id": "ext1", "modelKind": "SHARED_EXTENSION", "baseModelId": "shared1"},
                {"id": "wb1", "name": "WB", "modelKind": "WORKBOOK", "baseModelId": "ext1"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    yaml_body = "label: Orders\nbase_view_name: orders_view\n"
    for model_id in ("shared1", "ext1", "wb1"):
        respx.get(
            f"https://test.omniapp.co/api/v1/models/{model_id}/yaml",
            params={"mode": "combined"},
        ).mock(
            return_value=httpx.Response(200, json={"files": {"orders.topic": yaml_body}})
        )
        respx.get(
            f"https://test.omniapp.co/api/v1/models/{model_id}/topic/orders",
        ).mock(return_value=httpx.Response(404))
    for wb_model in ("ext1", "wb1"):
        respx.get(
            f"https://test.omniapp.co/api/v1/models/{wb_model}/yaml",
            params={"mode": "extension"},
        ).mock(return_value=httpx.Response(200, json={"files": {}}))

    snapshot = make_client().fetch_snapshot(crawl_only_content_backed_workbooks=False)
    topics_by_model = {t["modelId"]: t for t in snapshot["topics"]}
    # The workbook's topic climbs past the SHARED_EXTENSION straight to SHARED.
    assert topics_by_model["wb1"]["owningModelId"] == "shared1"


@respx.mock
def test_fetch_snapshot_skips_non_topic_files():
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"records": [{"id": "mod1"}], "pageInfo": {"hasNextPage": False}},
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={"records": [], "pageInfo": {"hasNextPage": False}})
    )
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(200, json={"files": {"schema.sql": "SELECT 1"}})
    )

    snapshot = make_client().fetch_snapshot()
    assert snapshot["topics"] == []


# ---------------------------------------------------------------------------
# topic-detail memoization
#
# A live run against a large org issued 25,831 topic-detail requests that
# resolved to 93 distinct topics: every workbook inheriting a shared topic
# re-fetched it. These are invariants on the request COUNT, not on any one
# call site, so they stay meaningful if the fetch path is refactored.
# ---------------------------------------------------------------------------

def test_topic_detail_is_fetched_once_per_owning_model_and_topic():
    """N workbooks inheriting one shared topic cost ONE topic-detail request."""
    client = make_client()
    calls: list[tuple[str, str]] = []

    def _record(model_id: str, topic_name: str) -> dict:
        calls.append((model_id, topic_name))
        return {"sourceTableName": "orders"}

    client._fetch_topic_detail = _record  # type: ignore[assignment]

    for _ in range(50):
        detail = client._fetch_topic_detail_cached("shared-model-1", "orders")
        assert detail == {"sourceTableName": "orders"}

    assert len(calls) == 1, f"expected 1 fetch, got {len(calls)}"
    assert calls[0] == ("shared-model-1", "orders")


def test_topic_detail_cache_separates_distinct_keys():
    """Distinct owning models, and distinct topics, are cached independently."""
    client = make_client()
    calls: list[tuple[str, str]] = []

    def _record(model_id: str, topic_name: str) -> dict:
        calls.append((model_id, topic_name))
        return {"sourceTableName": f"{model_id}:{topic_name}"}

    client._fetch_topic_detail = _record  # type: ignore[assignment]

    for _ in range(10):
        client._fetch_topic_detail_cached("model-a", "orders")
        client._fetch_topic_detail_cached("model-a", "users")
        client._fetch_topic_detail_cached("model-b", "orders")

    assert len(calls) == 3
    assert set(calls) == {
        ("model-a", "orders"),
        ("model-a", "users"),
        ("model-b", "orders"),
    }


def test_topic_detail_failure_is_not_cached():
    """A failed fetch returns {} and is retried, not permanently blanked.

    Caching {} would let one transient failure blank that topic for every
    workbook in the run - a worse trade than re-attempting it.
    """
    client = make_client()
    calls: list[tuple[str, str]] = []

    def _record(model_id: str, topic_name: str) -> dict:
        calls.append((model_id, topic_name))
        return {}

    client._fetch_topic_detail = _record  # type: ignore[assignment]

    assert client._fetch_topic_detail_cached("model-a", "orders") == {}
    assert client._fetch_topic_detail_cached("model-a", "orders") == {}
    assert len(calls) == 2


def test_host_rate_limiter_ratchets_down_never_up():
    """The most conservative rpm any run asked for wins for the host."""
    from app.client import _RateLimiter

    limiter = _RateLimiter(60)
    assert limiter.min_interval == pytest.approx(1.0)

    limiter.tighten_to(10)          # 6s spacing - more restrictive
    assert limiter.min_interval == pytest.approx(6.0)

    limiter.tighten_to(60)          # would loosen - must be ignored
    assert limiter.min_interval == pytest.approx(6.0)

    limiter.tighten_to(0)           # rpm=0 must never disable it
    assert limiter.min_interval == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# The call site, not the memo dict.
#
# The first cut of these tests stubbed _fetch_topic_detail and called the cache
# wrapper directly, which asserts that a dict memoizes. Reverting the call site
# to model_id left the whole suite green. These drive _fetch_topics_for_model
# and assert on the URLs actually requested, so they fail if it reverts.
# ---------------------------------------------------------------------------

def _payload(files: dict) -> dict:
    return {"files": files}


def test_module_imports():
    """typedefs.py has no importer in-tree, so nothing else catches a syntax
    or signature error in it."""
    import app.typedefs  # noqa: F401
    import app.client    # noqa: F401
    import app.activities  # noqa: F401
    import app.handler  # noqa: F401


def test_single_document_failure_does_not_widen_the_crawl():
    """One transient document-detail failure must not flip the workbook filter
    off -- that widens the crawl from ~10% of models to 100%."""
    from app.client import _DOCUMENT_DETAIL_DEGRADE_THRESHOLD

    assert 0 < _DOCUMENT_DETAIL_DEGRADE_THRESHOLD < 1
    # 1 failure in 263 documents is 0.38% -- must stay below the threshold.
    assert (1 / 263) < _DOCUMENT_DETAIL_DEGRADE_THRESHOLD
    # The observed 50-in-263 (19%) must exceed it and degrade.
    assert (50 / 263) > _DOCUMENT_DETAIL_DEGRADE_THRESHOLD


# ---------------------------------------------------------------------------
# Schema-namespaced view references.
#
# Omni topic YAML names views by their internal `<schema>__<view>` reference,
# while the view FILES are keyed "<CATALOG>.<SCHEMA>/<view>.view". Keying the
# parsed views on the bare stem alone missed every lookup, and because one
# unresolvable name dumps the WHOLE topic to the per-topic API -- and
# `base_view` is a required topic parameter -- it fired on 100% of topics.
# One measured crawl fell back for 20,692 of 20,693 topics.
#
# These assert on DERIVATION SUCCEEDING, which is the invariant; they do not
# care how the lookup is implemented.
# ---------------------------------------------------------------------------

_VIEW_ORDERS = "name: order_items\ntable_name: ORDER_ITEMS\nschema: ECOMM\ncatalog: PROD\n"
_VIEW_USERS = "name: users\ntable_name: USERS\nschema: ECOMM\ncatalog: PROD\n"


def test_bare_reference_still_derives_locally():
    """Control: an org that references views bare keeps working unchanged."""
    client = make_client()
    files = {"order_items.view": _VIEW_ORDERS, "users.view": _VIEW_USERS}
    views = client._views_from_payload(files)
    parsed = {"name": "orders", "base_view": "order_items",
              "joins": {"users": {}}}

    detail = client._topic_detail_from_views(parsed, "order_items", views, {})
    assert detail is not None
    assert detail["sourceTableName"] == "ORDER_ITEMS"


def test_module_imports():
    """typedefs.py has no in-tree importer, so nothing else catches a signature
    error in it -- a removed attribute once left an orphaned _str() call."""
    import app.typedefs  # noqa: F401
    import app.client  # noqa: F401
    import app.activities  # noqa: F401
    import app.handler  # noqa: F401


def test_single_document_failure_does_not_widen_the_crawl():
    """One transient document-detail failure must not flip the workbook filter
    off -- that widens the crawl from ~10% of models to 100%."""
    from app.client import _DOCUMENT_DETAIL_DEGRADE_THRESHOLD

    assert 0 < _DOCUMENT_DETAIL_DEGRADE_THRESHOLD < 1
    assert (1 / 263) < _DOCUMENT_DETAIL_DEGRADE_THRESHOLD    # 1 flaky doc: tolerate
    assert (50 / 263) > _DOCUMENT_DETAIL_DEGRADE_THRESHOLD   # observed 19%: degrade


# ---------------------------------------------------------------------------
# View-reference forms, measured against a live Omni org (2026-09-01).
#
#   file key                                                topic reference
#   WIDE_WORLD_IMPORTERS.PROCESSED_GOLD/dim_customer.view   wide_world_importers_processed_gold__dim_customer
#   DEMO/account.view                                       demo__account
#   user_order_facts.query.view                             user_order_facts
#
# The reference is the directory path lower-cased with "." -> "_", then "__",
# then the stem, with a dotted suffix on the stem dropped. View bodies carry no
# `name` at all, so the file key is the only source.
# ---------------------------------------------------------------------------

_VIEW_BODY = "schema: PROCESSED_GOLD\ntable_name: DIM_CUSTOMER\ncatalog: WWI\n"

_LIVE_FORMS = [
    ("WIDE_WORLD_IMPORTERS.PROCESSED_GOLD/dim_customer.view",
     "wide_world_importers_processed_gold__dim_customer"),
    ("wide_world_importers.processed_gold/dim_customer.view",
     "wide_world_importers_processed_gold__dim_customer"),
    ("DEMO/account.view", "demo__account"),
    ("ECOMM/order_items.view", "ecomm__order_items"),
    ("user_order_facts.query.view", "user_order_facts"),
    ("order_items.view", "order_items"),
]


@pytest.mark.parametrize("file_key,reference", _LIVE_FORMS)
def test_live_view_reference_forms_resolve(file_key, reference):
    """Every reference form observed on a real org must resolve to its view."""
    views = ClientClass._views_from_payload({file_key: _VIEW_BODY})
    assert reference in views, (
        f"{reference!r} does not resolve to {file_key!r} -- local derivation "
        f"will fall through to the per-topic API for every topic using it"
    )


def test_full_directory_prefix_not_just_schema_segment():
    """Regression guard: the first cut used only the last dot-segment of the
    directory, which misses the two-part catalog.schema form entirely."""
    views = ClientClass._views_from_payload(
        {"WIDE_WORLD_IMPORTERS.PROCESSED_GOLD/dim_customer.view": _VIEW_BODY}
    )
    assert "wide_world_importers_processed_gold__dim_customer" in views
    # the schema-only form is registered too, harmlessly
    assert "processed_gold__dim_customer" in views


def test_schema_namespaced_topic_derives_without_api():
    """End to end: a topic whose base_view is schema-namespaced derives locally."""
    client = make_client()
    files = {
        "ECOMM/order_items.view":
            "schema: ECOMM\ntable_name: ORDER_ITEMS\ncatalog: PROD\n",
        "ECOMM/users.view":
            "schema: ECOMM\ntable_name: USERS\ncatalog: PROD\n",
    }
    views = client._views_from_payload(files)
    parsed = {"name": "order_items_embed", "base_view": "ecomm__order_items",
              "joins": {"ecomm__users": {}}}

    detail = client._topic_detail_from_views(parsed, "ecomm__order_items", views, {})

    assert detail is not None, "fell through to the per-topic API"
    assert detail["sourceTableName"] == "ORDER_ITEMS"
    assert len(detail["viewSources"]) == 2


def test_genuinely_absent_view_still_gives_up():
    """The fix must not paper over a view that really is missing."""
    client = make_client()
    views = client._views_from_payload({"ECOMM/order_items.view": _VIEW_BODY})
    assert client._topic_detail_from_views(
        {"base_view": "nowhere__missing"}, "nowhere__missing", views, {}
    ) is None


# ---------------------------------------------------------------------------
# Request-budget fixes measured on a large estate (~5,200 models).
#
# ~65% of that crawl's requests were a pair of topic-detail 404s re-issued once
# per inheriting model; a further 7-21% were 3x retries of a fixed set of
# model-YAML 403s that never clear. These pin the behaviors that stop it:
# confirmed-404 negative cache, probe-B skip on byte-identical topic files,
# 403 re-checked once then forbidden, and a run-level forbidden abort.
# ---------------------------------------------------------------------------

import re
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor

_LISTING_EMPTY = {"records": [], "pageInfo": {"hasNextPage": False}}


def _mock_listings(models: list[dict]) -> None:
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(
            200, json={"records": models, "pageInfo": {"hasNextPage": False}}
        )
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json=_LISTING_EMPTY)
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json=_LISTING_EMPTY)
    )


def _quiet_client(monkeypatch) -> ClientClass:
    """A client whose retry / re-check sleeps are no-ops."""
    monkeypatch.setattr("app.client.time.sleep", lambda _s: None)
    return make_client()


_SHARED_WB_MODELS = [
    {"id": "shared1", "modelKind": "SHARED"},
    {"id": "wb1", "name": "Workbook 1", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
]
_ORDERS_TOPIC = "label: Orders\nbase_view: orders_view\n"


def _mock_yaml(model_id: str, files: dict, mode: str = "combined"):
    return respx.get(
        f"https://test.omniapp.co/api/v1/models/{model_id}/yaml", params={"mode": mode}
    ).mock(return_value=httpx.Response(200, json={"files": files}))


def _capture(monkeypatch, level: str) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(
        f"app.client.logger.{level}", lambda msg, *a, **k: lines.append(str(msg))
    )
    return lines


# --- 1. confirmed-404 negative cache ---------------------------------------

@respx.mock
def test_topic_detail_confirmed_404_is_cached():
    """A 404 is Omni saying it cannot compile the topic; it does not change on
    retry, so the second inheriting model must not re-issue it."""
    client = make_client()
    route = respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404, text="Not found")
    )
    assert client._fetch_topic_detail_cached("shared1", "orders") == {}
    assert client._fetch_topic_detail_cached("shared1", "orders") == {}
    assert route.call_count == 1
    assert client._stats["topic_detail_404_keys_cached"] == 1
    assert client._failures["topic_detail"] == 1


@respx.mock
def test_topic_detail_non_404_failure_is_still_not_cached():
    """Only a confirmed 404 is memoized. Any other failure keeps the docstring's
    original promise: re-attempt rather than permanently blank the topic."""
    client = make_client()
    route = respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(400, text="bad")
    )
    assert client._fetch_topic_detail_cached("shared1", "orders") == {}
    assert client._fetch_topic_detail_cached("shared1", "orders") == {}
    assert route.call_count == 2
    assert client._stats["topic_detail_404_keys_cached"] == 0
    assert ("shared1", "orders") not in client._topic_detail_not_found


# --- 2. probe B skipped only when it provably cannot help -----------------

@respx.mock
def test_probe_b_skipped_when_inheriting_copy_is_byte_identical_to_owner():
    _mock_listings(_SHARED_WB_MODELS)
    _mock_yaml("shared1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {}, mode="extension")
    owner_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/shared1/topic/orders"
    ).mock(return_value=httpx.Response(404))
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    snapshot = client.fetch_snapshot(crawl_only_content_backed_workbooks=False)

    assert owner_probe.call_count == 1
    assert model_probe.call_count == 0, "probe B re-issued a 404 it could predict"
    assert client._stats["topic_detail_probe_b_skipped"] == 1
    # The emitted row is IDENTICAL to what the double-404 path produced before:
    # YAML-only fields, no lineage keys.
    wb_topic = next(t for t in snapshot["topics"] if t["modelId"] == "wb1")
    assert wb_topic == {
        "modelId": "wb1",
        "owningModelId": "shared1",
        "name": "orders",
        "label": "Orders",
        "baseViewName": "orders_view",
    }
    assert client._prefetched_yaml == {}


@respx.mock
def test_probe_b_runs_when_inheriting_copy_differs_from_owner():
    """A BRANCH / extension-defined topic has different content — the model
    itself may compile it, so the per-model probe still runs."""
    _mock_listings(_SHARED_WB_MODELS)
    _mock_yaml("shared1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC + "joins:\n  users: {}\n"})
    _mock_yaml("wb1", {}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    client.fetch_snapshot(crawl_only_content_backed_workbooks=False)
    assert model_probe.call_count == 1
    assert client._stats["topic_detail_probe_b_skipped"] == 0


@respx.mock
def test_probe_b_runs_when_owner_lacks_the_topic_file():
    _mock_listings(_SHARED_WB_MODELS)
    _mock_yaml("shared1", {"other.topic": "label: Other\n"})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/other").mock(
        return_value=httpx.Response(404)
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    client.fetch_snapshot(crawl_only_content_backed_workbooks=False)
    assert model_probe.call_count == 1


@respx.mock
def test_probe_b_runs_when_owner_failure_was_not_a_confirmed_404():
    """A transient owner failure is not evidence the model will 404 too."""
    _mock_listings(_SHARED_WB_MODELS)
    _mock_yaml("shared1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(400, text="bad")
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(200, json={"topic": {"views": []}}))

    client = make_client()
    client.fetch_snapshot(crawl_only_content_backed_workbooks=False)
    assert model_probe.call_count == 1


@respx.mock
def test_probe_b_skip_does_not_apply_to_genuinely_overridden_topics():
    """owning == model for an override: the existing single probe is unchanged."""
    _mock_listings(_SHARED_WB_MODELS)
    _mock_yaml("shared1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    snapshot = client.fetch_snapshot(crawl_only_content_backed_workbooks=False)
    wb_topic = next(t for t in snapshot["topics"] if t["modelId"] == "wb1")
    assert wb_topic["owningModelId"] == "wb1"
    assert model_probe.call_count == 1
    assert client._stats["topic_detail_probe_b_skipped"] == 0


@respx.mock
def test_owner_yaml_costs_one_request_even_when_inheriting_model_runs_first():
    """If a workbook gets ahead of its SHARED owner in the pool, the owner's
    YAML is fetched lazily for the hash comparison and then REUSED by the
    owner's own pass — never fetched twice, and nothing left parked."""
    owner_yaml = _mock_yaml("shared1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    client._model_lookup = {m["id"]: m for m in _SHARED_WB_MODELS}
    wb_topics = client._fetch_topics_for_model(_SHARED_WB_MODELS[1])
    assert owner_yaml.call_count == 1
    assert model_probe.call_count == 0
    assert wb_topics[0]["owningModelId"] == "shared1"
    assert "shared1" in client._prefetched_yaml

    owner_topics = client._fetch_topics_for_model(_SHARED_WB_MODELS[0])
    assert owner_yaml.call_count == 1, "owner YAML fetched twice"
    assert owner_topics[0]["modelId"] == "shared1"
    assert client._prefetched_yaml == {}


@respx.mock
def test_owner_yaml_is_single_flight_when_owner_and_inheritor_race():
    """Owner's YAML slow and in flight while the inheriting model reaches the
    hash comparison: exactly one owner request, nothing left in
    `_prefetched_yaml`, and the inheritor still gets the skip."""
    calls = {"owner_yaml": 0}

    def slow_owner(request):
        calls["owner_yaml"] += 1
        _time.sleep(0.5)
        return httpx.Response(200, json={"files": {"orders.topic": _ORDERS_TOPIC}})

    respx.get("https://test.omniapp.co/api/v1/models/shared1/yaml").mock(side_effect=slow_owner)
    _mock_yaml("wb1", {"orders.topic": _ORDERS_TOPIC})
    _mock_yaml("wb1", {}, mode="extension")
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    model_probe = respx.get(
        "https://test.omniapp.co/api/v1/models/wb1/topic/orders"
    ).mock(return_value=httpx.Response(404))

    client = make_client()
    client._model_lookup = {m["id"]: m for m in _SHARED_WB_MODELS}
    t_owner = threading.Thread(target=client._fetch_topics_for_model, args=(_SHARED_WB_MODELS[0],))
    t_owner.start()
    _time.sleep(0.1)
    client._fetch_topics_for_model(_SHARED_WB_MODELS[1])
    t_owner.join()

    assert calls["owner_yaml"] == 1
    assert client._prefetched_yaml == {}
    assert model_probe.call_count == 0
    assert client._stats["topic_detail_probe_b_skipped"] == 1


# --- 3. 403: re-check once, then forbidden; run-level abort ---------------

@respx.mock
def test_isolated_403_is_rechecked_once_then_forbidden(monkeypatch):
    from app.client import OmniForbiddenError

    client = _quiet_client(monkeypatch)
    acquires: list[int] = []
    real_acquire = client._rate_limiter.acquire
    monkeypatch.setattr(
        client._rate_limiter, "acquire", lambda: (acquires.append(1), real_acquire())
    )
    route = respx.get(
        "https://test.omniapp.co/api/v1/models/m1/yaml", params={"mode": "combined"}
    ).mock(return_value=httpx.Response(403, text='{"detail":"Forbidden for m1"}'))

    with pytest.raises(OmniForbiddenError) as excinfo:
        client.get_model_yaml("m1")
    assert route.call_count == 2, "exactly one re-check, no backoff ladder"
    assert len(acquires) == 2, "every attempt must pass the rpm gate"
    assert excinfo.value.status_code == 403
    assert excinfo.value.retryable is False
    assert "Forbidden for m1" in excinfo.value.body


@respx.mock
def test_403_recheck_that_returns_200_is_processed_normally(monkeypatch):
    client = _quiet_client(monkeypatch)
    _mock_listings([{"id": "m1"}])
    route = respx.get(
        "https://test.omniapp.co/api/v1/models/m1/yaml", params={"mode": "combined"}
    )
    route.side_effect = [
        httpx.Response(403, text="Invalid bearer token"),
        httpx.Response(200, json={"files": {"orders.topic": _ORDERS_TOPIC}}),
    ]
    respx.get("https://test.omniapp.co/api/v1/models/m1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    snapshot = client.fetch_snapshot()
    assert route.call_count == 2
    assert [t["modelId"] for t in snapshot["topics"]] == ["m1"]
    assert client._failures["model_yaml_forbidden"] == 0
    assert client._forbidden_model_ids == []


@respx.mock
def test_403_recheck_that_returns_429_takes_the_rate_limit_ladder(monkeypatch):
    """403 -> re-check -> 429: that is the existing 429 backoff, not forbidden."""
    from app.client import OmniForbiddenError

    client = _quiet_client(monkeypatch)
    route = respx.get("https://test.omniapp.co/api/v1/connections")
    route.side_effect = [
        httpx.Response(403, text="Invalid bearer token"),
        httpx.Response(429, text="Rate limited"),
        httpx.Response(200, json={"connections": [{"id": "c1"}]}),
    ]
    assert client.list_connections()[0]["id"] == "c1"
    assert route.call_count == 3

    # And a 429 ladder that never clears still ends retryable, never forbidden.
    route.side_effect = [httpx.Response(403)] + [httpx.Response(429)] * 4
    with pytest.raises(OmniApiError) as excinfo:
        client.list_connections()
    assert not isinstance(excinfo.value, OmniForbiddenError)
    assert excinfo.value.retryable is True
    assert route.call_count == 3 + 5  # 403, then 1 + 3 retries of 429


@respx.mock
def test_contiguous_forbidden_models_cost_two_requests_each_and_never_abort(monkeypatch):
    """Six forbidden models adjacent in the listing, ten workers: each costs
    exactly one request plus one re-check, none is counted as model_yaml, and
    the run completes (6/8 = 75% forbidden, but under the min sample)."""
    client = _quiet_client(monkeypatch)
    warnings = _capture(monkeypatch, "warning")
    models = [{"id": f"f{i}"} for i in range(6)] + [{"id": "ok1"}, {"id": "ok2"}]
    _mock_listings(models)
    forbidden_routes = {}
    for i in range(6):
        forbidden_routes[f"f{i}"] = respx.get(
            f"https://test.omniapp.co/api/v1/models/f{i}/yaml", params={"mode": "combined"}
        ).mock(return_value=httpx.Response(403, text=f"no access to f{i}"))
    for mid in ("ok1", "ok2"):
        _mock_yaml(mid, {"orders.topic": _ORDERS_TOPIC})
        respx.get(f"https://test.omniapp.co/api/v1/models/{mid}/topic/orders").mock(
            return_value=httpx.Response(404)
        )

    snapshot = client.fetch_snapshot(max_concurrency=10)

    assert client._failures["model_yaml"] == 0
    assert client._failures["model_yaml_forbidden"] == 6
    assert sorted(client._forbidden_model_ids) == [f"f{i}" for i in range(6)]
    for mid, route in forbidden_routes.items():
        assert route.call_count == 2, f"{mid} cost {route.call_count} requests"
    assert sorted(t["modelId"] for t in snapshot["topics"]) == ["ok1", "ok2"]
    forbidden_logs = [w for w in warnings if "model YAML forbidden" in w]
    assert len(forbidden_logs) == 6, "one WARNING per forbidden model"
    assert any("no access to f3" in w for w in forbidden_logs), "body snippet missing"


def _mock_estate(n_models: int, n_forbidden: int) -> None:
    """n_models plain models, the first n_forbidden of which 403 on YAML."""
    _mock_listings([{"id": f"m{i:03d}"} for i in range(n_models)])

    def yaml_handler(request):
        idx = int(re.search(r"/models/m(\d+)/yaml", str(request.url)).group(1))
        if idx < n_forbidden:
            return httpx.Response(403, text="Invalid bearer token")
        return httpx.Response(200, json={"files": {}})

    respx.get(url__regex=r".*/v1/models/m\d+/yaml.*").mock(side_effect=yaml_handler)


@respx.mock
def test_partial_forbidden_estate_now_completes(monkeypatch):
    """0.4.3: the 30% ratio-abort was removed. A partial-permission estate
    (CCI's shape: 2,800 of 6,163 forbidden with the per-model-perms body)
    now completes with the readable models rather than aborting the run.
    The only abort check left is "every model forbidden"."""
    from app.client import _FORBIDDEN_ABORT_MIN_MODELS

    client = _quiet_client(monkeypatch)
    n = _FORBIDDEN_ABORT_MIN_MODELS + 10
    _mock_estate(n, n_forbidden=n // 3 + 1)  # just over 30%

    snapshot = client.fetch_snapshot(max_concurrency=4)
    assert len(snapshot["models"]) == n
    assert client._failures["model_yaml_forbidden"] == n // 3 + 1
    assert client._failures["model_yaml"] == 0, "forbidden must not count as model_yaml"


@respx.mock
def test_every_model_forbidden_aborts(monkeypatch):
    """10 models, all 403 twice: a run that can read NOTHING must not complete
    with zero topics and report success. The N == M safety net survives."""
    client = _quiet_client(monkeypatch)
    _mock_estate(10, n_forbidden=10)

    with pytest.raises(OmniApiError, match="all 10 models returned 403") as excinfo:
        client.fetch_snapshot(max_concurrency=4)
    assert "token cannot read any model" in str(excinfo.value)
    assert client._failures["model_yaml_forbidden"] == 10
    assert client._failures["model_yaml"] == 0


@respx.mock
def test_forbidden_share_at_or_below_ratio_completes_and_lists_ids(monkeypatch):
    from app.client import _FORBIDDEN_ABORT_MIN_MODELS

    client = _quiet_client(monkeypatch)
    warnings = _capture(monkeypatch, "warning")
    n = _FORBIDDEN_ABORT_MIN_MODELS + 10
    _mock_estate(n, n_forbidden=10)  # ~17%

    snapshot = client.fetch_snapshot(max_concurrency=4)
    assert len(snapshot["models"]) == n
    assert client._failures["model_yaml_forbidden"] == 10
    summary = [w for w in warnings if "returned 403 for their YAML" in w]
    assert len(summary) == 1
    assert "10 model(s)" in summary[0] and "m000" in summary[0] and "m009" in summary[0]


# --- 4. observability -----------------------------------------------------

_JOINS_TOPIC = "label: Orders\nbase_view: ecomm__order_items\njoins:\n  ghost_view: {}\n"


@respx.mock
def test_unresolved_view_warning_is_logged_once_per_owner_and_topic(monkeypatch):
    """One SHARED owner, three inheriting workbooks, one topic whose `joins`
    names a view the payload does not carry: ONE warning naming the view (and
    the owner), one `topic_unresolved_views`, not one line per workbook."""
    warnings = _capture(monkeypatch, "warning")
    workbooks = [
        {"id": f"wb{i}", "name": f"W{i}", "modelKind": "WORKBOOK", "baseModelId": "shared1"}
        for i in range(3)
    ]
    _mock_listings([{"id": "shared1", "modelKind": "SHARED"}] + workbooks)
    files = {"orders.topic": _JOINS_TOPIC, "ECOMM/order_items.view": _VIEW_BODY}
    _mock_yaml("shared1", files)
    for wb in workbooks:
        _mock_yaml(wb["id"], files)
        _mock_yaml(wb["id"], {}, mode="extension")
        respx.get(f"https://test.omniapp.co/api/v1/models/{wb['id']}/topic/orders").mock(
            return_value=httpx.Response(404)
        )
    respx.get("https://test.omniapp.co/api/v1/models/shared1/topic/orders").mock(
        return_value=httpx.Response(404)
    )

    client = make_client()
    client.fetch_snapshot(crawl_only_content_backed_workbooks=False)

    unresolved = [w for w in warnings if "not derivable locally" in w]
    assert len(unresolved) == 1, unresolved
    assert "owning_model_id=shared1" in unresolved[0]
    assert "ghost_view" in unresolved[0]
    assert "ecomm__order_items" not in unresolved[0].split("unresolved")[1]
    assert client._stats["topic_unresolved_views"] == 1


def test_unresolved_view_warning_is_silent_without_context(monkeypatch):
    warnings = _capture(monkeypatch, "warning")
    client = make_client()
    views = client._views_from_payload({"ECOMM/order_items.view": _VIEW_BODY})
    parsed = {"base_view": "ecomm__order_items", "joins": {"ghost_view": {}}}
    assert client._topic_detail_from_views(parsed, "ecomm__order_items", views, {}) is None
    assert warnings == []
    assert client._stats["topic_unresolved_views"] == 0


def test_new_counters_reset_per_run_and_ride_the_progress_line(monkeypatch):
    infos = _capture(monkeypatch, "info")
    with respx.mock:
        _mock_listings([{"id": "m1"}])
        _mock_yaml("m1", {"orders.topic": _ORDERS_TOPIC})
        respx.get("https://test.omniapp.co/api/v1/models/m1/topic/orders").mock(
            return_value=httpx.Response(404)
        )
        client = make_client()
        client._stats["topic_detail_probe_b_skipped"] = 99
        client._failures["model_yaml_forbidden"] = 99
        client.fetch_snapshot()
    assert client._stats["topic_detail_probe_b_skipped"] == 0
    assert client._failures["model_yaml_forbidden"] == 0
    progress = [m for m in infos if m.startswith("fetch_snapshot progress: models")]
    assert progress, infos
    for key in (
        "topic_detail_404_keys_cached=",
        "topic_detail_probe_b_skipped=",
        "topic_unresolved_views=",
        "model_yaml_forbidden=",
    ):
        assert key in progress[-1], progress[-1]
    summary = [m for m in infos if m.startswith("fetch_snapshot failures:")]
    assert summary and "model_yaml_forbidden=0" in summary[0]
    assert "topic_unresolved_views=0" in summary[0]


# ---------------------------------------------------------------------------
# 0.4.3: YAML parse cache (byte-identical files parse once per run)
# ---------------------------------------------------------------------------

def test_parse_yaml_cached_returns_same_result_without_reparsing(monkeypatch):
    """Byte-identical input is parsed once; the second call is a cache hit."""
    import yaml as _yaml
    client = ClientClass(credentials=CREDS, rpm=0)
    calls = {"n": 0}
    real = _yaml.safe_load
    def counted(s):
        calls["n"] += 1
        return real(s)
    monkeypatch.setattr("app.client.yaml.safe_load", counted)

    body = "label: Orders\nbase_view: orders_view\n"
    first = client._parse_yaml_cached(body)
    second = client._parse_yaml_cached(body)
    assert first == {"label": "Orders", "base_view": "orders_view"}
    assert second == first
    assert calls["n"] == 1
    assert client._stats["yaml_parse_cache_hits"] == 1


def test_parse_yaml_cached_differentiates_distinct_content(monkeypatch):
    """Different bytes bypass the cache even when the parsed value is equal."""
    import yaml as _yaml
    client = ClientClass(credentials=CREDS, rpm=0)
    calls = {"n": 0}
    real = _yaml.safe_load
    def counted(s):
        calls["n"] += 1
        return real(s)
    monkeypatch.setattr("app.client.yaml.safe_load", counted)

    client._parse_yaml_cached("a: 1\n")
    client._parse_yaml_cached("a: 1\nb: 2\n")
    assert calls["n"] == 2
    assert client._stats["yaml_parse_cache_hits"] == 0


def test_parse_yaml_cached_memoizes_parse_errors(monkeypatch):
    """A YAMLError is memoized as None — don't re-raise on identical junk."""
    import yaml as _yaml
    client = ClientClass(credentials=CREDS, rpm=0)
    calls = {"n": 0}
    real = _yaml.safe_load
    def counted(s):
        calls["n"] += 1
        return real(s)
    monkeypatch.setattr("app.client.yaml.safe_load", counted)

    # Unterminated flow scalar — safe_load raises yaml.YAMLError.
    junk = "key: [unterminated"
    assert client._parse_yaml_cached(junk) is None
    assert client._parse_yaml_cached(junk) is None
    assert calls["n"] == 1


@respx.mock
def test_parse_yaml_cache_resets_per_run(monkeypatch):
    """The cache is per-run — fetch_snapshot clears it before each run so a
    cross-tenant pod running one activity after another doesn't carry state."""
    client = _quiet_client(monkeypatch)
    client._yaml_parse_cache["sentinel"] = "stale"
    client._stats["yaml_parse_cache_hits"] = 999
    _mock_listings([])
    client.fetch_snapshot()
    assert "sentinel" not in client._yaml_parse_cache
    assert client._stats["yaml_parse_cache_hits"] == 0


@respx.mock
def test_identical_topic_files_across_workbooks_parse_once(monkeypatch):
    """CCI's hot path: a shared topic inherited verbatim by three workbooks
    is parsed once, cache hit twice.

    The two workbook models are opt-in to the aggressive filter by appearing
    in /v1/documents (otherwise they are dropped as content-less and never
    reach `_fetch_topics_for_model`, which is the parse site)."""
    client = _quiet_client(monkeypatch)
    # listings: 3 models and 2 documents whose modelId points at each wb,
    # so item 4a's filter keeps both wbs.
    respx.get("https://test.omniapp.co/api/v1/connections").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    respx.get("https://test.omniapp.co/api/v1/models").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"id": "shared1", "modelKind": "SHARED"},
                {"id": "wb1", "name": "WB 1", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
                {"id": "wb2", "name": "WB 2", "modelKind": "WORKBOOK", "baseModelId": "shared1"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/folders").mock(
        return_value=httpx.Response(200, json=_LISTING_EMPTY)
    )
    respx.get("https://test.omniapp.co/api/v1/documents").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"identifier": "d1", "name": "D1"},
                {"identifier": "d2", "name": "D2"},
            ],
            "pageInfo": {"hasNextPage": False},
        })
    )
    respx.get("https://test.omniapp.co/api/v1/documents/d1").mock(
        return_value=httpx.Response(200, json={"modelId": "wb1", "queryPresentations": []})
    )
    respx.get("https://test.omniapp.co/api/v1/documents/d2").mock(
        return_value=httpx.Response(200, json={"modelId": "wb2", "queryPresentations": []})
    )
    files = {"orders.topic": _ORDERS_TOPIC}
    _mock_yaml("shared1", files)
    _mock_yaml("wb1", files)
    _mock_yaml("wb1", {}, mode="extension")
    _mock_yaml("wb2", files)
    _mock_yaml("wb2", {}, mode="extension")
    for model_id in ("shared1", "wb1", "wb2"):
        respx.get(f"https://test.omniapp.co/api/v1/models/{model_id}/topic/orders").mock(
            return_value=httpx.Response(404)
        )

    client.fetch_snapshot(max_concurrency=4)
    # Three parses of _ORDERS_TOPIC would be the pre-cache number; now it's
    # parsed once and hit at least twice.
    assert client._stats["yaml_parse_cache_hits"] >= 2


# ---------------------------------------------------------------------------
# 0.4.3: body-text-aware 403 branching
# ---------------------------------------------------------------------------

@respx.mock
def test_403_with_permission_denied_body_skips_recheck(monkeypatch):
    """CCI's shape: body says "You do not have permission..." — not a burst,
    skip the recheck. One request, OmniForbiddenError raised."""
    from app.client import OmniForbiddenError

    client = _quiet_client(monkeypatch)
    route = respx.get(
        "https://test.omniapp.co/api/v1/models/m1/yaml", params={"mode": "combined"}
    ).mock(return_value=httpx.Response(
        403,
        text='{"detail":"You do not have permission to read the model yaml for model m1","status":403}',
    ))

    with pytest.raises(OmniForbiddenError) as excinfo:
        client.get_model_yaml("m1")
    assert route.call_count == 1, "permanent-marker 403 must not be rechecked"
    assert "You do not have permission" in excinfo.value.body


@respx.mock
def test_403_with_permission_denied_body_is_case_insensitive(monkeypatch):
    """Substring match must survive a minor casing tweak on Omni's side."""
    from app.client import OmniForbiddenError
    client = _quiet_client(monkeypatch)
    route = respx.get(
        "https://test.omniapp.co/api/v1/models/m1/yaml", params={"mode": "combined"}
    ).mock(return_value=httpx.Response(
        403, text="YOU DO NOT HAVE PERMISSION to see this",
    ))

    with pytest.raises(OmniForbiddenError):
        client.get_model_yaml("m1")
    assert route.call_count == 1


@respx.mock
def test_403_invalid_bearer_token_still_rechecked(monkeypatch):
    """The burst-refusal path survives — 'Invalid bearer token' is the body
    we saw on Peter's org during rate-limit experiments, not permanent."""
    client = _quiet_client(monkeypatch)
    _mock_listings([{"id": "m1"}])
    route = respx.get(
        "https://test.omniapp.co/api/v1/models/m1/yaml", params={"mode": "combined"}
    )
    route.side_effect = [
        httpx.Response(403, text="Invalid bearer token"),
        httpx.Response(200, json={"files": {"orders.topic": _ORDERS_TOPIC}}),
    ]
    respx.get("https://test.omniapp.co/api/v1/models/m1/topic/orders").mock(
        return_value=httpx.Response(404)
    )
    snapshot = client.fetch_snapshot()
    assert route.call_count == 2
    assert [t["modelId"] for t in snapshot["topics"]] == ["m1"]


@respx.mock
def test_cci_shape_many_perms_denied_completes_without_recheck(monkeypatch):
    """CCI's actual shape: 60 models, 30 return the per-model permission body.
    Each forbidden model costs exactly ONE request (no recheck), the run
    completes, forbidden_model_ids_total ends at 30."""
    client = _quiet_client(monkeypatch)
    models = [{"id": f"m{i:03d}"} for i in range(60)]
    _mock_listings(models)

    def yaml_handler(request):
        idx = int(re.search(r"/models/m(\d+)/yaml", str(request.url)).group(1))
        if idx < 30:
            return httpx.Response(
                403,
                text=f'{{"detail":"You do not have permission to read the model yaml for model m{idx:03d}","status":403}}',
            )
        return httpx.Response(200, json={"files": {}})

    yaml_route = respx.get(url__regex=r".*/v1/models/m\d+/yaml.*").mock(side_effect=yaml_handler)

    snapshot = client.fetch_snapshot(max_concurrency=4)
    assert len(snapshot["models"]) == 60
    assert client._failures["model_yaml_forbidden"] == 30
    assert client._failures["model_yaml"] == 0
    # 30 forbidden x 1 request each + 30 readable x 1 request = 60 total
    assert yaml_route.call_count == 60, (
        f"expected 60 YAML calls (no recheck), got {yaml_route.call_count}"
    )
