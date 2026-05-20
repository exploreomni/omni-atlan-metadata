"""Tests for app/activities.py — focuses on get_workflow_args config normalization."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_EPOCH = "1747156800000"


def _make_base_args(overrides: dict | None = None) -> dict:
    """Simulate what the SDK's get_workflow_args returns from the state store.

    `connection_epoch_ms` is required by the activity; injected by default so
    individual tests don't need to set it unless they're exercising validation.
    """
    base = {
        "workflow_id": "wf-123",
        "workflow_run_id": "run-456",
        "output_path": "./local/tmp/wf-123/run-456",
        "output_prefix": "./local/tmp/",
        "payload": {"connection_epoch_ms": DEFAULT_EPOCH},
        "metadata": {},
        "credentials": {},
    }
    if overrides:
        # Merge payload overrides instead of clobbering so callers don't lose
        # the default connection_epoch_ms.
        payload_override = overrides.pop("payload", None)
        base.update(overrides)
        if payload_override is not None:
            base["payload"] = {**base["payload"], **payload_override}
    return base


async def _call_get_workflow_args(workflow_config: dict, base_args: dict) -> dict:
    """Invoke ActivitiesClass.get_workflow_args with a mocked super() call."""
    from app.activities import ActivitiesClass

    activities = ActivitiesClass()

    with patch.object(
        ActivitiesClass.__bases__[0],
        "get_workflow_args",
        new=AsyncMock(return_value=base_args),
    ):
        return await activities.get_workflow_args(workflow_config)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_defaults_when_state_empty():
    result = await _call_get_workflow_args({}, _make_base_args())
    assert result["metadata"]["connection_epoch_ms"] == DEFAULT_EPOCH
    assert result["metadata"]["page_size"] == 50
    assert result["metadata"]["max_pages"] is None
    assert result["metadata"]["save_output_local"] is False
    assert result["credentials"]["verify_ssl"] is True
    assert result["credentials"]["timeout_seconds"] == 30


@pytest.mark.asyncio
async def test_missing_connection_epoch_ms_raises():
    from temporalio.exceptions import ApplicationError

    base = _make_base_args()
    base["payload"].pop("connection_epoch_ms")
    with pytest.raises(ApplicationError, match="connection_epoch_ms"):
        await _call_get_workflow_args({}, base)


@pytest.mark.asyncio
async def test_non_numeric_connection_epoch_ms_raises():
    from temporalio.exceptions import ApplicationError

    base = _make_base_args({"payload": {"connection_epoch_ms": "not-a-number"}})
    with pytest.raises(ApplicationError, match="connection_epoch_ms"):
        await _call_get_workflow_args({}, base)


# ---------------------------------------------------------------------------
# Values from payload (state store)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reads_credentials_from_payload():
    base = _make_base_args(
        {
            "payload": {
                "omni_base_url": "https://org.omniapp.co/api",
                "omni_api_token": "tok-abc",
                "connection_epoch_ms": "1700000000000",
            }
        }
    )
    result = await _call_get_workflow_args({}, base)
    assert result["credentials"]["omni_base_url"] == "https://org.omniapp.co/api"
    assert result["credentials"]["omni_api_token"] == "tok-abc"
    assert result["metadata"]["connection_epoch_ms"] == "1700000000000"


@pytest.mark.asyncio
async def test_reads_pagination_from_payload():
    base = _make_base_args({"payload": {"page_size": "100", "max_pages": "5"}})
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["page_size"] == 100
    assert result["metadata"]["max_pages"] == 5


@pytest.mark.asyncio
async def test_null_string_max_pages_becomes_none():
    base = _make_base_args({"payload": {"max_pages": "null"}})
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["max_pages"] is None


@pytest.mark.asyncio
async def test_empty_string_max_pages_becomes_none():
    base = _make_base_args({"payload": {"max_pages": ""}})
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["max_pages"] is None


# ---------------------------------------------------------------------------
# Credentials fallback chain: payload > credentials > metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credentials_fallback_to_credentials_key():
    base = _make_base_args(
        {"credentials": {"omni_base_url": "https://fallback.omniapp.co/api", "omni_api_token": "tok-fb"}}
    )
    result = await _call_get_workflow_args({}, base)
    assert result["credentials"]["omni_base_url"] == "https://fallback.omniapp.co/api"


# ---------------------------------------------------------------------------
# output_path propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_path_from_base_args():
    base = _make_base_args({"output_path": "./local/tmp/wf-xyz/run-abc"})
    result = await _call_get_workflow_args({}, base)
    assert result["output_path"] == "./local/tmp/wf-xyz/run-abc"


@pytest.mark.asyncio
async def test_output_path_fallback_when_missing():
    base = _make_base_args()
    base.pop("output_path")
    result = await _call_get_workflow_args({}, base)
    assert "wf-123" in result["output_path"]
    assert "run-456" in result["output_path"]


# ---------------------------------------------------------------------------
# workflow_id / workflow_run_id propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_ids_propagated():
    base = _make_base_args({"workflow_id": "my-wf", "workflow_run_id": "my-run"})
    result = await _call_get_workflow_args({}, base)
    assert result["workflow_id"] == "my-wf"
    assert result["workflow_run_id"] == "my-run"


# ---------------------------------------------------------------------------
# atlan_source_connection_map normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_connection_map_default_empty():
    result = await _call_get_workflow_args({}, _make_base_args())
    assert result["metadata"]["atlan_source_connection_map"] == {}


@pytest.mark.asyncio
async def test_source_connection_map_parses_json_string():
    base = _make_base_args(
        {"payload": {"atlan_source_connection_map": '{"c1": "default/snowflake/1700"}'}}
    )
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["atlan_source_connection_map"] == {
        "c1": "default/snowflake/1700"
    }


@pytest.mark.asyncio
async def test_source_connection_map_accepts_dict():
    base = _make_base_args(
        {"payload": {"atlan_source_connection_map": {"c1": "default/redshift/abc"}}}
    )
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["atlan_source_connection_map"] == {
        "c1": "default/redshift/abc"
    }


@pytest.mark.asyncio
async def test_source_connection_map_invalid_json_yields_empty():
    base = _make_base_args(
        {"payload": {"atlan_source_connection_map": "{not valid json"}}
    )
    result = await _call_get_workflow_args({}, base)
    assert result["metadata"]["atlan_source_connection_map"] == {}
