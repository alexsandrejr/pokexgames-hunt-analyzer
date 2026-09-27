"""Arquivos do Analyzer: busca em pastas e gravação de textos colados como ``.json``."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from app.services.json_importer import ParsedSession

FILENAME_PREFIX = "hunt"
# Extensões procuradas ao importar pastas.
ANALYZER_EXTENSIONS = (".json", ".tsv")


def suggested_filename(session: ParsedSession, now: datetime | None = None) -> str:
    """``hunt_1080_2026-09-26_15-24-20.json``; usa a hora atual se faltar o início."""
    moment = session.start_datetime or now or datetime.now()
    parts = [FILENAME_PREFIX]
    if session.session_id is not None:
        parts.append(str(session.session_id))
    parts.append(moment.strftime("%Y-%m-%d_%H-%M-%S"))
    return "_".join(parts) + ".json"


def collect_analyzer_files(paths: Iterable[str | Path]) -> list[Path]:
    """Expande pastas (com subpastas) em arquivos ``.json``/``.tsv``, sem repetições.

    Arquivos indicados diretamente entram com qualquer extensão (o importador
    informa se não forem JSON ou TSV válidos); em pastas, só ``.json``/``.tsv``.
    """
    found: dict[Path, None] = {}
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*"), key=lambda p: str(p).lower()):
                if child.is_file() and child.suffix.lower() in ANALYZER_EXTENSIONS:
                    found.setdefault(child.resolve())
        elif path.is_file():
            found.setdefault(path.resolve())
    return list(found)


def write_new_json_file(directory: Path, filename: str, text: str) -> Path:
    """Cria o arquivo sem sobrescrever: ``nome.json``, ``nome_2.json``, ``nome_3.json``..."""
    directory.mkdir(parents=True, exist_ok=True)
    base = Path(filename)
    counter = 1
    while True:
        name = base.name if counter == 1 else f"{base.stem}_{counter}{base.suffix}"
        path = directory / name
        try:
            with path.open("x", encoding="utf-8", newline="") as file:
                file.write(text)
            return path
        except FileExistsError:
            counter += 1
