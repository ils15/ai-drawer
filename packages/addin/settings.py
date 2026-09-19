# Application Global Variables

import os

DEBUG = True
MCP_DEBUG = False
MCP_AUTO_CONNECT = True
MCP_SERVER_PORT = 8765

# Seconds a tools/call request waits for the Fusion main thread before
# returning a timeout error to the client.  Previously the wait was
# unbounded, so a busy or frozen Fusion hung MCP clients forever.
MCP_MAIN_THREAD_TIMEOUT = 120.0

ADDIN_NAME = "AutodeskFusionMCP"
COMPANY_NAME = "AutodeskFusionMCP"
