"""
Structured JSON logging for production observability.
Outputs logs as JSON for easy ingestion by Datadog, Loki, ELK, etc.
"""
import logging
import sys
from pythonjsonlogger import jsonlogger

from app.core.config import settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["app"] = settings.APP_NAME
        log_record["version"] = settings.APP_VERSION
        log_record["env"] = settings.ENVIRONMENT
        log_record["level"] = record.levelname
        log_record["logger"] = record.name


def setup_logging():
    """Configure root logger with JSON output."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
