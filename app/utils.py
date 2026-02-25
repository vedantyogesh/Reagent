"""
Shared utilities — validate_or_escalate and EscalationException.
Every layer that makes an LLM call uses validate_or_escalate().
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class EscalationException(Exception):
    """
    Raised when LLM output fails validation after max_retries attempts.
    Caught by flow_controller to transition session to FlowState.ESCALATED.
    """
    pass


def validate_or_escalate(
    raw: str | dict,
    schema: Type[T],
    max_retries: int = 2,
    retry_fn: Optional[Callable[[], str | dict]] = None,
) -> T:
    """
    Attempt to parse `raw` into `schema`. If parsing fails and retry_fn is
    provided, retry up to max_retries times. Raises EscalationException on
    final failure.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return schema(**data)
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_error = e
            if attempt < max_retries and retry_fn is not None:
                logger.warning(
                    "LLM output validation failed (attempt %d/%d): %s — retrying",
                    attempt + 1,
                    max_retries,
                    e,
                )
                raw = retry_fn()
            else:
                break

    raise EscalationException(
        f"LLM output failed {schema.__name__} validation after {max_retries} retries: {last_error}"
    )
