"""Caminhos e configurações globais da aplicação.

Três modos de execução:

* **Desenvolvimento** (``python main.py``): dados em ``<projeto>/data``.
* **Executável** (PyInstaller): recursos dentro do pacote e dados do usuário em
  ``%LOCALAPPDATA%/PokeXGames Hunt Analyzer`` (gravável e separado por usuário).
* **Portátil**: se existir uma pasta ``data`` ao lado do ``.exe``, os dados ficam
  nela (útil para levar o aplicativo e o histórico num pendrive).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "PokeXGames Hunt Analyzer"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppPaths:
    resources_dir: Path  # somente leitura (ícones)
    data_dir: Path  # gravável (banco, configurações, backups, logs)
    imports_dir: Path  # pasta inicial dos diálogos e destino dos JSONs colados
    portable: bool = False


def resolve_paths(frozen: bool, bundle_dir: Path | None, executable: Path,
                  local_app_data: str | None, project_root: Path = PROJECT_ROOT) -> AppPaths:
    """Decide os caminhos para o modo de execução (função pura, testável)."""
    if not frozen:
        return AppPaths(project_root / "resources", project_root / "data",
                        project_root / "imports")
    resources = (bundle_dir or executable.parent) / "resources"
    portable_data = executable.parent / "data"
    if portable_data.is_dir():
        return AppPaths(resources, portable_data, portable_data / "imports", portable=True)
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    data = base / APP_DIR_NAME
    return AppPaths(resources, data, data / "imports")


PATHS = resolve_paths(
    frozen=bool(getattr(sys, "frozen", False)),
    bundle_dir=Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else None,
    executable=Path(sys.executable),
    local_app_data=os.environ.get("LOCALAPPDATA"),
)

IS_FROZEN = bool(getattr(sys, "frozen", False))
DATA_DIR = PATHS.data_dir
IMPORTS_DIR = PATHS.imports_dir
RESOURCES_DIR = PATHS.resources_dir
ICONS_DIR = RESOURCES_DIR / "icons"
LOGS_DIR = DATA_DIR / "logs"

DEFAULT_DB_PATH = DATA_DIR / "hunts.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
BACKUPS_DIR_NAME = "backups"  # criada ao lado do arquivo do banco

# Permite apontar para outro banco sem alterar código (útil em desenvolvimento).
DB_PATH_ENV_VAR = "PXG_HUNTS_DB"


def database_path_from_env() -> Path | None:
    override = os.environ.get(DB_PATH_ENV_VAR)
    return Path(override).expanduser().resolve() if override else None


def get_database_path(configured: str | None = None) -> Path:
    """Banco em uso: variável de ambiente > configuração salva > banco padrão."""
    from_env = database_path_from_env()
    if from_env is not None:
        return from_env
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH


def backups_dir_for(database_path: Path) -> Path:
    return database_path.parent / BACKUPS_DIR_NAME
