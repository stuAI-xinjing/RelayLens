"""Supported GPT and Claude target profiles for reports.

The target is an operator-selected claim. It is never treated as proof that a
gateway actually serves that model; the audit still needs a trusted reference
run for behavioral comparison.
"""

TARGETS = {
    "gpt-6-astra": {"family": "gpt", "label": "GPT-6 Astra", "tier": "flagship"},
    "gpt-6.1-sol": {"family": "gpt", "label": "GPT-6.1 Sol", "tier": "advanced"},
    "gpt-6-luna": {"family": "gpt", "label": "GPT-6 Luna", "tier": "efficient"},
    "gpt-5.6-sol": {"family": "gpt", "label": "GPT-5.6 Sol", "tier": "advanced"},
    "claude-opus-5": {"family": "claude", "label": "Claude Opus 5", "tier": "flagship"},
    "claude-sonnet-5": {"family": "claude", "label": "Claude Sonnet 5", "tier": "advanced"},
    "claude-opus-4-8": {"family": "claude", "label": "Claude Opus 4.8", "tier": "flagship"},
    "claude-opus-4-6": {"family": "claude", "label": "Claude Opus 4.6", "tier": "advanced"},
    "claude-sonnet-4-6": {"family": "claude", "label": "Claude Sonnet 4.6", "tier": "advanced"},
    "claude-haiku-4-5": {"family": "claude", "label": "Claude Haiku 4.5", "tier": "efficient"},
}

TARGET_CHOICES = tuple(TARGETS)


def profile(target_model: str):
    """Return a copied profile, or ``None`` for an unselected target."""
    if not target_model:
        return None
    item = TARGETS.get(target_model)
    return {"id": target_model, **item} if item else None
