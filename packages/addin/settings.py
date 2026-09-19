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
MCP_MAIN_THREAD_TIMEOUT = 120.0

ADDIN_NAME = "AutodeskFusionMCP"
COMPANY_NAME = "AutodeskFusionMCP"
