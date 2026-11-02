"""Local MCP server for the explanatory dictionary of the Azerbaijani language."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("azerbaijan-mcp-izahli")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+unknown"
