"""Target claims and documented API settings, never invented IQ thresholds."""
CATALOG_CHECKED = "2026-10-26"
OPENAI_SOURCE = "https://developers.openai.com/api/docs/models"
CLAUDE_SOURCE = "https://platform.claude.com/docs/en/models/overview"

TARGETS = {
    "gpt-6-astra": {"family": "gpt", "label": "GPT-6 Astra", "tier": "flagship"},
    "gpt-6.1-sol": {"family": "gpt", "label": "GPT-6.1 Sol", "tier": "advanced"},
    "gpt-6-luna": {"family": "gpt", "label": "GPT-6 Luna", "tier": "efficient"},
    "claude-fable-5-1": {"family": "claude", "label": "Claude Fable 5.1", "tier": "flagship"},
    "claude-opus-5-5": {"family": "claude", "label": "Claude Opus 5.5", "tier": "flagship"},
    "claude-sonnet-5-5": {"family": "claude", "label": "Claude Sonnet 5.5", "tier": "advanced"},
    "claude-haiku-5-5": {"family": "claude", "label": "Claude Haiku 5.5", "tier": "efficient"},
    "gpt-5.6-sol": {"family": "gpt", "label": "GPT-5.6 Sol", "tier": "legacy"},
    "claude-opus-5": {"family": "claude", "label": "Claude Opus 5", "tier": "legacy"},
    "claude-sonnet-5": {"family": "claude", "label": "Claude Sonnet 5", "tier": "legacy"},
    "claude-opus-4-8": {"family": "claude", "label": "Claude Opus 4.8", "tier": "legacy"},
    "claude-opus-4-6": {"family": "claude", "label": "Claude Opus 4.6", "tier": "legacy"},
    "claude-sonnet-4-6": {"family": "claude", "label": "Claude Sonnet 4.6", "tier": "legacy"},
    "claude-haiku-4-5": {"family": "claude", "label": "Claude Haiku 4.5", "tier": "legacy"},
}
TARGET_CHOICES = tuple(TARGETS)


def profile(target_model):
    if not target_model:
        return None
    item = TARGETS.get(target_model)
    if item is None:
        family = "gpt" if target_model.startswith("gpt-") else "claude" if target_model.startswith("claude-") else None
        if family is None:
            return None
        item = {"family": family, "label": target_model, "tier": "custom"}
    return {"id": target_model, **item}


def known_efforts(target_model, api):
    if api == "messages":
        return ("low", "medium", "high", "max")
    if target_model in ("gpt-6-astra", "gpt-6.1-sol"):
        return ("low", "medium", "high", "xhigh", "max")
    if target_model == "gpt-6-luna":
        return ("none", "low", "medium", "high", "xhigh", "max")
    return None
