import time
from datetime import datetime, timezone
from typing import Optional, Tuple

from functions.utils.db.connect import get_db_client

class MacroSurpriseCalibrationAgent:
    """
    Dedicated calibration layer that owns the baseline standard deviation lookup.
    Now uses MongoDB to retrieve pre-calculated baselines, completely decoupling
    real-time operations from Alpha Vantage API rate limits.
    """

    def __init__(self, cache_ttl_seconds: int = 3600):
        self._cache: dict = {}
        self._ttl: int = cache_ttl_seconds

    def get_historical_std(
        self,
        ff_event_name: str,
        window: int = 12, # Kept for backwards compatibility
        api_key: str = "", # Kept for backwards compatibility
    ) -> Tuple[float, bool]:
        """
        Returns the rolling historical standard deviation for a macro indicator from MongoDB.
        """
        # 1. Cache lookup
        cached = self._get_from_cache(ff_event_name)
        if cached is not None:
            return cached, False

        # 2. Query MongoDB
        try:
            client, db = get_db_client()
            col = db["macro_baselines"]
            doc = col.find_one({"ff_event_name": ff_event_name})
            if not doc:
                doc = col.find_one({"av_indicator": ff_event_name})
            
            if doc and "std_dev" in doc:
                std_val = float(doc["std_dev"])
                if std_val > 0.0:
                    self._set_cache(ff_event_name, std_val)
                    return std_val, False
        except Exception as e:
            print(f"[CalibrationAgent] Database error fetching '{ff_event_name}': {e}")

        # 3. Handle Untracked Events & Coercion Fallback
        fallback = 1.0
        try:
            client, db = get_db_client()
            untracked_col = db["untracked_macro_events"]
            untracked_col.update_one(
                {"ff_event_name": ff_event_name},
                {
                    "$inc": {"query_count": 1},
                    "$set": {"last_queried": datetime.now(timezone.utc).isoformat()}
                },
                upsert=True
            )
        except Exception as e:
            print(f"[CalibrationAgent] Database error logging untracked event '{ff_event_name}': {e}")

        print(
            f"[CalibrationAgent] Coercion fallback applied for untracked '{ff_event_name}': "
            f"std = {fallback} (warning_flag=True)"
        )
        return fallback, True

    def _get_from_cache(self, key: str) -> Optional[float]:
        if self._ttl <= 0:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, fetched_at = entry
        if (time.monotonic() - fetched_at) < self._ttl:
            return value
        del self._cache[key]
        return None

    def _set_cache(self, key: str, value: float):
        self._cache[key] = (value, time.monotonic())

    def clear_cache(self):
        self._cache.clear()
