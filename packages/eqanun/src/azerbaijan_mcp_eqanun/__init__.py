"""Local MCP server for e-qanun.az, the Azerbaijani legal acts base."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("azerbaijan-mcp-eqanun")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"
