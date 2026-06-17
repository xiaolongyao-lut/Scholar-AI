"""Literature Assistant MCP Server - Security Foundation."""

__version__ = "0.1.0"

from .audit import AuditLog
from .backend_client import BackendClient
from .policy import PathPolicy
from .redaction import SecretRedactor
from .result import safe_result

__all__ = [
    "AuditLog",
    "BackendClient",
    "PathPolicy",
    "SecretRedactor",
    "safe_result",
]
