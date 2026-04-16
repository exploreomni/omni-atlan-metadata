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
    return ClientClass(credentials=CREDS)


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

    snapshot = make_client().fetch_snapshot()
    assert snapshot["topics"] == [
        {"modelId": "mod1", "name": "orders", "label": "Orders", "baseViewName": "orders_view"}
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

    snapshot = make_client().fetch_snapshot()
    topic_model_ids = {t["modelId"] for t in snapshot["topics"]}
    assert topic_model_ids == {"mod1", "mod2"}
    assert len(snapshot["topics"]) == 2


@respx.mock
def test_fetch_snapshot_yaml_failure_skips_model_but_continues():
    """A failed YAML call for one model does not abort the rest of the batch."""
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
    respx.get("https://test.omniapp.co/api/v1/models/mod1/yaml").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    yaml2 = "label: Customers\nbase_view_name: customers_view\n"
    respx.get("https://test.omniapp.co/api/v1/models/mod2/yaml").mock(
        return_value=httpx.Response(200, json={"files": {"customers.topic": yaml2}})
    )

    snapshot = make_client().fetch_snapshot()
    assert len(snapshot["topics"]) == 1
    assert snapshot["topics"][0]["modelId"] == "mod2"


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
    assert snapshot["document_model_ids"] == {"mod1", "mod2"}


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
    assert snapshot["document_model_ids"] == {"mod2"}


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
