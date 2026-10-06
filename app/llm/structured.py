"""Validated structured LLM output: parse -> Pydantic validate -> repair-retry -> fail safely."""
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMError
from app.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def structured_call(provider: LLMProvider, system: str, prompt: str, schema: type[T],
                    max_retries: int) -> T:
    current = prompt
    last = ""
    for _ in range(max_retries + 1):  # bounded: never infinite
        raw = provider.generate_json_text(system, current)
        try:
            return schema.model_validate_json(_FENCE.sub("", raw.strip()))
        except (ValidationError, ValueError) as exc:
            last = str(exc)[:400]
            current = (f"{prompt}\n\nYour previous output was invalid ({last}). "
                       "Return ONLY valid JSON matching the schema.")
    raise LLMError("LLM returned invalid structured output")
