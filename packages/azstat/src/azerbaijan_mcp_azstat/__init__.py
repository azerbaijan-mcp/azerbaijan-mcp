"""MCP server for the State Statistical Committee of Azerbaijan."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("azerbaijan-mcp-azstat")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"
