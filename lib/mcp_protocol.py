"""Wire-format helpers for the stateless MCP 2026-07-28 revision.

Legacy handshakes deliberately negotiate only LEGACY_PROTOCOL_VERSIONS.
Protocol selection is per request, never cached on an HTTP connection.
"""

import base64
import binascii
import math


MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED_PROTOCOL_VERSIONS = (MODERN_PROTOCOL_VERSION, *LEGACY_PROTOCOL_VERSIONS)
META_PREFIX = "io.modelcontextprotocol/"
CACHEABLE_METHODS = {
    "server/discover", "tools/list", "resources/list",
    "resources/templates/list", "resources/read",
}


def reject_non_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


class ProtocolError(Exception):
    def __init__(self, code, message, *, status=400, data=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.data = data

    def response(self, request_id=None):
        error = {"code": self.code, "message": str(self)}
        if self.data is not None:
            error["data"] = self.data
        response = {"jsonrpc": "2.0", "error": error}
        if type(request_id) in (str, int):
            response["id"] = request_id
        return response


def uses_modern_protocol(payload, headers):
    messages = payload if isinstance(payload, list) else [payload]
    for message in messages:
        if not isinstance(message, dict):
            continue
        params = message.get("params", {})
        meta = params.get("_meta", {}) if isinstance(params, dict) else {}
        if isinstance(meta, dict) and META_PREFIX + "protocolVersion" in meta:
            return True
        if message.get("method") in ("server/discover", "subscriptions/listen"):
            return True
    # A handshake remains a legacy request even if a client attaches its
    # preferred version in a header. Offer a version it can initialize with.
    if (isinstance(payload, dict) and payload.get("method") == "initialize"):
        return False
    version = headers.get("MCP-Protocol-Version")
    return version is not None and version not in LEGACY_PROTOCOL_VERSIONS


def decode_header(value):
    if value is None:
        raise ProtocolError(-32020, "Missing required request header")
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeError, ValueError):
            raise ProtocolError(-32020, "Malformed Base64 request header") from None
    if value != value.strip() or any((ord(c) < 32 and c != "\t") or ord(c) > 126 for c in value):
        raise ProtocolError(-32020, "Invalid characters in request header")
    return value


def validate_modern_request(message, headers):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ProtocolError(-32600, "Expected a single JSON-RPC 2.0 request")
    if not isinstance(message.get("method"), str) or not message["method"]:
        raise ProtocolError(-32600, "Request method must be a nonempty string")
    if type(message.get("id")) not in (str, int):
        raise ProtocolError(-32600, "Request id must be a string or integer")
    if "result" in message or "error" in message:
        raise ProtocolError(-32600, "Clients must not send JSON-RPC responses")
    params = message.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(meta, dict):
        raise ProtocolError(-32602, "params._meta is required")
    version = meta.get(META_PREFIX + "protocolVersion")
    capabilities = meta.get(META_PREFIX + "clientCapabilities")
    if not isinstance(version, str) or not isinstance(capabilities, dict):
        raise ProtocolError(-32602, "_meta requires protocolVersion and clientCapabilities")
    client_info = meta.get(META_PREFIX + "clientInfo")
    if client_info is not None and (
        not isinstance(client_info, dict)
        or not isinstance(client_info.get("name"), str)
        or not isinstance(client_info.get("version"), str)
    ):
        raise ProtocolError(-32602, "clientInfo requires name and version strings")
    expected = {"MCP-Protocol-Version": version, "Mcp-Method": message["method"]}
    if message["method"] in ("tools/call", "resources/read", "prompts/get"):
        key = "uri" if message["method"] == "resources/read" else "name"
        if not isinstance(params.get(key), str):
            raise ProtocolError(-32602, f"params.{key} must be a string")
        expected["Mcp-Name"] = params[key]
    for name, body_value in expected.items():
        values = headers.get_all(name, [])
        if len(values) != 1:
            raise ProtocolError(-32020, f"Missing or repeated {name} header")
        value = decode_header(values[0]) if name == "Mcp-Name" else values[0]
        if name != "Mcp-Name" and any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ProtocolError(-32020, f"Invalid characters in {name} header")
        if value != body_value:
            raise ProtocolError(-32020, f"{name} header does not match request body")
    if version != MODERN_PROTOCOL_VERSION:
        raise ProtocolError(
            -32022, "Unsupported protocol version for stateless requests",
            data={"requested": version, "supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
        )
    return params


def complete_result(result, method, server_info):
    result = dict(result)
    result["resultType"] = "complete"
    result["_meta"] = {**result.get("_meta", {}), META_PREFIX + "serverInfo": dict(server_info)}
    if method in CACHEABLE_METHODS:
        # Conservative defaults: never authorize a shared cache to publish
        # user data, and do not promise freshness beyond this response.
        result["ttlMs"] = 0
        result["cacheScope"] = "private"
    return result


def validate_arguments(value, schema, path="arguments"):
    """Validate the JSON Schema vocabulary used by this add-in's tools.

    Our owned schemas use object/array/scalar types, required properties and
    simple bounds. No remote schemas or references are loaded or evaluated.
    This is not a general-purpose validator for third-party tool schemas.
    """
    types = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: type(v) is bool,
        "integer": lambda v: type(v) is int or (type(v) is float and math.isfinite(v) and v.is_integer()),
        "number": lambda v: type(v) is int or (type(v) is float and math.isfinite(v)),
        "null": lambda v: v is None,
    }
    kind = schema.get("type")
    if kind in types and not types[kind](value):
        return f"{path} must be {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}.{key} is required"
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                error = validate_arguments(item, properties[key], f"{path}.{key}")
                if error:
                    return error
            elif schema.get("additionalProperties") is False:
                return f"{path}.{key} is not allowed"
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            error = validate_arguments(item, schema["items"], f"{path}[{index}]")
            if error:
                return error
    if type(value) in (int, float):
        for bound, compare in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b)):
            if bound in schema and compare(value, schema[bound]):
                return f"{path} violates {bound} {schema[bound]}"
    return None
