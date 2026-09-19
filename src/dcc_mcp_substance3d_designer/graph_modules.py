"""Read-only inventory of the Designer node modules that back built-in plugins.

Designer exposes every built-in node type through the graph's definition
inventory. This module groups those definitions into modules (the namespace that
owns them) and reports them with a bounded page, so an Agent can discover which
plugin surface a given Designer build actually provides before trying to use it.

Everything here is read-only. Probing a host API uses ``getattr`` and reports the
result; it never imports or invokes anything that could mutate the session.
"""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, graph_identity, page

_MODULE_SEPARATOR = "::"


def module_of(definition_id: str) -> str:
    """Return the owning module namespace for a node definition id.

    ``sbs::compositing::blur`` -> ``sbs::compositing``. A definition without a
    namespace is reported under ``<root>`` rather than being dropped.
    """
    segments = [segment for segment in str(definition_id).split(_MODULE_SEPARATOR) if segment]
    if len(segments) < 2:
        return "<root>"
    return _MODULE_SEPARATOR.join(segments[:2])


def _definitions(graph: Any):
    return list(api.items(graph.getNodeDefinitions()))


def _row(definition: Any) -> dict[str, Any]:
    return {
        "type_id": str(definition.getId()),
        "label": str(definition.getLabel() or ""),
        "module": module_of(definition.getId()),
    }


def _matches(definition: Any, query: str, only_module: str | None) -> bool:
    if only_module is not None and module_of(definition.getId()) != only_module:
        return False
    if not query:
        return True
    haystack = str(definition.getId()) + " " + str(definition.getLabel() or "")
    return query.casefold() in haystack.casefold()


def list_node_modules(query: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Report the node modules available to the active graph, with counts."""
    page([], offset, limit)
    if not isinstance(query, str) or len(query) > 128:
        raise api.GraphAuthoringError("query must contain at most 128 characters", "INVALID_QUERY")
    graph = checked_graph()
    counts: dict[str, int] = {}
    for definition in _definitions(graph):
        if not _matches(definition, query, None):
            continue
        module = module_of(definition.getId())
        counts[module] = counts.get(module, 0) + 1
    rows = [{"module": module, "definition_count": count} for module, count in sorted(counts.items())]
    return {"graph_uid": graph_identity(graph), **page(rows, offset, limit)}


def describe_node_module(module: str, query: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """List the node definitions owned by one module namespace."""
    page([], offset, limit)
    if not isinstance(module, str) or not module.strip():
        raise api.GraphAuthoringError("module must be a nonempty namespace", "INVALID_MODULE")
    if not isinstance(query, str) or len(query) > 128:
        raise api.GraphAuthoringError("query must contain at most 128 characters", "INVALID_QUERY")
    resolved_module = module.strip()
    graph = checked_graph()
    rows = [_row(definition) for definition in _definitions(graph) if _matches(definition, query, resolved_module)]
    if not rows:
        raise api.GraphAuthoringError(
            f"Module '{resolved_module}' has no matching node definitions", "MODULE_NOT_FOUND"
        )
    return {
        "graph_uid": graph_identity(graph),
        "module": resolved_module,
        **page(rows, offset, limit),
    }


def module_capabilities() -> dict[str, Any]:
    """Probe which module/plugin manager APIs this Designer build advertises.

    Probing is read-only: it only inspects attributes. A missing API is reported
    as unavailable instead of raising, because absence is an expected result on
    some builds.
    """
    application = api.application()
    probes = {
        "module_manager": "getModuleMgr",
        "package_manager": "getPackageMgr",
        "app_interop_manager": "getAppInteropMgr",
        "qt_ui_manager": "getQtForPythonUIMgr",
    }
    available = {}
    for name, method in probes.items():
        available[name] = callable(getattr(application, method, None))

    sdk_modules = {}
    for name in ("sd.api.sdmodule", "sd.api.sddefinition"):
        try:
            __import__(name)
        except ImportError:
            sdk_modules[name] = False
        else:
            sdk_modules[name] = True

    manager = getattr(application, "getModuleMgr", None)
    loaded = []
    if callable(manager):
        try:
            loaded = sorted(
                {str(api.value(item, "getName", "getIdentifier") or "") for item in api.items(manager().getModules())}
                - {""}
            )
        except Exception:  # noqa: BLE001 - a probe must not fail the tool.
            # Never swallow KeyboardInterrupt or SystemExit.
            loaded = []

    return {
        "application_apis": available,
        "sdk_modules": sdk_modules,
        "module_manager_modules": loaded,
        "probe_note": (
            "Read-only attribute probe. The graph definition inventory is the "
            "authoritative plugin surface; the module manager is reported when present."
        ),
    }
