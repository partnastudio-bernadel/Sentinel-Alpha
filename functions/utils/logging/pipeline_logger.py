import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler

# Suppress LangChain NVIDIA package warnings from cluttering the terminal
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_nvidia_ai_endpoints")

# Resolve logs directory relative to this file
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "..", "..", "logs"))

def log_to_file_only(logger: logging.Logger, level: int, message: str):
    """Emits a log message exclusively to FileHandlers (bypassing console stream handlers)."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            record = logger.makeRecord(
                logger.name, level, "(internal)", 0, message, None, None
            )
            handler.emit(record)

def get_pipeline_logger(domain: str = "sentiment") -> logging.Logger:
    """Configures and returns a shared pipeline logger using RotatingFileHandler.
    
    Args:
        domain: Logger domain ('sentiment' -> sentiment_pipeline.log, 'macro' -> macro_pipeline.log)
    """
    os.makedirs(_LOGS_DIR, exist_ok=True)
    
    clean_domain = (domain or "sentiment").lower().strip()
    logger_name = f"{clean_domain}_pipeline"
    log_filename = f"{clean_domain}_pipeline.log"
    log_path = os.path.join(_LOGS_DIR, log_filename)
    
    logger = logging.getLogger(logger_name)
    
    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Rotating File Handler (10MB max size, 3 backup files)
        try:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=3,
                encoding="utf-8"
            )
            file_formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Failed to setup rotating file log handler for {log_path}: {e}", file=sys.stderr)
            
        # Console Handler (clean progress output)
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(f"[{clean_domain.upper()}] %(message)s")
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
        
    return logger
