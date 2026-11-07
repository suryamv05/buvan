import logging
import re

import structlog

_SENSITIVE = re.compile(r"(?i)(bearer\s+|password[=: ]+|token[=: ]+|email[=: ]+)[^\s,]+")


def redact(_: object, __: str, event_dict: dict[str, object]) -> dict[str, object]:
    for key, value in tuple(event_dict.items()):
        if any(word in key.lower() for word in ("password", "token", "email", "secret")):
            event_dict[key] = "[REDACTED]"
        elif isinstance(value, str):
            event_dict[key] = _SENSITIVE.sub(r"\1[REDACTED]", value)
    return event_dict


def configure_logging() -> None:
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, redact, structlog.processors.add_log_level,
                                   structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()],
                        logger_factory=structlog.stdlib.LoggerFactory())
    logging.basicConfig(level=logging.INFO)
