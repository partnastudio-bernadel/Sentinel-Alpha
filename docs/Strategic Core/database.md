# MongoDB Database Analysis & Growth Report

*Generated on: 2026-06-25 14:18:08 UTC*

## Executive Summary

This report provides an in-depth analysis of the MongoDB footprint for the Sentinel Sentiment project. The analysis covers the document counts, size dimensions (data size, compressed storage size, and index size) and historical growth trajectories for both **sentinel_db** (primary application data) and **checkpointing_db** (LangGraph process checkpoints).

- **Total Document Count:** 8,589 documents
- **Total Data Size:** 366.95 MB
- **Total Disk Storage Size (Compressed):** 215.30 MB
- **Total Index Size:** 0.84 MB

---

## Collection Statistics Summary

| Database | Collection | Document Count | Data Size (KB) | Disk Storage (KB) | Index Size (KB) | Indexes |
|---|---|---|---|---|---|---|
| `sentinel_db` | `calibration_embeddings` | 6,076 | 334,803.72 KB | 210,012.00 KB | 268.00 KB | 1 |
| `checkpointing_db` | `checkpoint_writes` | 1,556 | 11,036.48 KB | 2,792.00 KB | 184.00 KB | 2 |
| `checkpointing_db` | `checkpoints` | 688 | 29,031.34 KB | 6,708.00 KB | 128.00 KB | 2 |
| `sentinel_db` | `langgraph_store` | 121 | 64.08 KB | 80.00 KB | 88.00 KB | 2 |
| `sentinel_db` | `scored_articles` | 98 | 42.47 KB | 68.00 KB | 44.00 KB | 1 |
| `sentinel_db` | `macro_calendar` | 30 | 5.36 KB | 36.00 KB | 36.00 KB | 1 |
| `sentinel_db` | `core_entities` | 12 | 2.86 KB | 36.00 KB | 36.00 KB | 1 |
| `sentinel_db` | `sec_filings_cache` | 6 | 670.36 KB | 588.00 KB | 36.00 KB | 1 |
| `sentinel_db` | `transcripts_cache` | 2 | 104.92 KB | 152.00 KB | 36.00 KB | 1 |

### Hotspots & Large Datasets
1. **`sentinel_db.calibration_embeddings`** is the largest collection in size, consuming **334.8 MB** (approx. 98.7% of the total database footprint). It contains high-dimensional embeddings for news calibration.
2. **`checkpointing_db.checkpoint_writes`** and **`checkpointing_db.checkpoints`** represent the largest document counts (1,556 and 688 respectively), which reflect the frequent state modifications during LangGraph agent execution loops.

---

## Collection Size Visualizations

The charts below show the breakdown of collections by document counts and physical data sizes.

### 1. Collection Document Counts
Shows which collections contain the largest quantity of documents.

![Collection Counts](images/collection_counts.png)

### 2. Collection Data Sizes
Shows the storage footprint of each collection. Notice that although `calibration_embeddings` doesn't have the highest doc count, it represents almost the entire database size due to vectors stored in each document.

![Collection Sizes](images/collection_sizes.png)

---

## Growth Trajectory & Velocity

### 1. Cumulative growth timeline
The line chart below tracks the historical expansion of each collection based on document creation times (using standard MongoDB ObjectIds and custom date attributes).

![Collection Growth](images/collection_growth.png)

### 2. Growth Velocity (Additions over time)
The chart below measures growth speed by aggregating insertions into 6-hour blocks. This excludes the initial setup chunk to highlight active ingestion dynamics.

![Collection Ingestion Velocity](images/collection_velocity.png)

### Growth Analysis
- **Calibration Embeddings:** Reached its full size of 6,076 documents during a batch processing run on **June 21, 2026**. Since then, it has remained static, indicating it functions as reference training/calibration data.
- **Checkpoints & Checkpoint Writes:** Show continuous growth patterns corresponding to the execution times of LangGraph threads, indicating active trading/sentiment sweeps run by the scheduler.
- **Scored Articles:** Displays incremental growth, adding documents as news sentiment loops fetch new articles for tickers.
