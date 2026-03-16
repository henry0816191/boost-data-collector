"""Compatibility exports for dashboard callers.

The canonical models are defined in ``boost_usage_tracker.models`` and should
be used by dashboard code instead of maintaining duplicate model definitions.
"""

from boost_usage_tracker.models import BoostExternalRepository, BoostUsage

__all__ = ["BoostExternalRepository", "BoostUsage"]
