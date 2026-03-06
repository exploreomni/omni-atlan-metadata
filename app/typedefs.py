"""Custom entity type definitions for the Omni connector.

Defines the six Omni entity types and a registration function that POSTs them
to Atlan's Atlas typedef API. Registration is idempotent — types that already
exist are silently skipped.
"""

from __future__ import annotations

from pyatlan.model.typedef import AttributeDef, EntityDef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(name: str) -> AttributeDef:
    """Return a nullable single-value string AttributeDef."""
    return AttributeDef(
        name=name,
        type_name="string",
        is_optional=True,
        cardinality="SINGLE",
    )


# Sync-tracking attributes added to every entity type
_SYNC_ATTRS: list[AttributeDef] = [
    _str("last_sync_workflow_name"),
    _str("last_sync_run"),
    _str("connector_name"),
]

# ---------------------------------------------------------------------------
# Entity type definitions
# ---------------------------------------------------------------------------

ENTITY_DEFS: list[EntityDef] = [
    EntityDef(
        name="omni_connection",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniId"),
            _str("dialect"),
            _str("database"),
            *_SYNC_ATTRS,
        ],
    ),
    EntityDef(
        name="omni_model",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniId"),
            _str("modelKind"),
            _str("updatedAt"),
            _str("connectionQualifiedName"),
            _str("baseModelQualifiedName"),
            *_SYNC_ATTRS,
        ],
    ),
    EntityDef(
        name="omni_topic",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniName"),
            _str("baseViewName"),
            _str("modelQualifiedName"),
            *_SYNC_ATTRS,
        ],
    ),
    EntityDef(
        name="omni_folder",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniId"),
            _str("path"),
            _str("scope"),
            _str("ownerId"),
            _str("ownerName"),
            *_SYNC_ATTRS,
        ],
    ),
    EntityDef(
        name="omni_dashboard",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniId"),
            _str("scope"),
            _str("url"),
            _str("updatedAt"),
            _str("sourceType"),
            _str("ownerId"),
            _str("ownerName"),
            _str("folderPath"),
            _str("connectionQualifiedName"),
            _str("folderQualifiedName"),
            *_SYNC_ATTRS,
        ],
    ),
    EntityDef(
        name="omni_workbook",
        super_types=["Asset"],
        attribute_defs=[
            _str("omniId"),
            _str("scope"),
            _str("url"),
            _str("updatedAt"),
            _str("sourceType"),
            _str("ownerId"),
            _str("ownerName"),
            _str("folderPath"),
            _str("connectionQualifiedName"),
            _str("folderQualifiedName"),
            *_SYNC_ATTRS,
        ],
    ),
]

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_typedefs(skip_existing: bool = True) -> None:
    """Register Omni custom entity type definitions with Atlan.

    Iterates over ENTITY_DEFS and creates each type via the pyatlan client.
    Types that already exist are skipped (idempotent). Requires ATLAN_BASE_URL
    and ATLAN_API_KEY (or ATLAN_API_TOKEN_GUID) to be set in the environment.

    Args:
        skip_existing: When True, log a warning and continue if a type already
            exists or creation fails. When False, raise on any error.
    """
    from application_sdk.clients.atlan import get_client
    from application_sdk.observability.logger_adaptor import get_logger

    log = get_logger(__name__)
    client = get_client()

    for entity_def in ENTITY_DEFS:
        type_name = entity_def.name
        try:
            client.typedef.get_by_name(type_name)
            log.info("Omni typedef '%s' already registered, skipping.", type_name)
        except Exception:
            # Type not found — attempt to create it
            try:
                client.typedef.create(entity_def)
                log.info("Registered Omni typedef '%s'.", type_name)
            except Exception as exc:
                if skip_existing:
                    log.warning(
                        "Failed to register Omni typedef '%s': %s", type_name, exc
                    )
                else:
                    raise
