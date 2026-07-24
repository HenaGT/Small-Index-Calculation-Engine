"""Exception types raised by the ESX Index Engine."""


class EngineError(Exception):
    """Base class for all engine errors."""


class NotInitializedError(EngineError):
    """Raised when an operation requires a base date/value that hasn't been set."""


class ConstituentNotFoundError(EngineError):
    """Raised when referencing a ticker that isn't in the current index."""


class InvalidCapError(EngineError):
    """Raised when a capping percentage is outside a sane 1-100% range."""


class InvalidCorporateActionError(EngineError):
    """Raised when a corporate action payload is missing required fields."""
