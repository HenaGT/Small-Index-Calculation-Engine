"""
ESX Index Engine
================

A free-float, market-capitalization-weighted index calculation engine
built to the ESX Index Methodology (Ethiopian Securities Exchange):

    Index Value = Sum(Price_i * Shares_i * FreeFloat%_i) / Divisor

Core capabilities:
    - Daily index-level calculation
    - Free-float adjustment
    - Automatic weight computation
    - Single-constituent capping with proportional redistribution
    - Divisor management (continuity across rebalances / corporate actions)
    - Corporate action processing (splits, rights issues, mergers,
      delistings, additions/deletions, dividends)
    - Historical backtesting
    - CSV / JSON export

See README.md for usage.
"""

from .models import Constituent, CorporateAction, DailyRecord
from .engine import ESXIndexEngine
from .capping import apply_cap
from .exceptions import (
    EngineError,
    NotInitializedError,
    ConstituentNotFoundError,
    InvalidCapError,
)

__all__ = [
    "Constituent",
    "CorporateAction",
    "DailyRecord",
    "ESXIndexEngine",
    "apply_cap",
    "EngineError",
    "NotInitializedError",
    "ConstituentNotFoundError",
    "InvalidCapError",
]

__version__ = "1.0.0"
