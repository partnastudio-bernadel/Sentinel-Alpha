# Offline Backtesting Using Kaggle & Hugging Face Transcripts

When building trading models, running real-time API calls to fetch historical transcripts is inefficient and cost-prohibitive. This guide explains how to acquire, preprocess, and integrate bulk datasets from Kaggle and Hugging Face for offline backtesting.

---

## 1. Finding Bulk Datasets

### Kaggle Datasets
Kaggle contains multiple community-curated datasets of parsed earnings call transcripts:
*   **Earnings Call Transcripts (by various authors)**: Typically contains CSV or JSON formats of transcripts for S&P 500 companies over several years.
*   **How to Download**: Use the Kaggle CLI to download datasets directly:
    ```bash
    kaggle datasets download -d <dataset-owner>/<dataset-name>
    ```

### Hugging Face Datasets
Hugging Face hosts datasets specifically formatted for NLP and sentiment models:
*   **`edgar-transcripts` or `financial-transcripts`**: Often contains pre-processed texts split into paragraphs or sentences.
*   **How to Load**: Use the Hugging Face `datasets` Python library to stream or download:
    ```python
    from datasets import load_dataset

    # Stream the dataset to avoid downloading massive gigabyte files all at once
    dataset = load_dataset("owner/dataset-name", split="train", streaming=True)
    for row in dataset:
        print(row["ticker"], row["date"], row["transcript"][:100])
        break
    ```

---

## 2. Formatting and Preprocessing

To make external datasets compatible with the Sentinel Sentiment Analyzer:

### Expected Schema Map
Ensure your bulk data loader parses each raw row into the standard pipeline schema:
```json
{
  "ticker": "AAPL",
  "date": "2024-02-01",
  "quarter": 1,
  "year": 2024,
  "presentation": "Management statements go here...",
  "qa": "Analyst Q&A exchanges go here..."
}
```

### Preprocessing Steps
1.  **Date Standardizing**: Parse timestamps to standard ISO-8601 strings (`YYYY-MM-DD`).
2.  **Section Division**: If the transcript is a single large text string, use regular expressions to segment the Presentation from the Q&A block based on typical transition sentences (e.g., *"We will now open the floor to questions"*).
3.  **Deduplication**: Remove duplicate transcripts and verify that the filings/transcripts align correctly with historical stock prices for accurate backtesting results.

---

## 3. Feeding Data to the Sentinel Pipeline

Instead of running live API/scraper steps, intercept the graph's nodes or pre-load the MongoDB `transcripts_cache` with your Kaggle/Hugging Face dataset.

Since the pipeline first queries the MongoDB cache, **writing your bulk-processed dataset directly into MongoDB** acts as a zero-code-change solution for backtesting:

```python
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["sentinel_db"]
cache_col = db["transcripts_cache"]

# Insert your Kaggle dataset records
backtest_records = [
    {
        "_id": "AAPL_2024_1",  # cache key format: {TICKER}_{YEAR}_{QUARTER}
        "presentation": "...",
        "qa": "...",
        "meta": {"symbol": "AAPL", "quarter": 1, "year": 2024, "date": "2024-02-01"}
    }
]

cache_col.insert_many(backtest_records)
```

Once loaded into the database, running the analysis for `AAPL` will hit the cache directly, bypassing FMP and external web requests entirely.
