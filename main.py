"""Main entrypoint for the Omni connector application."""

import asyncio

from app.activities import ActivitiesClass
from app.client import ClientClass
from app.handler import HandlerClass
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

        await application.start_worker()
        await application.setup_server(workflow_class=WorkflowClass, has_configmap=True)
        await application.start_server()

    except ApiError:
        logger.error(f"{ApiError.SERVER_START_ERROR}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
