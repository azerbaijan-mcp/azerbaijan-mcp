"""Errors shared by the index, the store and the tools."""


class IzahliError(Exception):
    """The dictionary could not be read, or has no such entry."""


class NotConfigured(IzahliError):
    """No source database is set."""


class BadDatabase(IzahliError):
    """The source database is missing, unreadable or not shaped the way this server expects."""


class BadQuery(IzahliError):
    """The question cannot be answered as it was asked."""


class NotFound(IzahliError):
    """The dictionary has no such headword or entry."""
