"""Errors shared by the client, the parsers and the tools."""


class EqanunError(Exception):
    """The site could not be reached or answered something unexpected."""


class NotFound(EqanunError):
    """The site has no such act, article or file."""


class EndpointBlocked(EqanunError):
    """The site refuses requests or asks this server to slow down (HTTP 403 or 429)."""


class TooLarge(EqanunError):
    """An act's file is bigger than this server reads."""


class UnexpectedShape(EqanunError):
    """The site answered, but not in the shape this server knows."""
