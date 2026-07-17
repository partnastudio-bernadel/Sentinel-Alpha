# Macro Ingestion LangGraph Pipeline

This document visualizes the **Macro Ingestion Graph**, illustrating the precise data payloads passed across the graph's `MacroState` and how quantitative/qualitative tools interoperate.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#E3F2FD', 'primaryBorderColor': '#1E88E5', 'primaryTextColor': '#0D47A1', 'lineColor': '#546E7A', 'clusterBkg': '#F9FAFB', 'clusterBorder': '#CFD8DC', 'edgeLabelBackground':'#FFFFFF'}}}%%
graph TD
    classDef startEnd fill:#F3E5F5,stroke:#8E24AA,stroke-width:2px,color:#4A148C;
    classDef process fill:#E3F2FD,stroke:#1E88E5,stroke-width:2px,color:#0D47A1,rx:10,ry:10;
    classDef database fill:#E8F5E9,stroke:#43A047,stroke-width:2px,color:#1B5E20;
    classDef external fill:#FFF3E0,stroke:#FB8C00,stroke-width:2px,color:#E65100,stroke-dasharray: 5 5;
    
    Start((Start Request)):::startEnd -->|"{indicators, timeframe_days}"| forex_factory

    subgraph Quantitative Pipeline
        direction TB
        forex_factory[forex_factory]:::process
        alpha_vantage[alpha_vantage]:::process
        
        forex_factory -->|"{forex_events}"| alpha_vantage
        alpha_vantage -->|"{av_indicators}"| textual_inertia
    end

    subgraph Qualitative Pipeline
        direction TB
        textual_inertia[textual_inertia]:::process
        tension_extractor[tension_extractor]:::process
        
        textual_inertia -->|"{textual_inertia_results}"| tension_extractor
        tension_extractor -->|"{tension_extractor_results}"| chief_economist
    end

    subgraph Final Synthesis
        direction TB
        chief_economist[chief_economist]:::process
    end
    
    chief_economist -->|"{results: MacroReport JSON}"| End((Final Output)):::startEnd

    %% Databases & APIs
    ForexMCP{{ForexFactory MCP}}:::external
    AlphaVantage{{Alpha Vantage API}}:::external
    SEC_Transcripts[(SEC / Transcripts)]:::database
    MongoDB[(MongoDB MQL)]:::database
    LLMs{{LLM Agents}}:::external

    forex_factory -.- ForexMCP
    alpha_vantage -.- AlphaVantage
    textual_inertia -.- SEC_Transcripts
    textual_inertia -.- LLMs
    tension_extractor -.- SEC_Transcripts
    tension_extractor -.- LLMs
    chief_economist -.- MongoDB
    chief_economist -.- LLMs

    subgraph Legend
        direction TB
        L1((Input / Output)):::startEnd
        L2[Internal Process Node]:::process
        L3[(Database Store)]:::database
        L4{{External API / Model}}:::external
    end

    %% Invisible link to force Legend to the bottom
    End ~~~ L1
```

## Detailed Node Workings

1. **`forex_factory`**:
   - **Data Intake**: Takes in the user's `timeframe_days` and `indicators` request.
   - **Inner Workings**: Communicates asynchronously with the **ForexFactory MCP server** to fetch a global macroeconomic calendar and economic events (e.g. CPI prints, rate decisions).
   - **Data Passed Output**: Passes a list of global economic events to the state via the `forex_events` key.

2. **`alpha_vantage`**:
   - **Data Intake**: Consumes `forex_events`.
   - **Inner Workings**: Utilizes a `MacroSurpriseCalibrationAgent` interacting with the **Alpha Vantage API**. It cross-references the scheduled events with trailing historical data to calculate actual vs. consensus "surprise" factors in the market.
   - **Data Passed Output**: Appends the mathematical indicator metrics to the state via the `av_indicators` payload.

3. **`textual_inertia`**:
   - **Data Intake**: Consumes the quantitative indicators.
   - **Inner Workings**: Shifts the pipeline to qualitative analysis. It calls upon a **ChatNVIDIA LLM Agent (Kimi config)** to analyze the "textual inertia" of heavy SEC filings and central bank statements (e.g. tracking subtle hawkish/dovish shifts in FOMC rhetoric over time).
   - **Data Passed Output**: Outputs subjective NLP shifts into `textual_inertia_results`.

4. **`tension_extractor`**:
   - **Data Intake**: Consumes `textual_inertia_results`.
   - **Inner Workings**: Employs another specialized **ChatNVIDIA LLM Agent** to analyze earnings call transcripts and press conferences. It specifically searches for hesitation, conflicting signals, or tension between analysts' Q&A and leadership responses.
   - **Data Passed Output**: Stores the qualitative tension scoring in `tension_extractor_results`.

5. **`chief_economist`**:
   - **Data Intake**: Aggregates all prior state variables (`forex_events`, `av_indicators`, `textual_inertia_results`, `tension_extractor_results`).
   - **Inner Workings**: Acts as the ultimate aggregator. It employs a LangChain Agent armed with the **MongoDB Text-to-MQL Toolkit** to query historical macroeconomic regimes (e.g. previous high-inflation periods) and compare them with the current collected state variables.
   - **Data Passed Output**: Generates a unified, structured macroeconomic outlook schema, storing the final JSON into the `results` key.

---

## Economic Calendar Retrieval Resiliency Flow

When resolving calendar events (e.g., `"CPI m/m"`), the pipeline uses a layered strategy to ensure high availability and bypass anti-bot scrapers:

```mermaid
graph TD
    A[Start Macro Ingestion] --> B(Live ForexFactory Scraping)
    B --> C{Events Retrieved?}
    C -- Yes (Match Found) --> D[Resolve Event Data]
    C -- No / Blocked --> E[Query MongoDB macro_calendar Cache]
    E --> F{Cached Event Found?}
    F -- Yes --> G[Extract Data & Set warning_flag=False]
    F -- No --> H[Apply Fuzzy/Regex Title Matcher]
    H --> I{Fuzzy Match Found?}
    I -- Yes --> D
    I -- No --> J[Trigger Scheduler fail-safe 0.0 payload]
    D --> K[Calculate Surprise & Forward to Chief Economist]
    G --> K
    J --> L[Fallback Report with warning_flag=True]
```
