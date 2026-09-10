"""Shared result boundary for public typed Designer skill tools."""

from __future__ import annotations

import sys
from typing import Any, Callable

from dcc_mcp_core.skill import skill_error, skill_success

from .graph_authoring import GraphAuthoringError


def typed_result(message: str, operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any):
    try:
        context = operation(*args, **kwargs)
    except GraphAuthoringError as exc:
        return skill_error(str(exc), exc.code)
    except BaseException as exc:  # SDK APIException derives directly from BaseException.
        sdk_error = getattr(sys.modules.get("sd.api.apiexception"), "APIException", None)
        if not isinstance(exc, Exception) and (sdk_error is None or not isinstance(exc, sdk_error)):
            raise  # Preserve cancellation, KeyboardInterrupt and SystemExit.
        return skill_error("Designer API operation failed", type(exc).__name__)
    return skill_success(message, **context)
