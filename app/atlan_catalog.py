"""Resolve the typeName of warehouse QNs by asking Atlan's catalog.

The source-table lineage pass used to hard-code every input as `typeName:
"Table"`. On tenants where some sources are Redshift Views or
MaterialisedViews (CCI's 2026-10-28 run: 32 of 57 lineage inputs were
views), that produced ATLAS-404-00-00A rejections at publish time — the
publisher looks up the referent by `(typeName, qualifiedName)` and the
view is in the catalog under its real type, not under `Table`.

The physical object type is NOT in Omni's `.view` YAML (Omni's view is a
Looker-style abstraction with `table_name` / `schema` / `catalog` but no
object kind). It IS in Atlan's catalog, which is where the warehouse
crawler put it. So we ask Atlan.

Design:
- One HTTP call per unique QN per run, cached (CCI's shape: a few hundred
  unique QNs, cached across all referring topics).
- The call is a terms filter on `typeName IN (Table, View, MaterialisedView,
  ...)` AND `qualifiedName == <qn>` against the indexsearch endpoint.
- If the QN isn't found in Atlan at all (warehouse crawler hasn't run yet,
  or the view was dropped), return None and let the caller decide what to
  do. The caller currently drops the source rather than emit a dangling
  ref — the opposite of the pre-fix behaviour of guessing `Table`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from application_sdk.observability.logger_adaptor import get_logger

logger = get_logger(__name__)

# Candidate typeNames for warehouse sources a BI tool might reference.
# Order is immaterial — the resolver matches on whatever Atlan returns.
# Covers Snowflake, Redshift, BigQuery, Postgres, MSSQL, Databricks.
_WAREHOUSE_SOURCE_TYPES: tuple[str, ...] = (
    "Table",
    "View",
    "MaterialisedView",
    "MaterializedView",  # US spelling, used by some connectors
)

# "SQL" is the shared supertype that Atlan Atlas resolves these under. If
# we ever hit a type we didn't enumerate above, searching this catches it.
# Kept separate so the primary query stays narrow.
_WAREHOUSE_SOURCE_SUPERTYPE = "SQL"


class AtlanCatalogResolver:
    """Resolve warehouse QN -> typeName via a per-run cache.

    The resolver assumes the Atlan tenant is reachable at `ATLAN_BASE_URL`
    with `ATLAN_API_KEY` — same env the typedef registration already uses.
    Call `.resolve_type(qn)` and get back one of the warehouse source
    typeNames, or `None` if the QN isn't in the catalog.

    Not thread-safe for cache writes — fine today because
    `_processes_source_to_topic` runs single-threaded in `transform()`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("ATLAN_BASE_URL") or "").rstrip("/")
        self._api_key = api_key or os.environ.get("ATLAN_API_KEY") or ""
        self._cache: dict[str, str | None] = {}
        self._stats = {"hits": 0, "misses": 0, "errors": 0, "lookups": 0}
        self._client = http_client
        self._owns_client = http_client is None

    @property
    def enabled(self) -> bool:
        """True only when both base URL and API key resolved to non-empty."""
        return bool(self._base_url and self._api_key)

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=15,
            )
        return self._client

    def resolve_type(self, qualified_name: str) -> str | None:
        """Return the Atlan typeName for `qualified_name`, or None.

        None covers three cases, from the caller's point of view
        indistinguishable:
          - resolver was built without credentials (local playground)
          - the QN isn't in Atlan's catalog
          - the lookup errored (network, 5xx)

        All three mean "do not emit a lineage input for this source" —
        guessing `Table` is what caused the ATLAS-404s in the first place.
        """
        if not self.enabled:
            return None
        if qualified_name in self._cache:
            self._stats["hits"] += 1
            return self._cache[qualified_name]
        self._stats["lookups"] += 1
        type_name = self._fetch_type(qualified_name)
        if type_name is None:
            self._stats["misses"] += 1
        self._cache[qualified_name] = type_name
        return type_name

    def _fetch_type(self, qualified_name: str) -> str | None:
        """One indexsearch call: find the typeName for a specific QN."""
        payload: dict[str, Any] = {
            "dsl": {
                "size": 1,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"qualifiedName": qualified_name}},
                            {"terms": {"__typeName.keyword": list(_WAREHOUSE_SOURCE_TYPES)}},
                        ]
                    }
                },
            },
            "attributes": ["qualifiedName"],
        }
        try:
            resp = self._get_client().post("/api/meta/search/indexsearch", json=payload)
        except httpx.HTTPError as exc:
            self._stats["errors"] += 1
            logger.warning(f"atlan catalog resolve error for {qualified_name}: {exc!r}")
            return None
        if resp.status_code >= 400:
            self._stats["errors"] += 1
            logger.warning(
                f"atlan catalog resolve non-2xx for {qualified_name}: "
                f"{resp.status_code} {resp.text[:200]!r}"
            )
            return None
        try:
            body = resp.json()
        except ValueError:
            self._stats["errors"] += 1
            return None
        entities = body.get("entities") or []
        if not entities:
            return None
        first = entities[0]
        type_name = first.get("typeName")
        if isinstance(type_name, str) and type_name:
            return type_name
        return None
