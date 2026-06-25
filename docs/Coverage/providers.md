# OpenBB Platform News Providers

The following table summarizes the data providers for news-related endpoints in the OpenBB Platform (v4), indicating support, commands, and credential requirements:

| Extension Name                 | Native Platform Has News? | OpenBB Code Supports It? | Target Router Command                     | Cost / Key Type                       |
| :----------------------------- | :-----------------------: | :----------------------: | :---------------------------------------- | :------------------------------------ |
| **openbb-benzinga**      |            Yes            |           Yes           | `obb.news.company` / `obb.news.world` | Paid (requires `benzinga_api_key`)  |
| **openbb-biztoc**        |            Yes            |           Yes           | `obb.news.world`                        | Free (requires `biztoc_api_key`)    |
| **openbb-fmp**           |            Yes            |           Yes           | `obb.news.company` / `obb.news.world` | Free Tier (requires `fmp_api_key`)  |
| **openbb-intrinio**      |            Yes            |           Yes           | `obb.news.company` / `obb.news.world` | Paid (requires `intrinio_api_key`)  |
| **openbb-tiingo**        |            Yes            |           Yes           | `obb.news.company` / `obb.news.world` | Free Tier (requires `tiingo_token`) |
| **openbb-tmx**           |            Yes            |           Yes           | `obb.news.company`                      | Free / Unauthenticated                |
| **openbb-yfinance**      |            Yes            |           Yes           | `obb.news.company`                      | Free / Unauthenticated                |
| **openbb-alpha-vantage** |            Yes            |            No            | N/A (Mapped to Price/FX)                  | Free Key                              |
| **openbb-seeking-alpha** |            Yes            |            No            | N/A (Mapped to Calendar)                  | Free                                  |
| **openbb-finviz**        |            Yes            |            No            | N/A (Mapped to Screener)                  | Free                                  |
| **openbb-nasdaq**        |            Yes            |            No            | N/A (Mapped to Data Link)                 | Free Tier                             |

---

## Sentiment Aggregator Provider Status (June 11, 2026)

This table shows the current working status of all 11 providers integrated in our sentiment/news aggregator system:

| Provider Name | Type | Integration Method | Current Status | Details / Limitations |
| :--- | :---: | :--- | :---: | :--- |
| **yfinance** | OpenBB | `obb.news.company` | **🟢 Working** | Works perfectly, no authentication required. |
| **tmx** | OpenBB | `obb.news.company` | **🟢 Working** | Works perfectly, no authentication required. |
| **fmp** | OpenBB | `obb.news.company` | **🟢 Working** | Works perfectly with `FMP_API_KEY`. |
| **biztoc** | OpenBB | `obb.news.world` | **🟢 Working** | Works perfectly with `BIZTOC_API_KEY`. |
| **benzinga** | OpenBB | `obb.news.company` | **🟢 Working** | Works perfectly with `BENZINGA_API_KEY`. |
| **tiingo** | OpenBB | `obb.news.company` | **🟡 Restricted** | Configured with `TIINGO_TOKEN`, but returns permission error because News feed requires a paid Tiingo add-on. |
| **alpha-vantage** | Custom API | `fetch_alpha_vantage` | **🟢 Working** | Works perfectly with `ALPHA_VANTAGE_API_KEY`. |
| **news_api** | Custom API | `fetch_news_api` | **🟢 Working** | Works perfectly with `NEWS_API_KEY`. |
| **nasdaq** | Custom Web API | `fetch_nasdaq_api` | **🟢 Working** | Works perfectly. Pulls from Nasdaq public API endpoint (unauthenticated). |
| **finviz** | Custom Scraper | `fetch_finviz_scrape` | **🟢 Working** | Works perfectly. Custom HTML scraper parsing Finviz stock table. |
| **seeking-alpha** | Custom API (RapidAPI) | `fetch_seeking_alpha_rapidapi` | **🔴 Broken / Unstable** | Old API Dojo endpoint is deprecated. Tipsters Seeking Alpha Finance API is highly unstable (frequent timeouts), and `/v1/articles/list` does not support symbol query filters (ignores them). |

