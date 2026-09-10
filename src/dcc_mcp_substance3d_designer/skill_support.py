"""Shared result boundary for public typed Designer skill tools."""

from __future__ import annotations

from typing import Any, Callable

from dcc_mcp_core.skill import skill_error, skill_success

from .graph_authoring import GraphAuthoringError


def typed_result(message: str, operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any):
    try:
        context = operation(*args, **kwargs)
    except GraphAuthoringError as exc:
        return skill_error(str(exc), exc.code)
    except BaseException as exc:
        # Adobe's APIException inherits BaseException, not Exception. Keep
        # KeyboardInterrupt/SystemExit and unrelated BaseExceptions observable.
        try:
            from sd.api.apiexception import APIException
        except ImportError:
            APIException = ()
        if isinstance(exc, APIException):
            code = getattr(getattr(exc, "mErrorCode", None), "name", "Unknown")
            return skill_error("Designer SDK operation failed", f"SDK_API_ERROR:{code}")
        if isinstance(exc, Exception):
            return skill_error("Designer API operation failed", type(exc).__name__)
        raise
    return skill_success(message, **context)
