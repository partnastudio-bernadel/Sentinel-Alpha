import logging
import os
import sys
import warnings

# Suppress LangChain NVIDIA package warnings from cluttering the terminal
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_nvidia_ai_endpoints")

# Resolve logs directory relative to this file
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "..", "..", "logs"))
_LOG_FILE = os.path.join(_LOGS_DIR, "pipeline.log")

def log_to_file_only(logger: logging.Logger, level: int, message: str):
    """Emits a log message exclusively to FileHandlers (bypassing console stream handlers)."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            record = logger.makeRecord(
                logger.name, level, "(internal)", 0, message, None, None
            )
            handler.emit(record)

def get_pipeline_logger() -> logging.Logger:
    """Configures and returns a shared pipeline logger writing to logs/pipeline.log and console."""
    os.makedirs(_LOGS_DIR, exist_ok=True)
    
    logger = logging.getLogger("sentiment_pipeline")
    
    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # File Handler (detailed formatting)
        try:
            file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
            file_formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Failed to setup file log handler: {e}", file=sys.stderr)
            
        # Console Handler (clean progress output)
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter("[+] %(message)s")
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
        
    return logger
