"""Backup e restauração do banco SQLite.

As cópias usam a API de backup do próprio SQLite, que gera um arquivo
consistente mesmo com o aplicativo aberto. Restaurar sempre cria antes um
backup de segurança do banco atual.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app.database.database import Database

BACKUP_PREFIX = "hunts_backup_"
BACKUP_SUFFIX = ".db"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


class BackupKind:
    """Etiquetas no nome do arquivo, que indicam a origem do backup."""

    MANUAL = "manual"
    AUTOMATIC = "auto"
    BEFORE_RESTORE = "antes-restauracao"
    BEFORE_MIGRATION = "antes-atualizacao"

    LABELS = {MANUAL: "Manual", AUTOMATIC: "Automático",
              BEFORE_RESTORE: "Antes de restaurar", BEFORE_MIGRATION: "Antes de atualizar"}


class BackupError(Exception):
    """Falha de backup/restauração com mensagem pronta para o usuário."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: datetime
    kind: str
    size_bytes: int

    @property
    def kind_label(self) -> str:
        return BackupKind.LABELS.get(self.kind, self.kind)


def _copy_sqlite(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def inspect_backup(path: Path) -> int:
    """Confere se o arquivo é um banco do aplicativo e retorna quantas Hunts tem."""
    if not path.is_file():
        raise BackupError(f"Arquivo não encontrado: {path}")
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "hunt_sessions" not in tables:
                raise BackupError("O arquivo não é um banco do PokeXGames Hunt Analyzer.")
            return connection.execute("SELECT COUNT(*) FROM hunt_sessions").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"O arquivo não é um banco SQLite válido ({exc}).") from exc


class BackupService:
    def __init__(self, database: Database, backups_dir: Path) -> None:
        self.database = database
        self.backups_dir = backups_dir

    @property
    def database_path(self) -> Path:
        path = self.database.file_path
        if path is None:
            raise BackupError("O banco atual não é um arquivo (banco em memória).")
        return path

    # ----------------------------------------------------------------- backup

    def create_backup(self, kind: str = BackupKind.MANUAL,
                      destination: Path | None = None) -> Path:
        """Copia o banco para ``destination`` ou para a pasta de backups."""
        if destination is None:
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            destination = self._unique_path(kind)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination.unlink()
        try:
            _copy_sqlite(self.database_path, destination)
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Não foi possível criar o backup: {exc}") from exc
        return destination

    def _unique_path(self, kind: str) -> Path:
        stamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        path = self.backups_dir / f"{BACKUP_PREFIX}{stamp}_{kind}{BACKUP_SUFFIX}"
        counter = 2
        while path.exists():
            path = self.backups_dir / f"{BACKUP_PREFIX}{stamp}_{kind}_{counter}{BACKUP_SUFFIX}"
            counter += 1
        return path

    def list_backups(self) -> list[BackupInfo]:
        """Backups da pasta padrão, do mais recente para o mais antigo."""
        if not self.backups_dir.is_dir():
            return []
        backups = []
        for path in self.backups_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"):
            info = self._parse_name(path)
            if info is not None:
                backups.append(info)
        return sorted(backups, key=lambda b: (b.created_at, b.path.name), reverse=True)

    @staticmethod
    def _parse_name(path: Path) -> BackupInfo | None:
        body = path.name[len(BACKUP_PREFIX):-len(BACKUP_SUFFIX)]
        stamp, _, rest = body[:19], body[19:20], body[20:]
        try:
            created_at = datetime.strptime(stamp, TIMESTAMP_FORMAT)
        except ValueError:
            return None
        kind = rest.rsplit("_", 1)[0] if rest.rsplit("_", 1)[-1].isdigit() else rest
        return BackupInfo(path, created_at, kind or BackupKind.MANUAL, path.stat().st_size)

    def prune_automatic(self, keep: int) -> list[Path]:
        """Mantém só os ``keep`` backups automáticos mais recentes."""
        automatic = [b for b in self.list_backups() if b.kind == BackupKind.AUTOMATIC]
        removed = []
        for backup in automatic[max(0, keep):]:
            backup.path.unlink(missing_ok=True)
            removed.append(backup.path)
        return removed

    def automatic_backup_if_due(self, keep: int, today: date | None = None) -> Path | None:
        """No máximo um backup automático por dia (e só se houver dados)."""
        today = today or date.today()
        if any(b.kind == BackupKind.AUTOMATIC and b.created_at.date() == today
               for b in self.list_backups()):
            return None
        if inspect_backup(self.database_path) == 0:
            return None
        path = self.create_backup(BackupKind.AUTOMATIC)
        self.prune_automatic(keep)
        return path

    # -------------------------------------------------------------- restauração

    def restore(self, source: Path) -> Path:
        """Substitui o banco atual pelo backup; retorna o backup de segurança criado."""
        source = source.resolve()
        inspect_backup(source)
        if source == self.database_path.resolve():
            raise BackupError("Este arquivo já é o banco em uso.")
        safety = self.create_backup(BackupKind.BEFORE_RESTORE)
        self.database.dispose()  # fecha as conexões antes de sobrescrever
        try:
            _copy_sqlite(source, self.database_path)
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Falha ao restaurar ({exc}). O banco anterior foi "
                              f"preservado em {safety}.") from exc
        self.database.create_schema()  # backups antigos são migrados para a versão atual
        return safety
