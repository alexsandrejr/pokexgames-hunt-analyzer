"""Preferências do usuário, gravadas em ``data/settings.json``.

O arquivo é lido de forma tolerante: se estiver ausente, corrompido ou com
valores inválidos, os padrões são usados, e o aplicativo abre normalmente.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from app.utils.formatters import NUMBER_FORMATS

THEMES = {"dark": "Escuro", "light": "Claro"}
MIN_BACKUPS_TO_KEEP, MAX_BACKUPS_TO_KEEP = 1, 100


@dataclass(frozen=True)
class AppSettings:
    theme: str = "dark"
    number_format: str = "pt-BR"
    database_path: str | None = None  # None: banco padrão (ver app/config.py)
    auto_backup: bool = True
    backups_to_keep: int = 10

    def validated(self) -> AppSettings:
        """Troca valores inválidos pelos padrões."""
        default = AppSettings()
        keep = self.backups_to_keep
        return replace(
            self,
            theme=self.theme if self.theme in THEMES else default.theme,
            number_format=(self.number_format if self.number_format in NUMBER_FORMATS
                           else default.number_format),
            database_path=(self.database_path.strip() or None
                           if isinstance(self.database_path, str) else None),
            auto_backup=self.auto_backup if isinstance(self.auto_backup, bool)
            else default.auto_backup,
            backups_to_keep=(keep if isinstance(keep, int) and not isinstance(keep, bool)
                             and MIN_BACKUPS_TO_KEEP <= keep <= MAX_BACKUPS_TO_KEEP
                             else default.backups_to_keep),
        )


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSettings:
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return AppSettings()
        if not isinstance(data, dict):
            return AppSettings()
        known = {f.name for f in fields(AppSettings)}
        return AppSettings(**{k: v for k, v in data.items() if k in known}).validated()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings.validated()), indent=2,
                                        ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)  # troca atômica: nunca deixa o arquivo pela metade
