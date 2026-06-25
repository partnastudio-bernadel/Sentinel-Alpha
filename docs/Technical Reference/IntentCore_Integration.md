# IntentCore Integration & Restructuring Guide

## Overview

IntentCore was originally prototyped as a standalone orchestration layer (using FinRobot/AutoGen) wrapped in a heavy SQLite backend. To achieve production readiness, the system was aggressively refactored and integrated natively into Sentinel's core architecture. 

This document serves as a technical reference for engineers tracing the migration of legacy IntentCore logic into native `functions/`.

## Architectural Shifts

1. **Agent Swarms Deprecated**: All FinRobot and AutoGen wrappers were permanently removed. Sentinel now utilizes LangGraph and LangChain natively.
2. **Database Centralization**: The standalone `intentcore.db` SQLite database was decommissioned. All audit logs, reasoning chains, and the manual review queue have been migrated to the primary **MongoDB Atlas** cluster.
3. **Dual-Mode Governance**: The Intent Governor was rebuilt as a LangGraph node (`governor_node.py`). It enforces compliance (e.g., 15% turnover limits) dynamically based on the execution context:
    - **Heartbeat Mode (Cron)**: Applies safe mathematical baselines and logs anomalies asynchronously without halting the pipeline.
    - **Reflex Mode (Webhook)**: Uses `NodeInterrupt` to explicitly pause LangGraph execution when critical flags are triggered, queuing the state for a human operator's manual override.

## File Migration Map

The `intentcore/` directory was entirely dissolved during Phase 2.5 of the integration. Below is the exact mapping of where files moved, how they changed, and why.

| Legacy Path (`intentcore/`) | Native Path (`functions/`) | Changes Made | Reasoning / Explanation |
| :--- | :--- | :--- | :--- |
| `database/manager.py` | `utils/db/governance_manager.py` | Rewritten to use PyMongo via `get_db_client()`. Dropped all `sqlite3` logic. | Sentinel relies heavily on MongoDB for state management; SQLite caused data siloing and concurrency locks. |
| `ui/backend/api.py` | `api/server.py` | Rebuilt as FastAPI. Added `/webhooks/` and direct `/execute/` endpoints. | Centralized the Reflex Router into the native Sentinel API directory. Webhooks launch CLI scripts via `subprocess` for true background async execution. |
| `core/router.py` | `api/router.py` | Converted to a strict LangChain parsing interface with Pydantic output schemas. | Handles semantic intent classification (`INTENT_UPDATE_MACRO`, `INTENT_SCORE_SECTOR`) to route payloads instantly. |
| `core/governor.py` (Draft) | `nodes/governance.py` | Built as a pure LangGraph node. Added Heartbeat (Cron) vs Reflex mode bifurcation. | Hooked natively to the end of `sentiment_graph.py` and `macro_graph.py` as the final production checkpoint. |
| `core/reasoning_chain.py` | `governance/reasoning_chain.py` | No logical changes, just import refactoring. | Core data models needed to live natively with the other governance logic. |
| `core/runtime.py` | `governance/runtime.py` | Refactored internal cross-imports to point to new `functions.*` modules. | Serves as the central interface for assembling reasoning chains from the nodes. |
| `policies/governance.py` | `governance/policies.py` | Import refactoring. | Centralized financial rule definitions. |
| `bridge/` & `wrappers/` | *[DELETED]* | Completely purged from codebase. | Deprecated FinRobot/AutoGen orchestration layers. Replaced by LangChain Router. |
| `database/schema.sql` | *[DELETED]* | Purged. | SQLite deprecated. Replaced by PyMongo document insertion. |
| `ui/frontend/` | `/frontend` (Project Root) | Extracted completely from backend logic. | Standardized React/Vite web application separation of concerns. |

## Webhooks & Remediation Loop

The new `server.py` API exposes several critical endpoints:
*   `/webhooks/news` & `/webhooks/forexfactory`: These intercept live alerts, run them through `router.py`, and trigger `news_sentiment_cli.py` or `macro_scheduler_cli.py`.
*   `/api/reviews/{chain_id}/decision`: When a Portfolio Manager submits an override (e.g., manually tuning a Beta score), this endpoint parses the modification payload and automatically recalculates the exact CLI script using `--override-betas`.

## Verification & Testing
Test coverage for the new governance logic was implemented in:
*   `tests/test_router.py` (Validates LangChain payload routing)
*   `tests/test_governance.py` (Validates the 15% turnover limit and `NodeInterrupt` behaviors)
