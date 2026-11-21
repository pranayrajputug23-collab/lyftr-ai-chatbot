"""Focused tests for LiteLLM response metadata and key failover mechanics."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import llm_service
from app.services.llm_service import LLMService, ProvidersUnavailable, parse_simulated_failures


def test_parse_failure_header_restricts_statuses():
    assert parse_simulated_failures("key_1=429,key_2=500,*=418") == {"key_1": 429, "key_2": 500}


@pytest.mark.parametrize("failure_status", [429, 500, 501, 502, 503, 504, 599])
def test_provider_rate_limit_or_server_error_fails_over_to_second_key(monkeypatch, failure_status):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs["api_key"] == "first":
            raise type("ProviderUnavailable", (Exception,), {"status_code": failure_status})("provider unavailable")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="real response"))],
            model="actual/model",
            usage=SimpleNamespace(prompt_tokens=24, completion_tokens=4),
            _hidden_params={},
        )

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("first", "second"), llm_model="provider/model", cache_enabled=False))
    result = service.complete([{"role": "user", "content": "hello"}])
    assert [call["api_key"] for call in calls] == ["first", "second"]
    assert result.reply == "real response"
    assert result.metadata["key_id"] == "key_2"
    assert result.metadata["fallback_attempts"] == 1
    assert result.metadata["input_tokens"] == 24


def test_all_provider_keys_failing_raises_generic_failure(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        raise type("ProviderError", (Exception,), {"status_code": 503})("private provider detail")

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("one", "two"), cache_enabled=False))
    try:
        service.complete([{"role": "user", "content": "hi"}])
    except ProvidersUnavailable:
        pass
    else:
        raise AssertionError("Expected all providers to fail")
    assert len(calls) == 2


def test_quota_exhaustion_fails_over_even_without_http_status(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs["api_key"] == "first":
            raise Exception("The provider quota has been exceeded")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="second-key response"))],
            model="actual/model",
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
            _hidden_params={},
        )

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("first", "second"), cache_enabled=False))
    result = service.complete([{"role": "user", "content": "hi"}])
    assert [call["api_key"] for call in calls] == ["first", "second"]
    assert result.metadata["fallback_attempts"] == 1


def test_simulated_key_one_failure_calls_second_key_and_counts_attempt(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="real response from second key"))],
            model="actual/model",
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
            _hidden_params={},
        )

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("first", "second"), cache_enabled=False))
    result = service.complete([{"role": "user", "content": "hi"}], {"key_1": 429})
    assert len(calls) == 1
    assert calls[0]["api_key"] == "second"
    assert result.reply == "real response from second key"
    assert result.metadata["key_id"] == "key_2"
    assert result.metadata["fallback_attempts"] == 1


def test_simulation_all_keys_failing_never_calls_provider(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("first", "second"), cache_enabled=False))
    try:
        service.complete([{"role": "user", "content": "hi"}], {"*": 429})
    except ProvidersUnavailable:
        pass
    else:
        raise AssertionError("Expected simulated unavailable providers")
    assert calls == []


def test_simulation_for_unconfigured_key_does_not_disable_cache(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="reply"))],
            model="actual/model",
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
            _hidden_params={},
        )

    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=completion))
    service = LLMService(Settings(llm_api_keys=("first", "second"), cache_enabled=True))
    service.complete([{"role": "user", "content": "hi"}], {"key_3": 429})
    assert calls[0]["caching"] is True


def test_litellm_cache_hit_preserves_usage_and_hides_key(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="cached reply"))],
        model="actual/model",
        usage=SimpleNamespace(prompt_tokens=30, completion_tokens=6),
        _hidden_params={"cache_hit": True},
    )
    monkeypatch.setattr(llm_service, "configure_litellm_cache", lambda *_: None)
    monkeypatch.setitem(__import__("sys").modules, "litellm", SimpleNamespace(completion=lambda **_: response))
    service = LLMService(Settings(llm_api_keys=("one",), cache_enabled=False))
    result = service.complete([{"role": "user", "content": "hi"}])
    assert result.metadata["resolution_source"] == "LLM_CACHE"
    assert result.metadata["key_id"] is None
    assert result.metadata["fallback_attempts"] == 0
    assert result.metadata["input_tokens"] == 30
    assert result.metadata["output_tokens"] == 6


def test_litellm_builtin_cache_reuses_matching_prompt_without_provider_call():
    """Exercise LiteLLM's local cache directly using its built-in mock completion."""
    import uuid
    import litellm
    from app.services.cache_service import configure_litellm_cache

    configure_litellm_cache(True, "local")
    unique = uuid.uuid4().hex
    messages = [{"role": "system", "content": "cache integration"}, {"role": "user", "content": unique}]
    first = litellm.completion(
        model="openai/gpt-4o-mini", messages=messages, api_key="test-only", caching=True,
        mock_response="cached answer " + unique,
    )
    repeated = litellm.completion(
        model="openai/gpt-4o-mini", messages=messages, api_key="test-only", caching=True,
        mock_response="should not be used " + unique,
    )
    different = litellm.completion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "system", "content": "cache integration"}, {"role": "user", "content": unique + " different"}],
        api_key="test-only", caching=True, mock_response="different answer " + unique,
    )
    assert first.choices[0].message.content == repeated.choices[0].message.content
    assert repeated._hidden_params.get("cache_hit") is True
    assert repeated.usage.prompt_tokens == first.usage.prompt_tokens
    assert repeated.usage.completion_tokens == first.usage.completion_tokens
    assert different.choices[0].message.content != first.choices[0].message.content
