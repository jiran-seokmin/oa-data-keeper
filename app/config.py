"""Runtime configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_dotenv(path: str | Path = ENV_PATH) -> None:
    """Load simple KEY=VALUE pairs from .env without overriding shell env."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def llm_provider() -> str:
    provider = os.environ.get("ACE_PROVIDER", "").strip().lower()
    if provider:
        return provider
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "gemini"


def llm_model() -> str:
    configured = os.environ.get("ACE_MODEL")
    if configured:
        return configured
    if llm_provider() == "gemini":
        return "gemini-2.5-flash"
    return "claude-opus-4-8"


def has_llm_credentials() -> bool:
    provider = llm_provider()
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False
