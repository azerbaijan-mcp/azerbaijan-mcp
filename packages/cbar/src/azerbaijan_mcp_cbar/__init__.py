"""MCP server for the official exchange rates of the Central Bank of Azerbaijan (CBAR)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("azerbaijan-mcp-cbar")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"
