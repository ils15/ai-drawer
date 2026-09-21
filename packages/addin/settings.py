# Application Global Variables


DEBUG = True
MCP_DEBUG = False
MCP_AUTO_CONNECT = True

# Network interface the Streamable HTTP server binds to.
#
# Loopback is the only safe default: the add-in serves a tool surface that can
# drive the whole Fusion process, so it must never be reachable from the
# network. The WSL -> Windows host path can still reach it, because WSL can
# address the host's loopback directly (non-mirrored networking mode needs the
# host's vEthernet adapter IP instead -- set this to that address, or to
# "0.0.0.0" only if you understand and accept the exposure).
MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8765

# Seconds a tools/call request waits for the Fusion main thread before
# returning a timeout error to the client.  Previously the wait was
# unbounded, so a busy or frozen Fusion hung MCP clients forever.
#
# INVARIANT: this value must be strictly LESS than the bridge's
# DEFAULT_TIMEOUT_MS (30 000 ms).  The bridge uses an AbortController
# that fires at 30 s; when it does, the client sees a timeout error.
# If the add-in's deadline were ≥ 30 s, a queued mutation could still
# execute on the Fusion main thread *after* the client already received
# a timeout — a silent late application that causes duplicate state on
# retry.  With 25 s here and 30 s in the bridge, the 5 s margin
# guarantees the add-in has responded (cancelling queued work or
# returning a "still running" warning) before the bridge gives up.
#
# The 5 s margin also absorbs HTTP-handler overhead (SSE framing,
# thread join, socket write) so the response reaches the bridge
# connection before the AbortController fires.
MCP_MAIN_THREAD_TIMEOUT = 25.0

ADDIN_NAME = "AutodeskFusionMCP"
COMPANY_NAME = "AutodeskFusionMCP"
