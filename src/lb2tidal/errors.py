"""Exception hierarchy.

Each exception maps to an exit code in ``cli`` (§6.4 of the specification).
"""


class Lb2TidalError(Exception):
    """Base class for every error this tool raises deliberately."""


class ConfigError(Lb2TidalError):
    """Configuration is missing, malformed, or invalid. Exit code 2."""


class AuthError(Lb2TidalError):
    """Tidal authentication is missing, expired, or was never completed. Exit code 3."""


class RecommendationError(Lb2TidalError):
    """One recommendation failed. Recorded in the report; other ones continue."""


class ServiceUnavailable(RecommendationError):
    """Too many consecutive failures: the remote service is treated as down."""
