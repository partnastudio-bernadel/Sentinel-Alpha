# News Sentiment LangGraph Pipeline

This document visualizes the **News Sentiment Graph**, detailing how the inner nodes interact, the specific state variables (`SentimentState`) they pass to each other, and their external dependencies.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#E3F2FD', 'primaryBorderColor': '#1E88E5', 'primaryTextColor': '#0D47A1', 'lineColor': '#546E7A', 'clusterBkg': '#F9FAFB', 'clusterBorder': '#CFD8DC', 'edgeLabelBackground':'#FFFFFF'}}}%%
graph TD
    classDef startEnd fill:#F3E5F5,stroke:#8E24AA,stroke-width:2px,color:#4A148C;
    classDef process fill:#E3F2FD,stroke:#1E88E5,stroke-width:2px,color:#0D47A1,rx:10,ry:10;
    classDef database fill:#E8F5E9,stroke:#43A047,stroke-width:2px,color:#1B5E20;
    classDef external fill:#FFF3E0,stroke:#FB8C00,stroke-width:2px,color:#E65100,stroke-dasharray: 5 5;
    
    Start((Start Request)):::startEnd -->|"{ticker, timeframe_days, limit}"| ingest_news

    subgraph Data Ingestion & Caching
        direction TB
        ingest_news[ingest_news]:::process
        check_cache[check_cache]:::process
        prepare_bypass[prepare_bypass]:::process
        
        ingest_news -->|"{articles_payload, raw_article_ids, is_etf, constituents}"| check_cache
        ingest_news -.->|If force_rescore=True| prepare_bypass
        prepare_bypass -->|"{cache_buster timestamp}"| sentiment_scorer_node
    end

    subgraph LLM Scoring & Analysis
        direction TB
        sentiment_scorer_node[sentiment_scorer_node]:::process
        check_cache -->|"{uncached articles_payload, scored_article_ids}"| sentiment_scorer_node
        
        cio_analyst_node[cio_analyst_node]:::process
        sentiment_scorer_node -->|"{scored_article_ids}"| cio_analyst_node
    end

    cio_analyst_node -->|"{results: SentimentReport JSON}"| End((Final Output)):::startEnd

    %% External Dependencies
    MongoDB[(MongoDB)]:::database
    OpenBB{{OpenBB API}}:::external
    Aggregator{{News Aggregator}}:::external
    LLMs{{LLM Agents}}:::external
    SEC_Data[(SEC / Qualitative Data)]:::database

    ingest_news -.- OpenBB
    ingest_news -.- Aggregator
    ingest_news -.- MongoDB
    check_cache -.- MongoDB
    sentiment_scorer_node -.- LLMs
    sentiment_scorer_node -.- MongoDB
    cio_analyst_node -.- SEC_Data
    cio_analyst_node -.- LLMs

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

1. **`ingest_news`**: 
   - **Data Intake**: Takes in the base request (`ticker`, `timeframe`, `limit`).
   - **Inner Workings**: If the ticker is an ETF, it queries OpenBB to decompose the ETF into its top `holdings` (constituents). It fetches news via the aggregator API.
   - **Data Passed Output**: Prepares the raw articles and passes them as `articles_payload`, along with `raw_article_ids` and `is_etf`/`constituents` metadata. Raw heavy data is stored in MongoDB LangGraph store.

2. **`check_cache` / `prepare_bypass`**: 
   - **Data Intake**: Takes the `articles_payload`.
   - **Inner Workings**: Queries the MongoDB `scored_articles` collection to see if any articles have already been scored by the LLM. 
   - **Data Passed Output**: Splits the payload. Passes ONLY `uncached_articles` via the `articles_payload` field to the LLM scorer. If `force_rescore` is True, `prepare_bypass` simply sets a `cache_buster` timestamp in the state to bypass LangGraph's internal cache mechanism.

3. **`sentiment_scorer_node`**:
   - **Data Intake**: Takes the uncached `articles_payload`.
   - **Inner Workings**: Spins up a LangChain React Agent. It uses a MongoDB Vector Search Retriever to pull financial sentence calibration examples as few-shot context.
   - **Data Passed Output**: Returns the `scored_article_ids` after writing all LLM inferences to the MongoDB `scored_articles` database.

4. **`cio_analyst_node` (Chief Investment Officer)**:
   - **Data Intake**: Takes `scored_article_ids` and the ETF `constituents` metadata.
   - **Inner Workings**: Reads the scored records from MongoDB. It then concurrently executes qualitative worker agents (`textual_inertia`, `tension_extractor`) powered by Kimi LLM on SEC filings. It then calculates mathematical weighted portfolios (`calculate_portfolio_sentiment`).
   - **Data Passed Output**: Outputs the final meticulously structured Pydantic model (`SentimentReport`) stored into the `results` state key.
