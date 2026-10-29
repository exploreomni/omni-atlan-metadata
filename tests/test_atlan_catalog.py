"""Tests for app/atlan_catalog.py — the warehouse-type resolver."""

import httpx
import pytest
import respx

from app.atlan_catalog import AtlanCatalogResolver


BASE_URL = "https://test.atlan.com"
API_KEY = "test-key"


def _resolver() -> AtlanCatalogResolver:
    return AtlanCatalogResolver(base_url=BASE_URL, api_key=API_KEY)


def test_enabled_false_without_credentials(monkeypatch):
    """Resolver falls back to disabled when neither constructor arg nor env
    provides credentials. In that state resolve_type always returns None —
    the caller then skips the source rather than guess."""
    monkeypatch.delenv("ATLAN_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAN_API_KEY", raising=False)
    r = AtlanCatalogResolver()
    assert r.enabled is False
    assert r.resolve_type("default/redshift/x/a/b/c") is None


def test_enabled_true_with_env_credentials(monkeypatch):
    monkeypatch.setenv("ATLAN_BASE_URL", BASE_URL)
    monkeypatch.setenv("ATLAN_API_KEY", API_KEY)
    assert AtlanCatalogResolver().enabled is True


@respx.mock
def test_resolve_returns_view_for_view_qn():
    """CCI shape — the physical object is a Redshift View; indexsearch returns
    `typeName: View`; resolver surfaces that to the caller."""
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(200, json={
            "entities": [{"typeName": "View", "attributes": {"qualifiedName": "x"}}],
        })
    )
    r = _resolver()
    assert r.resolve_type("default/redshift/1/analytics/public/vw_users") == "View"


@respx.mock
def test_resolve_returns_table_for_table_qn():
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(200, json={
            "entities": [{"typeName": "Table"}],
        })
    )
    assert _resolver().resolve_type("default/snowflake/1/a/b/c") == "Table"


@respx.mock
def test_resolve_returns_none_for_unknown_qn():
    """QN not in Atlan's catalog (warehouse crawler never ran, source
    dropped, ...): empty hits -> None -> caller skips the lineage input."""
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(200, json={"entities": []})
    )
    assert _resolver().resolve_type("default/redshift/1/no/such/thing") is None


@respx.mock
def test_resolve_caches_the_lookup_per_qn():
    """One HTTP call per unique QN, cache hits otherwise. CCI's shape sees
    the same source QNs across many topics — caching is load-bearing."""
    route = respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(200, json={"entities": [{"typeName": "View"}]})
    )
    r = _resolver()
    qn = "default/redshift/1/a/b/c"
    assert r.resolve_type(qn) == "View"
    assert r.resolve_type(qn) == "View"
    assert r.resolve_type(qn) == "View"
    assert route.call_count == 1
    assert r.stats["hits"] == 2
    assert r.stats["lookups"] == 1


@respx.mock
def test_resolve_distinct_qns_each_fetched_once():
    """Different QNs = different lookups. Verifies the cache key is the QN."""
    responses = iter([
        httpx.Response(200, json={"entities": [{"typeName": "Table"}]}),
        httpx.Response(200, json={"entities": [{"typeName": "View"}]}),
    ])
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        side_effect=lambda req: next(responses)
    )
    r = _resolver()
    assert r.resolve_type("a") == "Table"
    assert r.resolve_type("b") == "View"
    assert r.stats["lookups"] == 2


@respx.mock
def test_resolve_returns_none_on_5xx_without_raising():
    """A transient 5xx must not abort the transform — one bad lookup can't
    kill a 4-hour crawl. Error is counted + logged, resolver returns None,
    source is skipped."""
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(503, text="atlas boom")
    )
    r = _resolver()
    assert r.resolve_type("default/x/a/b/c") is None
    assert r.stats["errors"] == 1


@respx.mock
def test_resolve_returns_none_on_network_error():
    """httpx.HTTPError (DNS, connect reset, etc.) same contract as 5xx."""
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    r = _resolver()
    assert r.resolve_type("default/x/a/b/c") is None
    assert r.stats["errors"] == 1


@respx.mock
def test_resolve_non_json_body_counts_as_error():
    respx.post(f"{BASE_URL}/api/meta/search/indexsearch").mock(
        return_value=httpx.Response(200, text="<html>login</html>")
    )
    r = _resolver()
    assert r.resolve_type("default/x/a/b/c") is None
    assert r.stats["errors"] == 1


def test_close_is_idempotent():
    r = _resolver()
    r.close()
    r.close()  # must not raise
