"""Atualização do executável pelos releases do GitHub.

Um programa em execução não pode substituir a própria pasta. Por isso, a instalação tem dois
processos:

1. A versão atual baixa o ``.zip`` do release, confere o SHA-256 informado pelo GitHub, extrai o
   pacote em ``updates/``, abre o ``.exe`` novo com ``--apply-update`` e fecha.
2. O ``.exe`` novo espera a versão atual fechar, troca os arquivos do programa e abre o
   programa já atualizado.

Só os arquivos que vêm no pacote são trocados: a pasta ``data`` do modo portátil, ou qualquer
outro arquivo do usuário ao lado do ``.exe``, continua onde está. Toda versão a partir da 1.6.0
precisa continuar aceitando ``--apply-update``.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from app.utils.constants import APP_NAME, APP_VERSION, GITHUB_REPOSITORY

API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPOSITORY}/releases/download/"
USER_AGENT = f"PokeXGames-Hunt-Analyzer/{APP_VERSION}"
APPLY_UPDATE_ARG = "--apply-update"
EXE_NAME = f"{APP_NAME}.exe"

CHECK_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 30
CHUNK_BYTES = 256 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 ** 3
WAIT_EXIT_SECONDS = 60
MOVE_ATTEMPTS = 20
MOVE_RETRY_SECONDS = 0.5

STAGING_DIR = ".update-new"
OLD_DIR = ".update-old"
# Nunca é trocada, mesmo se um pacote a trouxer: é onde ficam os dados do modo portátil.
PROTECTED_NAMES = frozenset({"data", STAGING_DIR, OLD_DIR})

ProgressCallback = Callable[[int, int], None]


class UpdateError(ValueError):
    """Falha na atualização, com a mensagem pronta para mostrar ao usuário."""


class UpdateCancelled(Exception):
    """O usuário cancelou o download."""


def parse_version(text: str) -> tuple[int, ...] | None:
    """``v1.10.0`` → ``(1, 10, 0)``; ``None`` se não for uma versão."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(candidate: tuple[int, ...], current: tuple[int, ...]) -> bool:
    size = max(len(candidate), len(current))
    return (*candidate, *[0] * (size - len(candidate))) > (*current, *[0] * (size - len(current)))


def asset_name(version: str) -> str:
    return f"PokeXGames-Hunt-Analyzer-{version}-windows.zip"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    notes: str
    page_url: str
    # Vazios se o release não tiver o pacote esperado: aí, só dá para abrir a página.
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""

    @property
    def installable(self) -> bool:
        return bool(self.asset_url and self.sha256 and self.asset_size > 0)


def parse_release(data: object, current_version: str = APP_VERSION) -> ReleaseInfo | None:
    """A versão publicada, se for mais nova que a atual."""
    if not isinstance(data, dict):
        raise UpdateError("O GitHub devolveu uma resposta inesperada.")
    tag = data.get("tag_name")
    version = parse_version(tag) if isinstance(tag, str) else None
    current = parse_version(current_version)
    if version is None or current is None:
        raise UpdateError("O GitHub devolveu uma resposta inesperada.")
    if data.get("draft") or data.get("prerelease") or not is_newer(version, current):
        return None
    text = tag.strip().removeprefix("v")
    notes = data.get("body")
    page = data.get("html_url")
    release = ReleaseInfo(
        text, notes if isinstance(notes, str) else "",
        page if isinstance(page, str) and page.startswith(f"https://github.com/{GITHUB_REPOSITORY}/")
        else RELEASES_URL)
    assets = data.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict) or asset.get("name") != asset_name(text):
            continue
        url, size, digest = asset.get("browser_download_url"), asset.get("size"), asset.get("digest")
        if (isinstance(url, str) and url.startswith(DOWNLOAD_PREFIX)
                and isinstance(size, int) and not isinstance(size, bool)
                and isinstance(digest, str)
                and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
            return ReleaseInfo(release.version, release.notes, release.page_url, url, size,
                               digest.removeprefix("sha256:").lower())
    return release


def _request(url: str) -> urllib.request.Request:
    # Identifica só o aplicativo: nenhum dado do usuário vai na requisição.
    return urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})


