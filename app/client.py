from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import Any

import httpx
import yaml
from application_sdk.observability.logger_adaptor import get_logger

logger = get_logger(__name__)


def _parse_dt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


@dataclass
class OmniCredentials:
    base_url: str
    api_token: str
    verify_ssl: bool = True
    timeout_seconds: int = 30

    def __repr__(self) -> str:
        return (
            f"OmniCredentials(base_url={self.base_url!r}, api_token='***', "
            f"verify_ssl={self.verify_ssl}, timeout_seconds={self.timeout_seconds})"
        )


class OmniApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class NonRetryableOmniApiError(OmniApiError):
    pass


class ClientClass:
    def __init__(self, credentials: dict[str, Any] | None = None):
        self._credentials: OmniCredentials | None = None
        self._http_client: httpx.Client | None = None
        if credentials:
            self.load_credentials(credentials)

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        base_url = str(credentials.get("omni_base_url", "")).strip().rstrip("/")
        token = str(credentials.get("omni_api_token", "")).strip()
        if not base_url or not token:
            raise ValueError("Both omni_base_url and omni_api_token are required.")
        if not (base_url.startswith("https://") or base_url.startswith("http://")):
            raise ValueError(
                "omni_base_url must include protocol, for example "
                "'https://your-org.omniapp.co/api'."
            )

        verify_ssl = bool(credentials.get("verify_ssl", True))
        timeout_seconds = int(credentials.get("timeout_seconds", 30))
        self._credentials = OmniCredentials(
            base_url=base_url,
            api_token=token,
            verify_ssl=verify_ssl,
            timeout_seconds=timeout_seconds,
        )

        self.close()
        self._http_client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            verify=verify_ssl,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def _client(self) -> httpx.Client:
        if not self._http_client:
            raise OmniApiError("Omni client is not initialized. Call load_credentials first.")
        return self._http_client

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        max_rate_limit_retries = 3
        max_server_error_retries = 2

        for attempt in range(max_rate_limit_retries + 1):
            try:
                response = self._client().get(path, params=params or {})
            except httpx.HTTPError as exc:
                if attempt < max_server_error_retries:
                    delay = (2**attempt) + random.uniform(0.0, 0.25)
                    time.sleep(delay)
                    continue
                raise OmniApiError(
                    f"GET {path} failed due to network error: {exc}",
                    retryable=True,
                ) from exc

            status = response.status_code
            if status < 400:
                data = response.json()
                if not isinstance(data, dict):
                    raise NonRetryableOmniApiError(
                        f"GET {path} returned non-object response.",
                        status_code=status,
                        retryable=False,
                    )
                return data

            if status == 429:
                if attempt < max_rate_limit_retries:
                    delay = (2**attempt) + random.uniform(0.0, 0.5)
                    logger.warning(
                        "Omni rate limit hit for %s. Retrying in %.2fs (attempt %d/%d).",
                        path,
                        delay,
                        attempt + 1,
                        max_rate_limit_retries,
                    )
                    time.sleep(delay)
                    continue
                raise OmniApiError(
                    f"GET {path} rate-limited after retries: {status}",
                    status_code=status,
                    retryable=True,
                )

            if 500 <= status < 600:
                if attempt < max_server_error_retries:
                    delay = (2**attempt) + random.uniform(0.0, 0.25)
                    time.sleep(delay)
                    continue
                raise OmniApiError(
                    f"GET {path} failed after server retries: {status}",
                    status_code=status,
                    retryable=True,
                )

            raise NonRetryableOmniApiError(
                f"GET {path} failed: {status}",
                status_code=status,
                retryable=False,
            )

        raise OmniApiError(f"GET {path} failed unexpectedly.", retryable=True)

    def list_connections(self) -> list[dict[str, Any]]:
        data = self._get_json("/v1/connections")
        return data.get("connections", []) or []

    def list_models(self, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size}
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/v1/models", params=params)

    def list_folders(self, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "include": "labels,_count"}
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/v1/folders", params=params)

    def list_documents(self, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "include": "labels,_count"}
        if cursor:
            params["cursor"] = cursor
        return self._get_json("/v1/documents", params=params)

    def get_model_yaml(self, model_id: str, mode: str = "combined") -> dict[str, Any]:
        return self._get_json(f"/v1/models/{model_id}/yaml", params={"mode": mode})

    def get_document(self, identifier: str) -> dict[str, Any]:
        return self._get_json(f"/v1/documents/{identifier}")

    @staticmethod
    def _paginate(response: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        records = response.get("records", []) or []
        page_info = response.get("pageInfo", {}) or {}
        has_next = bool(page_info.get("hasNextPage"))
        next_cursor = page_info.get("nextCursor")
        return records, (next_cursor if has_next else None)

    def _collect_paginated(
        self,
        list_fn,
        page_size: int,
        max_pages: int | None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        page = 0
        while True:
            response = list_fn(page_size=page_size, cursor=cursor)
            records, cursor = self._paginate(response)
            rows.extend(records)
            page += 1
            if not cursor:
                break
            if max_pages is not None and page >= max_pages:
                break
        return rows

    def _fetch_topics_for_model(self, model: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch and parse topics from a single model's YAML. Returns [] on any error."""
        model_id = model.get("id")
        if not model_id:
            return []
        try:
            payload = self.get_model_yaml(model_id, mode="combined")
        except Exception:
            return []
        topics: list[dict[str, Any]] = []
        files = payload.get("files", {}) or {}
        for file_name, file_content in files.items():
            if not file_name.endswith(".topic"):
                continue
            try:
                parsed = yaml.safe_load(file_content) or {}
            except yaml.YAMLError:
                continue
            # Omni topic YAML has no "name" field; derive it from the filename stem.
            topic_name = parsed.get("name") or file_name.removesuffix(".topic")
            if not topic_name:
                continue
            topics.append(
                {
                    "modelId": model_id,
                    "name": topic_name,
                    "label": parsed.get("label"),
                    "baseViewName": parsed.get("base_view") or parsed.get("base_view_name"),
                }
            )
        return topics

    def _resolve_document_model_id(self, doc: dict[str, Any]) -> str | None:
        """Fetch document detail to resolve the backing modelId. Returns None on any error."""
        identifier = doc.get("identifier")
        if not identifier:
            return None
        try:
            detail = self.get_document(identifier)
            return detail.get("modelId")
        except Exception:
            return None

    def fetch_snapshot(
        self,
        page_size: int = 50,
        max_pages: int | None = None,
        max_concurrency: int = 10,
    ) -> dict[str, Any]:
        connections = self.list_connections()
        models = self._collect_paginated(self.list_models, page_size, max_pages)
        folders = self._collect_paginated(self.list_folders, page_size, max_pages)
        documents = self._collect_paginated(self.list_documents, page_size, max_pages)

        # Fetch model YAMLs and document details concurrently in a shared pool.
        # Both batches are submitted together so they overlap in flight.
        topics: list[dict[str, Any]] = []
        document_model_ids: set[str] = set()
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            model_futures = [executor.submit(self._fetch_topics_for_model, m) for m in models]
            doc_futures = [executor.submit(self._resolve_document_model_id, d) for d in documents]
            for future in model_futures:
                topics.extend(future.result())
            for future in doc_futures:
                model_id = future.result()
                if model_id:
                    document_model_ids.add(model_id)

        for model in models:
            model["updatedAt"] = _parse_dt(model.get("updatedAt"))
        for doc in documents:
            doc["updatedAt"] = _parse_dt(doc.get("updatedAt"))

        return {
            "connections": connections,
            "models": models,
            "folders": folders,
            "documents": documents,
            "topics": topics,
            "document_model_ids": document_model_ids,
        }
