"""LiteLLM inference, response metadata, and ordered API-key failover."""

import re
import time
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.services.cache_service import configure_litellm_cache

SIMULATABLE_STATUSES = {429, 500, 502, 503}
DEFAULT_SYSTEM_PROMPT = "You are Lyftr AI, a helpful and concise assistant."


class ProvidersUnavailable(Exception):
    """Raised when every configured provider key is unavailable."""


@dataclass(frozen=True)
class InferenceResult:
    reply: str
    metadata: dict[str, Any]


def _usage_value(usage: Any, attribute: str, key: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(key, 0) or 0)
    return int(getattr(usage, attribute, 0) or 0)


def _cache_hit(response: Any) -> bool:
    hidden = getattr(response, "_hidden_params", None) or {}
    if isinstance(hidden, dict) and hidden.get("cache_hit"):
        return True
    return bool(getattr(response, "cache_hit", False))


def _status_code(error: Exception) -> int | None:
    for candidate in (getattr(error, "status_code", None), getattr(error, "status", None),
                      getattr(getattr(error, "response", None), "status_code", None)):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            pass
    return None


def _is_retryable(error: Exception) -> bool:
    status = _status_code(error)
    if status == 429 or status is not None and 500 <= status <= 599:
        return True
    name = type(error).__name__.lower()
    message = str(error).lower()
    return "quota" in message or "ratelimit" in name


def parse_simulated_failures(header: str | None) -> dict[str, int]:
    """Parse entries such as `key_1=429,*=503`, ignoring invalid entries."""
    failures: dict[str, int] = {}
    for item in (header or "").split(","):
        match = re.fullmatch(r"\s*(key_\d+|\*)\s*=\s*(\d{3})\s*", item)
        if not match:
            continue
        status = int(match.group(2))
        if status in SIMULATABLE_STATUSES:
            failures[match.group(1)] = status
    return failures


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        configure_litellm_cache(settings.cache_enabled, settings.cache_type)

    def complete(self, messages: list[dict[str, str]], simulated_failures: dict[str, int] | None = None) -> InferenceResult:
        if not self.settings.llm_api_keys:
            raise ProvidersUnavailable()
        import litellm

        start = time.perf_counter()
        simulated_failures = simulated_failures or {}
        simulation_applies = "*" in simulated_failures or any(
            f"key_{index}" in simulated_failures
            for index in range(1, len(self.settings.llm_api_keys) + 1)
        )
        model_name = self.settings.llm_model
        if "/" not in model_name:
            model_name = f"{self.settings.llm_provider}/{model_name}"
        for index, api_key in enumerate(self.settings.llm_api_keys, start=1):
            key_id = f"key_{index}"
            simulated_status = simulated_failures.get(key_id, simulated_failures.get("*"))
            if simulated_status is not None:
                if simulated_status in SIMULATABLE_STATUSES:
                    continue
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                    "api_key": api_key,
                    "caching": not simulation_applies,
                }
                if self.settings.llm_api_base:
                    kwargs["api_base"] = self.settings.llm_api_base
                response = litellm.completion(**kwargs)
            except Exception as exc:
                if _is_retryable(exc):
                    continue
                raise ProvidersUnavailable() from exc

            usage = getattr(response, "usage", None)
            choices = getattr(response, "choices", None)
            try:
                reply = choices[0].message.content
            except (AttributeError, IndexError, TypeError):
                raise ProvidersUnavailable()
            if not isinstance(reply, str):
                reply = ""
            cached = _cache_hit(response)
            latency_ms = max(0, int((time.perf_counter() - start) * 1000))
            model = getattr(response, "model", None) or model_name
            metadata = {
                "resolution_source": "LLM_CACHE" if cached else "LIVE_INFERENCE",
                "model": model,
                "latency_ms": latency_ms,
                "input_tokens": _usage_value(usage, "prompt_tokens", "prompt_tokens"),
                "output_tokens": _usage_value(usage, "completion_tokens", "completion_tokens"),
                "key_id": None if cached else key_id,
                "fallback_attempts": 0 if cached else index - 1,
            }
            return InferenceResult(reply=reply, metadata=metadata)
        raise ProvidersUnavailable()


def make_messages(history: list[dict[str, Any]] | None, message: str, system_prompt: str | None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}]
    for entry in history or []:
        messages.append({"role": entry["role"], "content": entry["content"]})
    messages.append({"role": "user", "content": message})
    return messages