class UpdateService:
    def __init__(self, updates_dir: Path, current_version: str = APP_VERSION,
                 opener: Callable = urllib.request.urlopen) -> None:
        self.updates_dir = updates_dir
        self.current_version = current_version
        self._open = opener

    def check(self) -> ReleaseInfo | None:
        """A versão mais nova publicada, ou ``None`` se esta já for a mais recente."""
        try:
            with self._open(_request(API_URL), timeout=CHECK_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # o repositório ainda não tem release publicado
                return None
            raise UpdateError(f"O GitHub recusou a verificação (código {exc.code}). "
                              "Tente mais tarde.") from exc
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise UpdateError("Não foi possível falar com o GitHub. "
                              "Confira a internet e tente de novo.") from exc
        return parse_release(data, self.current_version)

    def download(self, release: ReleaseInfo, progress: ProgressCallback | None = None,
                 cancelled: Event | None = None) -> Path:
        """Baixa o pacote e confere o tamanho e o SHA-256."""
        if not release.installable:
            raise UpdateError("Este release não tem um pacote para instalar sozinho.")
        target = self.updates_dir / asset_name(release.version)
        partial = target.with_suffix(".part")
        digest = hashlib.sha256()
        received = 0
        try:
            self.updates_dir.mkdir(parents=True, exist_ok=True)
            with self._open(_request(release.asset_url),
                            timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, partial.open("wb") as file:
                while chunk := response.read(CHUNK_BYTES):
                    if cancelled is not None and cancelled.is_set():
                        raise UpdateCancelled
                    received += len(chunk)
                    if received > release.asset_size:
                        raise UpdateError("O download veio maior que o esperado e foi descartado.")
                    digest.update(chunk)
                    file.write(chunk)
                    if progress is not None:
                        progress(received, release.asset_size)
        except (UpdateCancelled, UpdateError):
            partial.unlink(missing_ok=True)
            raise
        except (OSError, http.client.HTTPException) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("O download foi interrompido. Confira a internet e o espaço em "
                              "disco, e tente de novo.") from exc
        if received != release.asset_size or digest.hexdigest() != release.sha256:
            partial.unlink(missing_ok=True)
            raise UpdateError("O arquivo baixado não confere com o publicado no GitHub e foi "
                              "descartado. Nada foi alterado.")
        partial.replace(target)
        return target

    def extract(self, archive: Path, version: str) -> Path:
        """Extrai o pacote e retorna a pasta com o ``.exe`` novo."""
        destination = self.updates_dir / version
        shutil.rmtree(destination, ignore_errors=True)
        try:
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                if sum(info.file_size for info in infos) > MAX_EXTRACTED_BYTES:
                    raise UpdateError("O pacote é grande demais para ser desta aplicação.")
                for info in infos:
                    parts = info.filename.replace("\\", "/").split("/")
                    if parts[0] != APP_NAME or ".." in parts or ":" in info.filename:
                        raise UpdateError("O pacote baixado tem um formato inesperado.")
                package.extractall(destination)
        except (OSError, zipfile.BadZipFile) as exc:
            raise UpdateError("Não foi possível extrair o pacote baixado.") from exc
        root = destination / APP_NAME
        if not (root / EXE_NAME).is_file():
            raise UpdateError("O pacote baixado não tem o executável do programa.")
        return root


# ------------------------------------------------------------- instalação


def can_install_itself(frozen: bool, executable: Path) -> bool:
    """Só o ``.exe`` com o nome original se atualiza; no código-fonte, o update é pelo git."""
    return frozen and executable.name == EXE_NAME


def ensure_writable(folder: Path) -> None:
    """Falha antes do download se o programa estiver em uma pasta sem permissão de escrita."""
    try:
        with tempfile.TemporaryFile(dir=folder):
            pass
    except OSError as exc:
        raise UpdateError(f"Sem permissão para alterar a pasta do programa ({folder}). Mova o "
                          "programa para Documentos ou baixe a versão nova pela página do "
                          "GitHub.") from exc


def child_environment(leaving_dir: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Ambiente de um programa aberto pelo ``.exe``: sem as bibliotecas da pasta dele.

    Sem isso, a versão nova herdaria o caminho e os plugins do Qt da versão antiga.
    """
    environment = dict(os.environ if environ is None else environ)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    folder = os.path.normcase(str(leaving_dir))
    environment["PATH"] = os.pathsep.join(
        entry for entry in environment.get("PATH", "").split(os.pathsep)
        if entry and os.path.normcase(entry) != folder
        and not os.path.normcase(entry).startswith(folder + os.sep))
    return environment


def _start_detached(arguments: list[str], cwd: Path, environment: dict[str, str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(arguments, cwd=cwd, env=environment, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def start_installer(new_root: Path, target: Path, pid: int) -> None:
    """Abre o ``.exe`` novo para instalar por cima de ``target``, assim que ``pid`` fechar."""
    try:
        _start_detached([str(new_root / EXE_NAME), APPLY_UPDATE_ARG, str(target), str(pid)],
                        new_root, child_environment(target))
    except OSError as exc:
        raise UpdateError(f"Não foi possível abrir o instalador: {exc}") from exc


def relaunch(target: Path, leaving_dir: Path) -> None:
    """Abre o programa instalado em ``target``."""
    _start_detached([str(target / EXE_NAME)], target, child_environment(leaving_dir))


def wait_for_exit(pid: int, timeout: float = WAIT_EXIT_SECONDS) -> bool:
    """Espera o processo fechar; ``False`` se ele continuar aberto depois do tempo limite."""
    if sys.platform != "win32":
        return True
    import ctypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True  # já fechou
    try:
        return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) != wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _move(source: Path, target: Path, *, attempts: int = MOVE_ATTEMPTS,
          delay: float = MOVE_RETRY_SECONDS) -> None:
    """Renomeia com novas tentativas: o antivírus pode segurar um arquivo por um instante."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def apply_update(source: Path, target: Path) -> None:
    """Troca os arquivos do programa em ``target`` pelos de ``source``.

    Primeiro copia tudo para dentro de ``target``, a parte demorada e que pode falhar sem causar
    dano. Depois só renomeia. Se algo falhar, devolve os arquivos antigos.
    """
    if not (source / EXE_NAME).is_file() or not (target / EXE_NAME).is_file():
        raise UpdateError("Não encontrei o executável do programa para atualizar.")
    if source.resolve() == target.resolve():
        raise UpdateError("A versão nova já está na pasta do programa.")
    names = [path.name for path in source.iterdir() if path.name not in PROTECTED_NAMES]
    staging, old = target / STAGING_DIR, target / OLD_DIR
    for folder in (staging, old):
        shutil.rmtree(folder, ignore_errors=True)
    try:
        staging.mkdir()
        old.mkdir()
        for name in names:
            path = source / name
            if path.is_dir():
                shutil.copytree(path, staging / name)
            else:
                shutil.copy2(path, staging / name)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        raise UpdateError(f"Não foi possível copiar a versão nova: {exc}") from exc

    moved_out: list[str] = []
    moved_in: list[str] = []
    try:
        for name in names:
            if (target / name).exists():
                _move(target / name, old / name)
                moved_out.append(name)
        for name in names:
            _move(staging / name, target / name)
            moved_in.append(name)
    except OSError as exc:
        try:
            for name in moved_in:
                _move(target / name, staging / name)
            for name in moved_out:
                _move(old / name, target / name)
        except OSError as restore_error:
            # Não apaga nada: os arquivos antigos continuam na pasta citada na mensagem.
            raise UpdateError("Não foi possível trocar os arquivos do programa nem devolver os "
                              f"antigos, que estão em {old}. Baixe a versão nova pela página do "
                              f"GitHub. ({restore_error})") from exc
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        raise UpdateError("Não foi possível trocar os arquivos do programa, e a versão anterior "
                          f"foi mantida. Feche outras janelas do programa e tente de novo. ({exc})"
                          ) from exc
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def clean_leftovers(updates_dir: Path, app_dir: Path) -> None:
    """Apaga o que sobrou de uma atualização; o que estiver em uso fica para a próxima abertura."""
    shutil.rmtree(updates_dir, ignore_errors=True)
    shutil.rmtree(app_dir / OLD_DIR, ignore_errors=True)
    shutil.rmtree(app_dir / STAGING_DIR, ignore_errors=True)
