"""Errors shared by the index, the store and the tools."""


class IzahliError(Exception):
    """The dictionary could not be read, or has no such entry."""


class BadDatabase(IzahliError):
    """The source database is missing, unreadable or not shaped the way this server expects."""


class DownloadFailed(IzahliError):
    """The dictionary database could not be downloaded."""


class BadQuery(IzahliError):
    """The question cannot be answered as it was asked."""


class NotFound(IzahliError):
    """The dictionary has no such headword or entry."""
