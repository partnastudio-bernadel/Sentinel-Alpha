# Sentinel Pipeline Coordination & Architecture Diagram

This document illustrates how the different components of the Sentinel pipeline run autonomously in the background, while still allowing for manual, ad-hoc execution of any agent or scheduler.

---

## 1. Autonomous System Architecture (Background Operations)

The following diagram illustrates the three distinct, fully autonomous execution loops that run in production. They coordinate state asynchronously using the MongoDB database.

```mermaid
graph TD
    %% LOOP 1: Initial Calibration / Seeding
    subgraph Loop1 ["Loop 1: Volatility Calibration (Weekend Refresh via macro_baselines_cli.py)"]
        AV_MCP["Alpha Vantage MCP Server"] -->|Fetch 5-Yr History| CA["macro_baselines_cli.py"]
        CA -->|Compute Rolling Std Dev σ| DB_Baselines[("macro_baselines Collection<br/>(Stores historical σ)")]
    end

    %% LOOP 2: Real-Time Calendar Surprise Ingestion
    subgraph Loop2 ["Loop 2: Macro Surprise Ingestion (Event-Driven / Autonomous)"]
        MS["Macro Scheduler<br/>(macro_scheduler_cli.py)"] -->|1. Wakes up on event time| MS
        MS -->|2. Fetch consensus/actuals| FF_JSON["ForexFactory JSON Mirror"]
        MS -->|3. Query standard deviation| DB_Baselines
        DB_Baselines -->|Returns σ| MS
        MS -->|4. Trigger LangGraph pipeline| MG["Macro Graph<br/>(macro_graph.py)"]
        MG -->|5. Qualitative context + Z-score math| ME["Math Engine<br/>(formulas.py)"]
        ME -->|6. Upsert Shock Index S_t| DB_Calendar[("macro_calendar Collection")]
    end

    %% LOOP 3: Hourly news sentiment
    subgraph Loop3 ["Loop 3: Sentiment Orchestration (Hourly Cron)"]
        SO["Sentinel Orchestrator<br/>(sentinel_orchestrator.py)"] -->|1. Run hourly background loop| SO
        SO -->|2. Pull core ETF list| DB_Entities[("core_entities Collection")]
        SO -->|3. Pull latest Shock Index S_t| DB_Calendar
        SO -->|4. Load macro/market beta vectors| BM["beta_matrix.json"]
        SO -->|5. Run news sentiment graph| SG["sentiment_graph.py<br/>(Sentiment Scorer + CIO)"]
        SG -->|6. Upsert computed weights & velocities| DB_Handler["db_handler.py"]
        DB_Handler -->|Update leaderboard| DB_Leaderboard[("sentiment_leaderboard Collection")]
        DB_Handler -->|Insert scored items| DB_Articles[("articles Collection")]
    end

    %% PRESENTATION LAYER
    subgraph UI ["Presentation Layer (Continuous)"]
        Streamlit["Streamlit Dashboard<br/>(app.py)"]
    end

    DB_Calendar -->|Query Schedule & Shock Values| Streamlit
    DB_Leaderboard -->|Query Live Leaderboard| Streamlit

    style Loop1 fill:#172554,stroke:#3b82f6,stroke-width:2px,color:#fff
    style Loop2 fill:#022c22,stroke:#10b981,stroke-width:2px,color:#fff
    style Loop3 fill:#311042,stroke:#a855f7,stroke-width:2px,color:#fff
    style UI fill:#1e1b4b,stroke:#ec4899,stroke-width:2px,color:#fff
```

---

## 2. Manual / Ad-Hoc Invocation Architecture

While the system is fully autonomous, every component is decoupled and wrapped in a CLI or callable interface. This allows developers or a future "Chat Layer" to manually trigger updates on-demand without interrupting the background loops.

### Command-Line Ad-Hoc Triggers
This graph shows how a user can invoke the individual CLIs directly from the terminal.

```mermaid
graph LR
    subgraph User_Terminal ["User Terminal"]
        Manual_Macro["Manually Trigger Macro CLI"]
        Manual_Sentiment["Manually Trigger Sentiment CLI"]
        Manual_Scheduler["Manually Run Scheduler Scan"]
    end

    subgraph Scripts ["Command Line Wrappers"]
        MACRO_CLI["macro_ingestion_cli.py"]
        SENTIMENT_CLI["sentinel_orchestrator.py --now"]
        SCHED_CLI["macro_scheduler_cli.py --scan-only"]
    end

    subgraph Graphs ["Agent Graphs"]
        MG["Macro Graph<br/>(macro_graph.py)"]
        SG["Sentiment Graph<br/>(sentiment_graph.py)"]
    end

    subgraph DB ["MongoDB Storage"]
        Database[("Live Database Layer")]
    end

    Manual_Macro -->|Runs| MACRO_CLI
    MACRO_CLI -->|Invokes| MG
    MG -->|Saves state| Database

    Manual_Sentiment -->|Runs| SENTIMENT_CLI
    SENTIMENT_CLI -->|Invokes| SG
    SG -->|Saves state| Database

    Manual_Scheduler -->|Runs| SCHED_CLI
    SCHED_CLI -->|Checks for missed events| Database

    style User_Terminal fill:#4c0519,stroke:#e11d48,stroke-width:2px,color:#fff
    style Scripts fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style Graphs fill:#14532d,stroke:#22c55e,stroke-width:2px,color:#fff
    style DB fill:#3f3f46,stroke:#a1a1aa,stroke-width:2px,color:#fff
```

### Conversational Chat Layer Integration
Because the entire system writes its output to MongoDB, a conversational AI interface (Chat Layer) can easily be layered over the DB. The chatbot can read the live DB state to answer questions, and it can be given access to trigger the CLIs as background tools when requested.

```mermaid
graph TD
    subgraph ChatBot ["Conversational Chat Layer"]
        User["User"] -->|1. Asks question or requests update| ChatAgent["LangChain/LangGraph Chat Agent"]
    end

    subgraph DB ["Database State"]
        Database[("MongoDB Collection State")]
    end
    
    subgraph Background_Tools ["Executable Tools"]
        MACRO_TOOL["Tool: Run Macro Update"]
        SENTIMENT_TOOL["Tool: Run Sentiment Update"]
    end

    ChatAgent -->|2a. Reads live state to answer| Database
    ChatAgent -->|2b. If requested, triggers Tool| MACRO_TOOL
    ChatAgent -->|2b. If requested, triggers Tool| SENTIMENT_TOOL
    MACRO_TOOL -->|Executes CLI in background| Database
    SENTIMENT_TOOL -->|Executes CLI in background| Database
    
    style ChatBot fill:#3b0764,stroke:#9333ea,stroke-width:2px,color:#fff
    style DB fill:#3f3f46,stroke:#a1a1aa,stroke-width:2px,color:#fff
    style Background_Tools fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
```
