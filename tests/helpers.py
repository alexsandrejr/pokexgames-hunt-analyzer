"""Utilitários compartilhados pelos testes."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.database.database import Database

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HUNT_PATH = FIXTURES_DIR / "sample_hunt.json"


def load_sample() -> dict[str, Any]:
    return json.loads(SAMPLE_HUNT_PATH.read_text(encoding="utf-8"))


def sample_text(**session_overrides: Any) -> str:
    """JSON de exemplo com campos da ``Session`` sobrescritos."""
    data = copy.deepcopy(load_sample())
    data["Session"].update(session_overrides)
    return json.dumps(data)


def memory_database() -> Database:
    database = Database("sqlite://")
    database.create_schema()
    return database
