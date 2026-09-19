from .mcp_about_command import start, stop

# Re-exported so the add-in's command registry can import the pair by package
# (`from commands.mcpAbout import start, stop`).  Declaring them here keeps the
# names part of the public API without triggering F401 for "unused" imports.
__all__ = ["start", "stop"]