---

## Playwright Full-Text Scraping Results (June 11, 2026)

We tested our Chromium-based Playwright full-text scraper (`fetch_article_text`) on representative URLs for the 12 core financial news domains found in our daily consolidated feeds. Here are the results:

| Domain | Scrape Status | Character Length | Scraping Notes / Details |
| :--- | :---: | :---: | :--- |
| **finance.yahoo.com** | 🟢 **SUCCESS** | ~6,200 chars | Extracts full article body successfully; bypasses cookie dialogs. |
| **cnbc.com** | 🟢 **SUCCESS** | ~13,500 chars | Extracts full article body successfully including sidebar text blocks. |
| **benzinga.com** | 🟢 **SUCCESS** | ~2,600 chars | Extracts full article body successfully. |
| **zerohedge.com** | 🟢 **SUCCESS** | ~4,900 chars | Extracts full article body successfully. |
| **investorplace.com** | 🟢 **SUCCESS** | ~10,400 chars | Extracts full article body successfully. |
| **trefis.com** | 🟢 **SUCCESS** | ~4,200 chars | Extracts full article body successfully. |
| **bloomberg.com** | 🟡 **BLOCKED** | ~400 chars | Blocked by Cloudflare anti-bot verification page ("click the box below to let us know you're not a robot"). |
| **nasdaq.com** | 🔴 **FAILED** | 0 chars | Request fails with `net::ERR_HTTP2_PROTOCOL_ERROR` due to strict CDN headers / HTTP/2 validation blocks. |
| **seekingalpha.com** | 🔴 **FAILED** | 0 chars | Returns empty text due to paywall walling and rendering blocks. |
| **reuters.com** | 🔴 **FAILED** | 0 chars | Returns empty text due to anti-bot protection and subscription wall. |
| **wsj.com** | 🔴 **FAILED** | 0 chars | Returns empty text due to strict paywall blocking paragraph extraction. |
| **marketwatch.com** | 🔴 **FAILED** | 0 chars | Returns empty text due to subscription wall restrictions on body paragraphs. |

---

## 🔊 News Feed Noise and API Authentication Issues

During our testing runs for various tickers (especially for high-profile tech stocks like `AAPL` or constituents of ETFs), we have encountered significant data quality issues and access restrictions:

### 1. Cross-Ticker/ETF Feed Noise
* **The Issue**: News aggregators frequently return articles that are tagged with the target ticker (e.g., `AAPL`) but do not actually focus on that company. This is especially common with macro commentary, market wraps, or articles about unrelated companies (e.g., SpaceX, Tesla) that mention the target ticker in passing or list it under a generic "related stocks" section.
* **Impact**: The Sentiment Scorer agent is forced to process articles that are irrelevant to the target asset's actual business performance, leading to potentially skewed sentiment scores.
* **Mitigation**: The consolidator agent (CIO Agent) checks the articles' relevance and uses confidence-weighted metrics. The system should ideally employ stricter keyword filtering or relevance scoring at the ingestion phase to prune unrelated content before it reaches the scoring agents.

### 2. HTTP 403/Forbidden Blocks
* **The Issue**: External news providers such as SeekingAlpha, Reuters, or Bloomberg frequently block programmatic access, returning HTTP 403 status codes. 
* **Impact**: Attempting to scrape the full-text content of these articles fails, forcing the pipeline to fall back on the snippet/summary field returned by the news search endpoint.
* **Mitigation**: Standardize on using `yfinance`, `tmx`, and `nasdaq` for stock-specific news summary feeds, and rely on `MacroSurpriseCalibrationAgent` and ForexFactory MCP tools for macro indicators where API limits are handled gracefully with fallbacks.


