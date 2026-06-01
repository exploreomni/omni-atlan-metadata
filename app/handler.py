import json
from pathlib import Path
from typing import Any, Dict

from application_sdk.handlers import HandlerInterface
from application_sdk.observability.logger_adaptor import get_logger

from .client import ClientClass

logger = get_logger(__name__)


class HandlerClass(HandlerInterface):
    def __init__(self, client: ClientClass | None = None):
        self.client = client or ClientClass()

    async def load(self, *args: Any, **kwargs: Any) -> None:
        # Server path: args[0] = body.model_dump() = {"credentials": {...}, "metadata": {...}}
        # Activities path: kwargs = {"credentials": {...}, ...}
        credentials = kwargs.get("credentials") or {}
        if args and isinstance(args[0], dict):
            credentials = args[0].get("credentials") or args[0]
        self.client.load_credentials(credentials)

    async def test_auth(self, *args: Any, **kwargs: Any) -> bool:
        # load() has already initialized the client with credentials.
        self.client.list_connections()
        return True

    async def preflight_check(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # Server path: args[0] = body.model_dump() = {"credentials": {...}, "metadata": {...}}
        # Activities path: kwargs = {"credentials": {...}, "metadata": {...}}
        data = args[0] if args and isinstance(args[0], dict) else {}
        metadata = kwargs.get("metadata") or data.get("metadata") or {}
        self.client.list_connections()
        return {
            "success": True,
            "message": "Omni connection validated.",
            "data": {
                "page_size": metadata.get("page_size", 50),
                "max_pages": metadata.get("max_pages"),
            },
        }

    async def fetch_metadata(self, *args: Any, **kwargs: Any) -> Any:
        metadata = kwargs.get("metadata") or {}
        page_size = int(metadata.get("page_size", 50))
        max_pages = metadata.get("max_pages")
        max_pages = int(max_pages) if max_pages not in (None, "", "null") else None
        max_concurrency = int(metadata.get("max_concurrency", 10))
        return self.client.fetch_snapshot(
            page_size=page_size,
            max_pages=max_pages,
            max_concurrency=max_concurrency,
        )

    @staticmethod
    async def get_configmap(config_map_id: str) -> Dict[str, Any]:
        workflow_json_path = Path().cwd() / "app" / "frontend" / "workflow.json"
        with open(workflow_json_path) as f:
            return json.load(f)
