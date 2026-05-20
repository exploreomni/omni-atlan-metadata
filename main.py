"""Main entrypoint for the Omni connector application."""

import asyncio
import os

from app.activities import ActivitiesClass
from app.client import ClientClass
from app.handler import HandlerClass
from app.typedefs import register_typedefs
from app.workflow import WorkflowClass
from application_sdk.application import BaseApplication
from application_sdk.common.error_codes import ApiError
from application_sdk.constants import APPLICATION_NAME
from application_sdk.observability.decorators.observability_decorator import (
    observability,
)
from application_sdk.observability.logger_adaptor import get_logger
from application_sdk.observability.metrics_adaptor import get_metrics
from application_sdk.observability.traces_adaptor import get_traces

logger = get_logger(__name__)
metrics = get_metrics()
traces = get_traces()


@observability(logger=logger, metrics=metrics, traces=traces)
async def main():
    try:
        logger.info("Starting Omni connector application")
        application = BaseApplication(
            name=APPLICATION_NAME, client_class=ClientClass, handler_class=HandlerClass
        )

        await application.setup_workflow(
            workflow_and_activities_classes=[(WorkflowClass, ActivitiesClass)],
        )

        try:
            register_typedefs()
        except Exception:
            # Surface as ERROR (not WARN): if typedefs are unregistered, the
            # ingestion side cannot accept the entities this app emits.
            logger.error(
                "Failed to register Omni typedefs. Entities emitted by this run "
                "will not be ingestible until typedefs exist on the target tenant. "
                "Set ATLAN_BASE_URL and ATLAN_API_KEY for typedef registration.",
                exc_info=True,
            )

        # ui_enabled is False in production — the workflow form is served from
        # marketplace-packages, not from this container, and the SDK's static
        # mount would otherwise crash-loop on an empty frontend/static/ dir.
        # For local development, set OMNI_LOCAL_UI=1 to mount the form on
        # http://localhost:8000 so the dry-run flow is interactive.
        ui_enabled = os.environ.get("OMNI_LOCAL_UI", "").lower() in ("1", "true", "yes")
        await application.start(
            workflow_class=WorkflowClass,
            has_configmap=True,
            ui_enabled=ui_enabled,
        )

    except ApiError:
        logger.error(f"{ApiError.SERVER_START_ERROR}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
