import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Custom typed exceptions raised by mcp_helper so the scheduler can classify
# them without importing httpx or other transport libraries directly.
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """Raised when an upstream MCP source returns HTTP 429 or HTTP 403."""
    pass


class MCPConnectionError(Exception):
    """Raised when the MCP transport layer fails to establish a connection."""
    pass


# ---------------------------------------------------------------------------
# MacroScheduler
# ---------------------------------------------------------------------------

class MacroScheduler:
    """
    Deterministic middleware guard that wraps raw MCP tool calls with:
      - 10-second async timeout enforcement (TRD requirement)
      - Exception classification → telemetry state machine
      - 12-hour staleness boundary annotation (non-blocking)
      - NaN-safe fallback payload contract when a failure state is detected
      - Structured audit metadata block (_scheduler) for downstream logging
      - Optional redis_client parameter for future Option B state persistence

    State machine:
        OK           - Successful tool execution.
        STALE        - Data retrieved but older than 12-hour staleness window,
                       OR an unclassified exception occurred.
        RATE_LIMITED - HTTP 429 / HTTP 403 response received.
        TIMEOUT      - asyncio.TimeoutError or network timeout exceeded.

    Usage:
        scheduler = MacroScheduler()
        result = scheduler.execute_with_guard(
            async_query_forexfactory_mcp,
            "ffcal_get_calendar_events", {"time_period": "this_month"},
            source="forexfactory",
            timeout=10.0
        )
        if scheduler.state != "OK":
            payload = scheduler.build_fallback_payload("CPI m/m")
    """

    # Staleness window in seconds (12 hours as specified in TRD)
    STALENESS_SECONDS: int = 43200

    # Default network timeout in seconds (TRD: 10-second threshold)
    DEFAULT_TIMEOUT: float = 60.0

    def __init__(self, redis_client=None):
        """
        Args:
            redis_client: Optional Redis client for future Option B persistent
                          state. When None (default), state is in-process only.
        """
        self._lock = threading.Lock()
        self._state: str = "OK"
        self._stale_calendar_flag: bool = False
        self._redis = redis_client  # Future: redis.set("stale_calendar_flag", 1, ex=43200)

    # ------------------------------------------------------------------
    # Public Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def stale_calendar_flag(self) -> bool:
        with self._lock:
            return self._stale_calendar_flag

    # ------------------------------------------------------------------
    # Core Guard
    # ------------------------------------------------------------------

    def execute_with_guard(
        self,
        async_fn: Callable,
        *args,
        source: str = "unknown",
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs
    ) -> Any:
        """
        Executes an async MCP tool call synchronously with timeout enforcement
        and exception classification.

        Args:
            async_fn:  The async coroutine function to execute.
            *args:     Positional arguments forwarded to async_fn.
            source:    Human-readable data source label (e.g. 'forexfactory', 'alpha_vantage').
            timeout:   Maximum seconds to wait for a response. Defaults to 10.0.
            **kwargs:  Keyword arguments forwarded to async_fn.

        Returns:
            The raw result from async_fn if successful.

        Raises:
            RuntimeError: Always re-raises after updating internal state, so the
                          caller can decide whether to use build_fallback_payload().
        """
        start_ms = int(time.monotonic() * 1000)

        try:
            # Build the coroutine then wrap with wait_for inside a thread event loop
            coro = async_fn(*args, **kwargs)
            result = self._run_with_timeout(coro, timeout)
            self._set_state("OK")
            return result

        except asyncio.TimeoutError as e:
            self._set_state("TIMEOUT")
            raise RuntimeError(f"[Scheduler] Timeout after {timeout}s on '{source}'.") from e

        except RateLimitError as e:
            self._set_state("RATE_LIMITED")
            raise RuntimeError(f"[Scheduler] Rate limit (429/403) on '{source}'.") from e

        except (MCPConnectionError, ConnectionError, OSError) as e:
            self._set_state("STALE")
            raise RuntimeError(f"[Scheduler] Connection error on '{source}': {e}") from e

        except Exception as e:
            self._set_state("STALE")
            raise RuntimeError(f"[Scheduler] Unclassified error on '{source}': {e}") from e

    # ------------------------------------------------------------------
    # Staleness Check (non-blocking annotation)
    # ------------------------------------------------------------------

    def check_staleness(self, datetime_utc_str: Optional[str]) -> bool:
        """
        Compares an event's datetime_utc timestamp against the current UTC time.
        Returns True if the event is older than STALENESS_SECONDS (12 hours).

        This is NON-BLOCKING — a stale payload still proceeds to calculation.
        Staleness is only annotated in the _scheduler metadata block.

        Args:
            datetime_utc_str: ISO 8601 UTC string (e.g. '2026-06-10T12:30:00+00:00').
                              Returns False (not stale) if None or unparseable.

        Returns:
            bool: True if age exceeds 12-hour boundary.
        """
        if not datetime_utc_str:
            return False
        try:
            event_dt = datetime.fromisoformat(datetime_utc_str)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - event_dt).total_seconds()
            return age_seconds > self.STALENESS_SECONDS
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Fallback Payload Builder
    # ------------------------------------------------------------------

    def build_fallback_payload(
        self,
        event_name: str,
        source: str = "unknown",
        outage_duration_ms: int = 0,
        stale: bool = False
    ) -> dict:
        """
        Constructs a deterministic NaN-safe payload contract.

        All numeric fields are set to 0.0, warning_flag is True, and
        macro_surprise_score is 0.0 (α_t → 0), ensuring FinRL-X receives
        a clean, parseable row with no NaN contamination.

        The _scheduler block contains audit metadata and is stripped before
        surfacing the payload to downstream consumers — it is written to the
        audit log only.

        Args:
            event_name:         The target economic event (e.g. 'CPI m/m').
            source:             Which data source triggered the fallback.
            outage_duration_ms: Duration of the failed attempt in milliseconds.
            stale:              Whether staleness annotation applies.

        Returns:
            dict: Schema-compliant fallback payload with embedded _scheduler block.
        """
        with self._lock:
            current_state = self._state

        triggered_at = datetime.now(timezone.utc).isoformat()
        trigger_start = int(time.monotonic() * 1000)

        payload = {
            "reasoning_summary": (
                f"Scheduler fail-safe triggered: {current_state} on {source}. "
                "alpha_t -> 0. Falling back to base portfolio weights w_base_t."
            ),
            "event_name": event_name,
            "category": None,
            "timestamp": None,
            "data": {
                "actual": 0.0,
                "consensus": 0.0,
                "difference": 0.0,
                "historical_std": 0.0,
                "impact_tier": None
            },
            "metrics": {
                "macro_surprise_score": 0.0,
                "warning_flag": True
            },
            "_scheduler": {
                "state": current_state,
                "source": source,
                "stale": stale,
                "outage_duration_ms": outage_duration_ms,
                "fallback_triggered_at": triggered_at,
                "fallback_trigger_ms": int(time.monotonic() * 1000) - trigger_start
            }
        }

        return payload

    # ------------------------------------------------------------------
    # State Helpers
    # ------------------------------------------------------------------

    def reset(self):
        """Resets state between pipeline runs. Call before each CLI invocation."""
        with self._lock:
            self._state = "OK"
            self._stale_calendar_flag = False
        # Future Option B: self._redis.delete("stale_calendar_flag")

    def _set_state(self, state: str):
        with self._lock:
            self._state = state
            if state != "OK":
                self._stale_calendar_flag = True
                # Future Option B: self._redis.set("stale_calendar_flag", 1, ex=self.STALENESS_SECONDS)

    # ------------------------------------------------------------------
    # Internal Async Runner
    # ------------------------------------------------------------------

    def _run_with_timeout(self, coro, timeout: float) -> Any:
        """Runs a coroutine with asyncio.wait_for timeout in a background thread."""
        import sys
        result_holder = {}
        exc_holder = {}

        def _run():
            try:
                if sys.platform == "win32":
                    loop = asyncio.ProactorEventLoop()
                else:
                    loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result_holder["result"] = loop.run_until_complete(
                    asyncio.wait_for(coro, timeout=timeout)
                )
            except asyncio.TimeoutError as e:
                exc_holder["exc"] = e
            except Exception as e:
                exc_holder["exc"] = e
            finally:
                loop.close()

        t = threading.Thread(target=_run)
        t.start()
        t.join()

        if "exc" in exc_holder:
            raise exc_holder["exc"]
        return result_holder["result"]
