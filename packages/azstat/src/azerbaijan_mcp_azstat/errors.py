"""Errors shared by the client, the parsers and the tools."""


class AzstatError(Exception):
    """The API could not be reached or answered something unexpected."""


class NotFound(AzstatError):
    """The Committee has no such table."""


class EndpointBlocked(AzstatError):
    """The API refuses requests or asks this server to slow down (HTTP 403 or 429)."""


class TableTooLarge(AzstatError):
    """The table is bigger than this server reads."""


class UnexpectedShape(AzstatError):
    """The API answered, but not in the shape this server knows."""
