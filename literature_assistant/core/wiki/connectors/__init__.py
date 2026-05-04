from __future__ import annotations

from literature_assistant.core.wiki.connectors.base import (
    ConnectorFieldSpec,
    ConnectorPermissionError,
    ConnectorScanReport,
    ConnectorSpec,
    ConnectorSource,
    ensure_path_within_allowed_roots,
    format_connector_source_id,
    path_to_safe_relative_string,
    sanitize_connector_error,
)
from literature_assistant.core.wiki.connectors.endnote import ENDNOTE_CONNECTOR_SPEC, get_endnote_connector_spec
from literature_assistant.core.wiki.connectors.markdown import MarkdownConnector
from literature_assistant.core.wiki.connectors.pdf_folder import PdfFolderConnector
from literature_assistant.core.wiki.connectors.zotero import ZOTERO_CONNECTOR_SPEC, get_zotero_connector_spec

__all__ = [
    "ConnectorFieldSpec",
    "ConnectorPermissionError",
    "ConnectorScanReport",
    "ConnectorSpec",
    "ConnectorSource",
    "ENDNOTE_CONNECTOR_SPEC",
    "MarkdownConnector",
    "PdfFolderConnector",
    "ZOTERO_CONNECTOR_SPEC",
    "ensure_path_within_allowed_roots",
    "format_connector_source_id",
    "get_endnote_connector_spec",
    "get_zotero_connector_spec",
    "path_to_safe_relative_string",
    "sanitize_connector_error",
]
