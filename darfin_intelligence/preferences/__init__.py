"""User Feedback & Personal Classification Preferences package (Task 2D).

Provides deterministic preference learning, feedback recording,
pattern normalization, and personalized suggestion boosting.
"""

from __future__ import annotations

from darfin_intelligence.preferences.models import (
    UserPreference,
    PreferenceBoost,
)
from darfin_intelligence.preferences.engine import (
    PreferenceEngine,
    apply_preferences,
    extract_reusable_patterns,
    is_folder_compatible_with_family,
)

__all__ = [
    "UserPreference",
    "PreferenceBoost",
    "PreferenceEngine",
    "apply_preferences",
    "extract_reusable_patterns",
    "is_folder_compatible_with_family",
]
