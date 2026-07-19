#!/usr/bin/env python3
"""
Sentinel Heavy Collections R2 Migrator
Location: scripts/migrate_heavy_collections_to_r2.py

Offloads 'calibration_embeddings' (326.96 MB) and 'sec_filings_cache' (41.06 MB)
from MongoDB Atlas to Cloudflare R2 object storage to instantly free up ~370 MB of storage
and release the Atlas 512 MB write lock.

Usage:
    python scripts/migrate_heavy_collections_to_r2.py --dry-run
    python scripts/migrate_heavy_collections_to_r2.py --collection sec_filings_cache
    python scripts/migrate_heavy_collections_to_r2.py --collection calibration_embeddings
    python scripts/migrate_heavy_collections_to_r2.py --all
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, List

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_local = project_root / ".env.local"
env_default = project_root / ".env"
if env_local.exists():
    load_dotenv(env_local)
elif env_default.exists():
    load_dotenv(env_default)

from functions.utils.db.connect import get_db_client
from functions.utils.storage.r2_client import (
    get_r2_client,
    get_r2_bucket_name,
    ensure_bucket_exists,
    exists_in_r2
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Heavy_Migrator")

def upload_json_to_r2(r2_key: str, data_dict: Dict[str, Any]) -> bool:
    """Uploads a dictionary payload as JSON to Cloudflare R2."""
    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    json_bytes = json.dumps(data_dict, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    client.put_object(
        Bucket=bucket_name,
        Key=r2_key,
        Body=json_bytes,
        ContentType="application/json"
    )
    return True

def migrate_sec_filings(dry_run: bool = False, limit: int = 0):
    logger.info("--- Processing sec_filings_cache (Target: ~41 MB) ---")
    client, db = get_db_client()
    coll = db["sec_filings_cache"]
    total = coll.count_documents({})
    logger.info(f"Found {total} documents in 'sec_filings_cache'.")

    cursor = coll.find({})
    if limit > 0:
        cursor = cursor.limit(limit)

    migrated = 0
    bytes_saved = 0

    for doc in cursor:
        doc_id = str(doc.get("_id"))
        doc_json = json.dumps(doc, default=str)
        doc_size = len(doc_json.encode("utf-8"))

        r2_key = f"sec_filings_cache/{doc_id}.json"

        if dry_run:
            logger.info(f"[DRY-RUN] SEC Filing '{doc_id}' ({doc_size} bytes) -> R2 '{r2_key}'")
            migrated += 1
            bytes_saved += doc_size
            continue

        try:
            upload_json_to_r2(r2_key, doc)
            if not exists_in_r2(r2_key):
                raise RuntimeError(f"Verification failed in R2 for key '{r2_key}'")

            coll.delete_one({"_id": doc["_id"]})
            migrated += 1
            bytes_saved += doc_size
            logger.info(f"✅ Migrated SEC Filing '{doc_id}' -> R2 '{r2_key}' (Freed {doc_size/1024:.1f} KB)")
        except Exception as e:
            logger.error(f"❌ Failed to migrate SEC Filing '{doc_id}': {e}")

    logger.info(f"Finished sec_filings_cache: {migrated} docs processed, ~{bytes_saved/(1024*1024):.2f} MB freed.")

def migrate_calibration_embeddings(dry_run: bool = False, limit: int = 0):
    logger.info("--- Processing calibration_embeddings (Target: ~327 MB) ---")
    client, db = get_db_client()
    coll = db["calibration_embeddings"]
    total = coll.count_documents({})
    logger.info(f"Found {total} documents in 'calibration_embeddings'.")

    cursor = coll.find({})
    if limit > 0:
        cursor = cursor.limit(limit)

    migrated = 0
    bytes_saved = 0

    for doc in cursor:
        doc_id = str(doc.get("_id"))
        doc_json = json.dumps(doc, default=str)
        doc_size = len(doc_json.encode("utf-8"))

        r2_key = f"calibration_embeddings/{doc_id}.json"

        if dry_run:
            if migrated < 5 or migrated % 1000 == 0:
                logger.info(f"[DRY-RUN] Embedding '{doc_id}' ({doc_size} bytes) -> R2 '{r2_key}'")
            migrated += 1
            bytes_saved += doc_size
            continue

        try:
            upload_json_to_r2(r2_key, doc)
            if not exists_in_r2(r2_key):
                raise RuntimeError(f"Verification failed in R2 for key '{r2_key}'")

            coll.delete_one({"_id": doc["_id"]})
            migrated += 1
            bytes_saved += doc_size

            if migrated % 100 == 0:
                logger.info(f"✅ Progress: {migrated}/{total} embeddings migrated to R2 (~{bytes_saved/(1024*1024):.2f} MB freed)")
        except Exception as e:
            logger.error(f"❌ Failed to migrate embedding '{doc_id}': {e}")

    logger.info(f"Finished calibration_embeddings: {migrated} docs processed, ~{bytes_saved/(1024*1024):.2f} MB freed.")

def migrate_transcripts_cache(dry_run: bool = False, limit: int = 0):
    logger.info("--- Processing transcripts_cache (Target: ~11 MB) ---")
    client, db = get_db_client()
    coll = db["transcripts_cache"]
    total = coll.count_documents({})
    logger.info(f"Found {total} documents in 'transcripts_cache'.")

    cursor = coll.find({})
    if limit > 0:
        cursor = cursor.limit(limit)

    migrated = 0
    bytes_saved = 0

    for doc in cursor:
        doc_id = str(doc.get("_id"))
        doc_json = json.dumps(doc, default=str)
        doc_size = len(doc_json.encode("utf-8"))

        r2_key = f"transcripts_cache/{doc_id}.json"

        if dry_run:
            logger.info(f"[DRY-RUN] Transcript '{doc_id}' ({doc_size} bytes) -> R2 '{r2_key}'")
            migrated += 1
            bytes_saved += doc_size
            continue

        try:
            upload_json_to_r2(r2_key, doc)
            if not exists_in_r2(r2_key):
                raise RuntimeError(f"Verification failed in R2 for key '{r2_key}'")

            coll.delete_one({"_id": doc["_id"]})
            migrated += 1
            bytes_saved += doc_size
            logger.info(f"✅ Migrated Transcript '{doc_id}' -> R2 '{r2_key}' (Freed {doc_size/1024:.1f} KB)")
        except Exception as e:
            logger.error(f"❌ Failed to migrate transcript '{doc_id}': {e}")

    logger.info(f"Finished transcripts_cache: {migrated} docs processed, ~{bytes_saved/(1024*1024):.2f} MB freed.")

def main():
    parser = argparse.ArgumentParser(description="Sentinel Heavy Collections R2 Migration Tool")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without writing to R2 or modifying MongoDB")
    parser.add_argument("--collection", choices=["sec_filings_cache", "calibration_embeddings", "transcripts_cache"], help="Specific collection to migrate")
    parser.add_argument("--all", action="store_true", help="Migrate all heavy collections (sec_filings_cache, calibration_embeddings, transcripts_cache)")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of documents to process per collection (default: 0 = all)")

    args = parser.parse_args()

    if not args.dry_run:
        try:
            ensure_bucket_exists()
        except Exception as e:
            logger.error(f"R2 Bucket connection check failed: {e}")
            sys.exit(1)

    if args.collection == "sec_filings_cache":
        migrate_sec_filings(dry_run=args.dry_run, limit=args.limit)
    elif args.collection == "calibration_embeddings":
        migrate_calibration_embeddings(dry_run=args.dry_run, limit=args.limit)
    elif args.collection == "transcripts_cache":
        migrate_transcripts_cache(dry_run=args.dry_run, limit=args.limit)
    elif args.all or not args.collection:
        migrate_sec_filings(dry_run=args.dry_run, limit=args.limit)
        migrate_calibration_embeddings(dry_run=args.dry_run, limit=args.limit)
        migrate_transcripts_cache(dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()
