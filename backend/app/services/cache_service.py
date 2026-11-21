"""Configuration for LiteLLM's built-in response cache."""

_configured: tuple[bool, str] | None = None


def configure_litellm_cache(enabled: bool, cache_type: str = "local") -> None:
    """Enable LiteLLM's own cache; repeated identical setup is harmless."""
    global _configured
    if _configured == (enabled, cache_type):
        return
    try:
        import litellm
        if enabled:
            from litellm.caching import Cache
            litellm.cache = Cache(type=cache_type)
        else:
            litellm.cache = None
    except ImportError as exc:
        raise RuntimeError("LiteLLM is required for chat requests") from exc
    _configured = (enabled, cache_type)


def is_configured() -> bool:
    return bool(_configured and _configured[0])
