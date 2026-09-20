"""Canonical error kinds and the structured MCP error envelope.

Every failure the bridge can produce is reported with the same envelope shape
as a success: ``content[0].text`` is JSON.  An error carries three fields an
LLM client can branch on:

* ``error_kind`` -- one stable name from :data:`ERROR_KINDS`, so a client can
  retry, rephrase, or surface guidance without parsing prose;
* ``message`` -- what went wrong, in user-facing terms;
* ``hint`` -- one actionable next step that usually resolves it.

Stack traces, exception reprs, file paths and internal identifiers never enter
the envelope; the detail stays in the add-in log.  Keeping the taxonomy in a
single module is what stops the add-in and its consumers from drifting apart
on error names -- a kind added here is the only place a new failure category
is allowed to be introduced.
"""

import json

# ── The taxonomy ──────────────────────────────────────────────────────────

ERROR_KINDS = (
    "no_active_document",      # no design/document is open for a tool that needs one
    "missing_argument",        # a required argument is absent or empty
    "invalid_value",           # an argument is present but fails validation
    "parameter_already_exists",  # a user parameter of that name already exists
    "parameter_not_found",     # no parameter matches the requested name
    "invalid_expression",      # Fusion rejected a parameter expression/unit
    "unsupported_operation",   # this Fusion build cannot do what was asked
    "not_found",               # a named/paths resource the caller asked for is absent
    "network_failure",         # a remote lookup (Autodesk docs) could not complete
    "io_failure",              # a local read/write of a file failed
    "no_export_target",        # nothing exportable is active (no design/manager)
    "internal",                # anything else; detail is logged, not returned
)

_KIND_INDEX = frozenset(ERROR_KINDS)

# Default user-facing messages; every kind has one so a call site can omit the
# message and still return something useful.
DEFAULT_MESSAGES = {
    "no_active_document": "No active Fusion document is open for this operation.",
    "missing_argument": "A required argument is missing or empty.",
    "invalid_value": "One of the provided argument values is not valid.",
    "parameter_already_exists": "A parameter with that name already exists in the active design.",
    "parameter_not_found": "No parameter with that name exists in the active design.",
    "invalid_expression": "Fusion rejected the parameter expression or unit.",
    "unsupported_operation": "This Fusion build does not support the requested operation.",
    "not_found": "The requested document, name, or resource was not found.",
    "network_failure": "A network lookup failed and could not be completed.",
    "io_failure": "Reading or writing a file failed.",
    "no_export_target": "No active design is available to export.",
    "internal": "An internal error occurred while handling this tool.",
}

# Actionable hints; never empty, always something a user or LLM can *do*.
DEFAULT_HINTS = {
    "no_active_document": "Open or create a Fusion design document first, then retry the call.",
    "missing_argument": "Provide every required argument listed in the tool schema and retry.",
    "invalid_value": "Check the value's type, range, and allowed members against the tool schema.",
    "parameter_already_exists": "Pick a unique name, or call modify_parameter to change the existing one.",
    "parameter_not_found": "Call list_parameters to see the exact names; match spelling and case.",
    "invalid_expression": "Use a Fusion expression such as '25 mm' or 'width / 2' with a supported unit.",
    "unsupported_operation": "Try an alternative the build supports, or update Fusion and retry.",
    "not_found": "Check the name or path spelling; call list_documents for what is currently open.",
    "network_failure": "Retry after a moment; if it persists, verify connectivity to Autodesk docs.",
    "io_failure": "Check the target folder is writable and the file is not locked, then retry.",
    "no_export_target": "Open or create a design document so an export manager exists, then retry.",
    "internal": "Retry once; if it repeats, restart the add-in. The cause is in the add-in log.",
}

# ── The envelope ──────────────────────────────────────────────────────────


def structured_error(kind, message=None, hint=None):
    """Build an MCP error envelope for *kind*.

    ``content[0].text`` is JSON (like ``success_result``), not prose, so a
    client can parse ``error_kind`` deterministically.  ``message`` and
    ``hint`` fall back to the per-kind defaults, which are never empty, so a
    call site that only knows the kind still returns a useful error.

    An unrecognized *kind* degrades to ``"internal"`` rather than raising: a
    bad error name must never become a second failure while reporting one.
    """
    if kind not in _KIND_INDEX:
        kind = "internal"
    payload = {
        "error_kind": kind,
        "message": str(message) if message else DEFAULT_MESSAGES[kind],
        "hint": str(hint) if hint else DEFAULT_HINTS[kind],
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "isError": True,
    }


def internal_error(exc=None, context="tool"):
    """Return a generic internal-error envelope, logging the real cause.

    Catch-alls use this so exception detail reaches the log -- where a human
    can read it -- and never the response content, where an LLM or an attacker
    could read it.  Logging is best-effort: a failure to log must not prevent
    a clean error from being returned.
    """
    if exc is not None:
        try:
            from .dispatch import log

            log(f"[{context}] failed: {exc!r}")
        except Exception:  # best-effort logging; never break error reporting
            pass
    return structured_error("internal")
