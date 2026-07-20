import os
import sys
import gzip
import shutil
import logging
import argparse
from datetime import datetime, timezone, timedelta

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir)
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.storage.r2_client import get_r2_client, get_r2_bucket_name, ensure_bucket_exists

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [log_archiver] %(message)s')
logger = logging.getLogger("log_archiver")

def compress_file(source_file: str, dest_gz: str):
    """Compresses a log file to .gz format."""
    with open(source_file, 'rb') as f_in:
        with gzip.open(dest_gz, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

def archive_and_upload_logs(retention_days: int = 60, dry_run: bool = False):
    """
    1. Finds rotated log files (*.log.1, *.log.2, etc.) in logs/ directory.
    2. Compresses them into .gz archives.
    3. Uploads compressed archives to Cloudflare R2 storage under logs/YYYY/MM/DD/.
    4. Deletes local rotated files after successful upload.
    5. Enforces retention policy by purging R2 logs older than retention_days (60 days).
    """
    logs_dir = os.path.join(sentiment_dir, "logs")
    if not os.path.exists(logs_dir):
        logger.info(f"Logs directory does not exist yet: {logs_dir}")
        return

    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    now_utc = datetime.now(timezone.utc)
    
    if not dry_run:
        ensure_bucket_exists()

    logger.info(f"Scanning for rotated log files in {logs_dir}...")
    
    # Identify rotated files (e.g., sentiment_pipeline.log.1, macro_pipeline.log.1, pipeline.log.1)
    candidates = []
    for entry in os.listdir(logs_dir):
        full_path = os.path.join(logs_dir, entry)
        if os.path.isfile(full_path) and (
            entry.endswith(".1") or 
            entry.endswith(".2") or 
            entry.endswith(".3") or 
            (entry.endswith(".log") and entry not in ["sentiment_pipeline.log", "macro_pipeline.log", "sentinel_orchestrator.log", "pipeline.log"])
        ):
            candidates.append(full_path)

    if not candidates:
        logger.info("No rotated log files currently pending archival.")
    else:
        logger.info(f"Found {len(candidates)} log file(s) for R2 archival.")

    for file_path in candidates:
        file_name = os.path.basename(file_path)
        mtime = datetime.fromtimestamp(os.path.getmtime(file_path), tz=timezone.utc)
        
        # Build structured R2 key path: logs/{YYYY}/{MM}/{DD}/{file_name}_{timestamp}.gz
        year_str = f"{mtime.year:04d}"
        month_str = f"{mtime.month:02d}"
        day_str = f"{mtime.day:02d}"
        time_str = mtime.strftime("%Y%m%d_%H%M%S")
        
        gz_filename = f"{file_name}_{time_str}.gz"
        r2_key = f"logs/{year_str}/{month_str}/{day_str}/{gz_filename}"
        
        temp_gz_path = file_path + ".gz"
        
        logger.info(f"Archiving '{file_name}' -> R2 Key: '{r2_key}'...")
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would compress '{file_name}', upload to s3://{bucket_name}/{r2_key}, and delete local copy.")
            continue

        try:
            # Compress file
            compress_file(file_path, temp_gz_path)
            
            # Upload to Cloudflare R2
            with open(temp_gz_path, "rb") as f_data:
                client.put_object(
                    Bucket=bucket_name,
                    Key=r2_key,
                    Body=f_data,
                    ContentType="application/gzip"
                )
            logger.info(f"✅ Successfully uploaded '{r2_key}' to R2 bucket '{bucket_name}'.")
            
            # Clean up local rotated log file and temporary .gz file
            os.remove(file_path)
            os.remove(temp_gz_path)
            logger.info(f"Cleaned up local file: {file_path}")
        except Exception as err:
            logger.error(f"❌ Failed to archive '{file_name}' to R2: {err}")
            if os.path.exists(temp_gz_path):
                os.remove(temp_gz_path)

    # Enforce R2 60-day Retention Lifecycle Purge
    logger.info(f"Checking Cloudflare R2 bucket '{bucket_name}' for logs older than {retention_days} days...")
    purge_cutoff = now_utc - timedelta(days=retention_days)
    
    try:
        paginator = client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=bucket_name, Prefix="logs/")
        
        purged_count = 0
        for page in page_iterator:
            for obj in page.get('Contents', []):
                last_modified = obj['LastModified']
                if last_modified < purge_cutoff:
                    obj_key = obj['Key']
                    if dry_run:
                        logger.info(f"[DRY-RUN] Would purge R2 log object older than {retention_days} days: '{obj_key}' (LastModified: {last_modified})")
                    else:
                        client.delete_object(Bucket=bucket_name, Key=obj_key)
                        logger.info(f"🗑️ Purged expired R2 log object (> {retention_days}d): '{obj_key}'")
                    purged_count += 1
                    
        if purged_count == 0:
            logger.info(f"No R2 log objects expired (older than {retention_days} days).")
        else:
            logger.info(f"R2 Log Lifecycle Cleanup: Purged {purged_count} expired log object(s).")
    except Exception as e:
        logger.error(f"Error during R2 log retention purge: {e}")

def main():
    parser = argparse.ArgumentParser(description="Archive rotated log files to Cloudflare R2 and enforce retention lifecycle.")
    parser.add_argument("--retention-days", type=int, default=60, help="Retention period in days before permanently purging logs from R2 (default: 60).")
    parser.add_argument("--dry-run", action="store_true", help="Simulate compression, upload, and purge actions without writing/deleting.")
    args = parser.parse_args()

    archive_and_upload_logs(retention_days=args.retention_days, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
