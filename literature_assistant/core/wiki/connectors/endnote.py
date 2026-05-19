from __future__ import annotations

from literature_assistant.core.wiki.connectors.base import ConnectorFieldSpec, ConnectorSpec


ENDNOTE_CONNECTOR_SPEC = ConnectorSpec(
    namespace="endnote",
    display_name="EndNote",
    root_hint=".enl file path plus sibling .Data directory",
    readable_fields=(
        ConnectorFieldSpec("record_id", "str", required=True),
        ConnectorFieldSpec("title", "str", required=True),
        ConnectorFieldSpec("authors", "list[str]"),
        ConnectorFieldSpec("year", "str | None"),
        ConnectorFieldSpec("journal", "str | None"),
        ConnectorFieldSpec("doi", "str | None"),
        ConnectorFieldSpec("url", "str | None"),
        ConnectorFieldSpec("abstract", "str | None", privacy="user_or_publisher_text"),
        ConnectorFieldSpec("keywords", "list[str]"),
        ConnectorFieldSpec("research_notes", "str | None", privacy="user_note"),
        ConnectorFieldSpec("attachment_relative_paths", "list[str]", privacy="relative_local_path"),
        ConnectorFieldSpec("database_generation", "sdb | rdb | tdb | pdf_only | unknown"),
    ),
    supports_content_read=False,
)


def get_endnote_connector_spec() -> ConnectorSpec:
    """Return the spec-only EndNote connector contract.

    The function does not read ``.enl``/``.Data`` files; it only documents the
    read-only fields a later implementation may expose.
    """

    return ENDNOTE_CONNECTOR_SPEC
