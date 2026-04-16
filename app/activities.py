import os
from pathlib import Path
from typing import Any, Dict

from app.client import NonRetryableOmniApiError, OmniApiError
from app.handler import HandlerClass
from app.transformer import OmniMetadataTransformer
from application_sdk.activities import ActivitiesInterface
from application_sdk.constants import TEMPORARY_PATH
from application_sdk.io.json import JsonFileWriter
from application_sdk.observability.logger_adaptor import get_logger
from temporalio import activity
from temporalio.exceptions import ApplicationError

logger = get_logger(__name__)
activity.logger = logger


class ActivitiesClass(ActivitiesInterface):
    def __init__(self, handler: HandlerClass | None = None):
        self.handler = handler or HandlerClass()

    @activity.defn
    async def get_workflow_args(
        self, workflow_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        base_args = await super().get_workflow_args(workflow_config)

        payload = base_args.get("payload", {}) or {}
        metadata_in = base_args.get("metadata", {}) or {}
        credentials_in = base_args.get("credentials", {}) or {}

        tenant_id = payload.get("tenant_id") or metadata_in.get("tenant_id") or "omni"
        page_size_raw = payload.get("page_size") or metadata_in.get("page_size") or 50
        max_pages_raw = payload.get("max_pages") or metadata_in.get("max_pages")
        timeout_raw = payload.get("timeout_seconds") or metadata_in.get("timeout_seconds") or 30
        max_concurrency_raw = payload.get("max_concurrency") or metadata_in.get("max_concurrency") or 10

        def _to_int(value: Any, default: int | None = None) -> int | None:
            if value in (None, "", "null"):
                return default
            return int(value)

        metadata: dict[str, Any] = {
            "page_size": _to_int(page_size_raw, 50),
            "max_pages": _to_int(max_pages_raw, None),
            "tenant_id": tenant_id,
            "output_file": payload.get("output_file") or metadata_in.get("output_file") or "omni_entities.ndjson",
            "save_output_local": bool(
                payload.get("save_output_local", metadata_in.get("save_output_local", False))
            ),
            "max_concurrency": _to_int(max_concurrency_raw, 10),
        }

        credentials = {
            "omni_base_url": (
                payload.get("omni_base_url")
                or credentials_in.get("omni_base_url")
                or metadata_in.get("omni_base_url")
            ),
            "omni_api_token": (
                payload.get("omni_api_token")
                or credentials_in.get("omni_api_token")
                or metadata_in.get("omni_api_token")
            ),
            "verify_ssl": bool(
                payload.get("verify_ssl", credentials_in.get("verify_ssl", metadata_in.get("verify_ssl", True)))
            ),
            "timeout_seconds": _to_int(timeout_raw, 30),
        }

        # output_path is set by the SDK's get_workflow_args; fall back to a local temp dir.
        output_path = base_args.get("output_path") or os.path.join(
            TEMPORARY_PATH,
            base_args.get("workflow_id", "omni-extraction"),
            base_args.get("workflow_run_id", "local-run"),
        )

        return {
            "workflow_id": base_args.get("workflow_id", "omni-extraction"),
            "workflow_run_id": base_args.get("workflow_run_id", "local-run"),
            "output_path": output_path,
            "credentials": credentials,
            "metadata": metadata,
        }

    @activity.defn
    async def extract_and_transform_metadata(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            await self.handler.load(credentials=args["credentials"])
            snapshot = await self.handler.fetch_metadata(metadata=args["metadata"])
        except NonRetryableOmniApiError as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc
        except OmniApiError as exc:
            raise ApplicationError(str(exc), non_retryable=not exc.retryable) from exc

        transformer = OmniMetadataTransformer(tenant_id=args["metadata"]["tenant_id"])
        entities = transformer.transform(
            snapshot=snapshot,
            workflow_id=args.get("workflow_id", "omni-extraction"),
            workflow_run_id=args.get("workflow_run_id", "local-run"),
        )

        # Write entities via the SDK writer, which uploads to the Atlan object store
        # (when ENABLE_ATLAN_UPLOAD=true in production) or writes locally (in dev).
        writer = JsonFileWriter(
            path=args["output_path"],
            typename="omni_entities",
            retain_local_copy=args["metadata"].get("save_output_local", False),
        )
        await writer.write(entities)
        stats = await writer.close()

        # Optional additional local debug write at the user-specified output_file path.
        if args["metadata"].get("save_output_local"):
            import json
            output_path_local = Path(args["metadata"]["output_file"])
            with output_path_local.open("w", encoding="utf-8") as handle:
                for entity in entities:
                    handle.write(json.dumps(entity))
                    handle.write("\n")

        return {
            "success": True,
            "entity_count": stats.total_record_count,
            "output_path": args["output_path"],
            "snapshot_counts": {
                "connections": len(snapshot.get("connections", [])),
                "models": len(snapshot.get("models", [])),
                "topics": len(snapshot.get("topics", [])),
                "folders": len(snapshot.get("folders", [])),
                "documents": len(snapshot.get("documents", [])),
            },
        }
