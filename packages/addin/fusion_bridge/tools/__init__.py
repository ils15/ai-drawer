"""Tool modules grouped by domain.

Every handler takes a validated arguments dict and returns an MCP response
envelope ``{"content": [{"type": "text", "text": ...}], "isError": bool}`` --
the same shape as ``viewport.py`` and ``selection.py``.  Handlers always run
on the Fusion main thread (the server reaches them through ``dispatch.py``'s
queue), so they may touch ``adsk`` objects directly.

``adsk`` members are resolved at *call* time (``adsk.fusion.Design.cast``),
never bound with ``from ... import ...``, so a test double installed after
this module is imported is still picked up.
"""

import adsk.core
import adsk.fusion

from ..dispatch import get_app
from ..value_builders import error_result, safe_get, success_result

__all__ = [
    "active_app",
    "active_design",
    "active_document",
    "active_product",
    "error_result",
    "optional_bool",
    "optional_str",
    "require",
    "safe_get",
    "success_result",
]


def active_app():
    """Return the Fusion Application singleton."""
    return get_app()


def active_product():
    """Return the active product, or None when no document is open."""
    return safe_get(active_app(), "activeProduct")


def active_design():
    """Return the active design, or None (also for non-design products)."""
    product = active_product()
    if product is None:
        return None
    try:
        return adsk.fusion.Design.cast(product)
    except Exception:
        return None


def active_document():
    """Return the active document, or None."""
    return safe_get(active_app(), "activeDocument")


def require(arguments, *names):
    """Return the named arguments, raising ValueError if any are missing/empty."""
    missing = [name for name in names if not arguments.get(name)]
    if missing:
        raise ValueError(f"missing required argument(s): {', '.join(missing)}")
    return {name: arguments[name] for name in names}


def optional_str(arguments, name):
    """Return a trimmed optional string argument, or None."""
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip() or None


def optional_bool(arguments, name):
    """Return an optional boolean argument, or None."""
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def bool_or_none(value):
    """Coerce an SDK boolean-ish value, or None when unavailable."""
    return value if isinstance(value, bool) else None
