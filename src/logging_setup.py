"""
Logging configuration using loguru.
Provides structured logging with rotation and colorization.
"""
import sys
from pathlib import Path
from loguru import logger

from src.config import get_config, get_env_settings


def setup_logging() -> None:
    """
    Configure logging for the pipeline.
    Uses loguru with file rotation and retention.
    """
    config = get_config()
    env_settings = get_env_settings()
    
    # Remove default handler
    logger.remove()
    
    # Determine log level (env overrides config)
    log_level = env_settings.log_level or config.logging.level
    
    # Console handler with colors
    logger.add(
        sys.stderr,
        format=config.logging.format,
        level=log_level,
        colorize=config.logging.colorize,
    )
    
    # File handler with rotation
    log_file = Path(env_settings.log_file or config.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        str(log_file),
        format=config.logging.format,
        level=log_level,
        rotation=config.logging.rotation,
        retention=config.logging.retention,
        compression="zip",
        enqueue=True,  # Thread-safe
    )
    
    logger.info(f"Logging initialized at level {log_level}")
    logger.info(f"Log file: {log_file}")


def get_logger(name: str):
    """
    Get a logger instance with a specific name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logger.bind(name=name)
