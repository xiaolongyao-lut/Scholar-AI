from __future__ import annotations

from literature_assistant.core.wiki.connectors.base import ConnectorFieldSpec, ConnectorSpec


ZOTERO_CONNECTOR_SPEC = ConnectorSpec(
    namespace="zotero",
    display_name="Zotero",
    root_hint="zotero.sqlite path plus storage attachment root",
    readable_fields=(
        ConnectorFieldSpec("item_key", "str", required=True),
        ConnectorFieldSpec("title", "str", required=True),
        ConnectorFieldSpec("creators", "list[dict[str, str]]"),
        ConnectorFieldSpec("date", "str | None"),
        ConnectorFieldSpec("publication_title", "str | None"),
        ConnectorFieldSpec("doi", "str | None"),
        ConnectorFieldSpec("url", "str | None"),
        ConnectorFieldSpec("abstract_note", "str | None", privacy="user_or_publisher_text"),
        ConnectorFieldSpec("tags", "list[str]"),
        ConnectorFieldSpec("notes", "list[str]", privacy="user_note"),
        ConnectorFieldSpec("annotations", "list[dict[str, object]]", privacy="user_note"),
        ConnectorFieldSpec("attachment_relative_paths", "list[str]", privacy="relative_local_path"),
    ),
    supports_content_read=False,
)


def get_zotero_connector_spec() -> ConnectorSpec:
    """Return the spec-only Zotero connector contract.

    The function does not read ``zotero.sqlite`` or attachment storage; it only
    documents the fields a later read-only implementation may expose.
    """

    return ZOTERO_CONNECTOR_SPEC
