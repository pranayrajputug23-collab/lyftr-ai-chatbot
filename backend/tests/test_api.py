"""Contract and persistence tests using a deterministic mocked LLM service."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.llm_service import InferenceResult, ProvidersUnavailable


class FakeLLM:
    def __init__(self, fail_all: bool = False):
        self.fail_all = fail_all
        self.calls = []
        self.cache = {}

    def complete(self, messages, simulated_failures=None):
        self.calls.append((messages, simulated_failures or {}))
        if self.fail_all or simulated_failures and "*" in simulated_failures:
            raise ProvidersUnavailable()
        # The fake is intentionally test-only; key off the full prompt and omit session ID.
        cache_key = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        if cache_key in self.cache and not simulated_failures:
            metadata = dict(self.cache[cache_key][1])
            metadata.update(resolution_source="LLM_CACHE", key_id=None, fallback_attempts=0, latency_ms=1)
            return InferenceResult(self.cache[cache_key][0], metadata)
        reply = f"Mock reply {len(self.calls)}"
        metadata = {
            "resolution_source": "LIVE_INFERENCE",
            "model": "mock/model",
            "latency_ms": 12,
            "input_tokens": len(json.dumps(messages)),
            "output_tokens": 3,
            "key_id": "key_1",
            "fallback_attempts": 0,
        }
        if not simulated_failures:
            self.cache[cache_key] = (reply, metadata)
        return InferenceResult(reply, metadata)


@pytest.fixture
def setup_client(tmp_path):
    fake = FakeLLM()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        llm_api_keys=("test-one", "test-two"),
        llm_model="mock/model",
        enable_failure_simulation=True,
    )
    application = create_app(settings, fake)
    with TestClient(application) as client:
        yield client, fake


def test_api_exposes_exactly_the_three_required_paths(tmp_path):
    application = create_app(
        Settings(database_url=f"sqlite:///{tmp_path / 'paths.db'}", llm_api_keys=("one", "two")),
        FakeLLM(),
    )
    assert set(application.openapi()["paths"]) == {
        "/health", "/chat", "/sessions/{session_id}/messages"
    }


def test_health_reports_ready_state(setup_client):
    client, _ = setup_client
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_valid_chat_persists_and_returns_required_metadata(setup_client):
    client, _ = setup_client
    response = client.post("/chat", json={"session_id": "s-1", "message": "Hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-1"
    assert body["reply"].startswith("Mock reply")
    assert set(body["metadata"]) == {
        "resolution_source", "model", "latency_ms", "input_tokens", "output_tokens", "key_id", "fallback_attempts"
    }
    assert [item["role"] for item in client.get("/sessions/s-1/messages").json()["messages"]] == ["user", "assistant"]


def test_missing_session_id_is_422(setup_client):
    client, _ = setup_client
    assert client.post("/chat", json={"message": "hi"}).status_code == 422


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_message_is_422(setup_client, message):
    client, _ = setup_client
    assert client.post("/chat", json={"session_id": "s", "message": message}).status_code == 422


def test_message_over_4000_trimmed_characters_is_422(setup_client):
    client, _ = setup_client
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4001}).status_code == 422


def test_message_length_is_measured_after_trimming(setup_client):
    client, _ = setup_client
    assert client.post("/chat", json={"session_id": "s", "message": "  " + "x" * 4000 + "  "}).status_code == 200


def test_multiturn_history_is_sent_to_model(setup_client):
    client, fake = setup_client
    client.post("/chat", json={"session_id": "multi", "message": "First", "system_prompt": "Be concise"})
    client.post("/chat", json={"session_id": "multi", "message": "Second"})
    messages = fake.calls[-1][0]
    assert messages == [
        {"role": "system", "content": "You are Lyftr AI, a helpful and concise assistant."},
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Mock reply 1"},
        {"role": "user", "content": "Second"},
    ]
    assert fake.calls[0][0][0]["content"] == "Be concise"


def test_sessions_are_isolated(setup_client):
    client, _ = setup_client
    client.post("/chat", json={"session_id": "one", "message": "private"})
    response = client.post("/chat", json={"session_id": "two", "message": "new"})
    assert [entry["content"] for entry in client.get("/sessions/two/messages").json()["messages"]] == ["new", response.json()["reply"]]


def test_history_oldest_first_and_unknown_session_404(setup_client):
    client, _ = setup_client
    client.post("/chat", json={"session_id": "ordered", "message": "one"})
    client.post("/chat", json={"session_id": "ordered", "message": "two"})
    history = client.get("/sessions/ordered/messages").json()["messages"]
    assert [message["role"] for message in history] == ["user", "assistant", "user", "assistant"]
    assert "metadata" not in history[0]
    assert history[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert client.get("/sessions/missing/messages").json() == {"detail": "session not found"}


def test_identical_first_messages_hit_cache_across_sessions(setup_client):
    client, fake = setup_client
    first = client.post("/chat", json={"session_id": "cache-a", "message": "Same prompt"}).json()
    second = client.post("/chat", json={"session_id": "cache-b", "message": "Same prompt"}).json()
    assert second["reply"] == first["reply"]
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]


def test_real_litellm_cache_through_chat_endpoint_ignores_session_and_includes_system_prompt(tmp_path, monkeypatch):
    """Use LiteLLM's actual local cache while mocking only the provider response."""
    import litellm

    from app.services.llm_service import LLMService

    actual_completion = litellm.completion
    completion_call_count = 0
    provider_call_count = 0

    def mocked_provider(**kwargs):
        nonlocal completion_call_count, provider_call_count
        completion_call_count += 1
        prompt_message = kwargs["messages"][-1]["content"]
        response = actual_completion(
            **kwargs,
            mock_response=f"provider response {completion_call_count} for {prompt_message}",
        )
        if not response._hidden_params.get("cache_hit"):
            provider_call_count += 1
        return response

    monkeypatch.setattr(litellm, "completion", mocked_provider)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'real-cache.db'}",
        llm_api_keys=("test-only-key-1", "test-only-key-2"),
        llm_model="openai/gpt-4o-mini",
        cache_enabled=True,
    )
    service = LLMService(settings)
    with TestClient(create_app(settings, service)) as client:
        first = client.post("/chat", json={"session_id": "real-cache-a", "message": "Repeat me"}).json()
        repeated = client.post("/chat", json={"session_id": "real-cache-b", "message": "Repeat me"}).json()
        changed_system = client.post(
            "/chat",
            json={"session_id": "real-cache-c", "message": "Repeat me", "system_prompt": "Answer in one word."},
        ).json()

    assert first["reply"] == repeated["reply"]
    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert repeated["metadata"]["resolution_source"] == "LLM_CACHE"
    assert repeated["metadata"]["key_id"] is None
    assert repeated["metadata"]["fallback_attempts"] == 0
    assert repeated["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert repeated["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]
    assert changed_system["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert changed_system["reply"] != first["reply"]
    assert provider_call_count == 2  # The repeated first message is served by LiteLLM's cache.
    assert completion_call_count == 3
    assert "test-only-key" not in str([first, repeated, changed_system])


def test_different_messages_do_not_hit_cache(setup_client):
    client, _ = setup_client
    client.post("/chat", json={"session_id": "a", "message": "Prompt A"})
    response = client.post("/chat", json={"session_id": "b", "message": "Prompt B"})
    assert response.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_all_keys_failure_returns_503_and_saves_nothing(setup_client):
    client, _ = setup_client
    response = client.post("/chat", headers={"X-Simulate-Failure": "*=429"}, json={"session_id": "fail", "message": "hi"})
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/fail/messages").status_code == 404


def test_key_failure_simulation_can_fall_through(setup_client):
    client, fake = setup_client
    response = client.post("/chat", headers={"X-Simulate-Failure": "key_1=429"}, json={"session_id": "fallback", "message": "hi"})
    assert response.status_code == 200
    assert fake.calls[-1][1] == {"key_1": 429}


def test_simulation_disabled_ignores_header(tmp_path):
    fake = FakeLLM()
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'disabled.db'}", llm_api_keys=("one", "two"), enable_failure_simulation=False)
    with TestClient(create_app(settings, fake)) as client:
        response = client.post("/chat", headers={"X-Simulate-Failure": "*=429"}, json={"session_id": "s", "message": "hi"})
    assert response.status_code == 200
    assert fake.calls[0][1] == {}

