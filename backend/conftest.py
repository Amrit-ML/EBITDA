"""Makes the backend package importable from tests (config, core.*)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    """Every test saves diagnostics to its own temp folder, never the real
    chat_history/ in the project root."""
    import config

    monkeypatch.setattr(config, "HISTORY_DIR", tmp_path / "chat_history")


@pytest.fixture(autouse=True)
def no_live_model(monkeypatch):
    """Hard stop on live `claude` calls: tests must script the model.

    Code paths that fall back to the model (upload mapping) degrade quietly, so
    without this a test would silently spend money and pass.
    """
    from core import llm

    def blocked(*a, **kw):
        raise llm.LLMError("live model call blocked in tests")

    monkeypatch.setattr(llm, "complete", blocked)
