import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

# Automatically load environment variables if present
project_root = Path(__file__).resolve().parents[3]
env_local = project_root / ".env.local"
env_default = project_root / ".env"
if env_local.exists():
    load_dotenv(env_local)
elif env_default.exists():
    load_dotenv(env_default)

logger = logging.getLogger(__name__)

_r2_client = None

def get_r2_client():
    """
    Initializes and returns a boto3 S3 client configured for Cloudflare R2.
    """
    global _r2_client
    if _r2_client is None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ImportError(
                "boto3 package is required for Cloudflare R2 storage. "
                "Please install it via 'pip install boto3'."
            )

        api_url = os.getenv("CLOUDFLARE_S3_API_URL", "").strip()
        access_key_id = os.getenv("CLOUDFLARE_S3_ACCESS_KEY_ID", "").strip()
        secret_access_key = os.getenv("CLOUDFLARE_S3_SECRET_ACCESS_KEY", "").strip()

        if not api_url or not access_key_id or not secret_access_key:
            logger.warning(
                "[R2 Storage] Missing Cloudflare R2 credentials in environment. "
                "Check CLOUDFLARE_S3_API_URL, CLOUDFLARE_S3_ACCESS_KEY_ID, CLOUDFLARE_S3_SECRET_ACCESS_KEY."
            )

        config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=10
        )

        _r2_client = boto3.client(
            "s3",
            endpoint_url=api_url if api_url.startswith("http") else f"https://{api_url}",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=config
        )
    return _r2_client

def get_r2_bucket_name() -> str:
    return os.getenv("CLOUDFLARE_S3_BUCKET", "sentinel-sentiment").strip()

def ensure_bucket_exists():
    """
    Ensures that the target Cloudflare R2 bucket exists.
    """
    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    try:
        client.head_bucket(Bucket=bucket_name)
    except Exception as e:
        logger.info(f"[R2 Storage] Bucket '{bucket_name}' not found or head failed. Creating bucket... ({e})")
        try:
            client.create_bucket(Bucket=bucket_name)
            logger.info(f"[R2 Storage] Bucket '{bucket_name}' successfully created.")
        except Exception as create_err:
            logger.error(f"[R2 Storage] Failed to create bucket '{bucket_name}': {create_err}")
            raise create_err

def generate_r2_key(art_id: str, date_str: Optional[str] = None) -> str:
    """
    Generates a structured S3/R2 key path: scored_articles/{YYYY}/{MM}/{DD}/{_id}.json
    """
    year, month, day = "2026", "01", "01"
    if date_str:
        try:
            # Handle standard formats: 'YYYY-MM-DD HH:MM:SS' or ISO format
            clean_date = date_str.replace("T", " ")
            dt = datetime.strptime(clean_date.split(".")[0], "%Y-%m-%d %H:%M:%S")
            year = f"{dt.year:04d}"
            month = f"{dt.month:02d}"
            day = f"{dt.day:02d}"
        except Exception:
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                year = f"{dt.year:04d}"
                month = f"{dt.month:02d}"
                day = f"{dt.day:02d}"
            except Exception:
                pass

    return f"scored_articles/{year}/{month}/{day}/{art_id}.json"

def upload_article_doc(doc: Dict[str, Any], date_str: Optional[str] = None) -> str:
    """
    Uploads a full article document dictionary as JSON to Cloudflare R2.
    Returns the R2 object key path.
    """
    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    art_id = doc.get("_id")
    if not art_id:
        raise ValueError("Document must contain an '_id' field for R2 storage.")

    effective_date = date_str or doc.get("date", "")
    key = generate_r2_key(art_id, effective_date)

    json_bytes = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")

    client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=json_bytes,
        ContentType="application/json"
    )
    logger.debug(f"[R2 Storage] Successfully uploaded '{art_id}' to R2 at '{key}' ({len(json_bytes)} bytes)")
    return key

def download_article_doc(r2_path: str) -> Dict[str, Any]:
    """
    Downloads and parses an article JSON document from Cloudflare R2 by key path.
    """
    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    response = client.get_object(Bucket=bucket_name, Key=r2_path)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)

def exists_in_r2(r2_path: str) -> bool:
    """
    Checks if an object exists in Cloudflare R2.
    """
    client = get_r2_client()
    bucket_name = get_r2_bucket_name()
    try:
        client.head_object(Bucket=bucket_name, Key=r2_path)
        return True
    except Exception:
        return False
