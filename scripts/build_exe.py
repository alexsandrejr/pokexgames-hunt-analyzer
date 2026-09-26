"""Gera o executável do PokeXGames Hunt Analyzer para Windows.

Uso (na raiz do projeto, com o .venv ativo e ``pip install -r requirements-dev.txt``)::

    python scripts/build_exe.py            # pasta + .zip (recomendado)
    python scripts/build_exe.py --onefile  # um único .exe (abre mais devagar)

Etapas: ícone .ico → metadados do .exe → PyInstaller → teste do .exe gerado
(``--smoke-test``, com dados temporários) → .zip com LEIA-ME para distribuir.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils.constants import APP_NAME, APP_VERSION  # noqa: E402

BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
EXE_NAME = APP_NAME  # "PokeXGames Hunt Analyzer"
ZIP_NAME = f"PokeXGames-Hunt-Analyzer-{APP_VERSION}-windows.zip"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Contorno da Pokébola no ícone do .exe (no app, a cor acompanha o tema).
ICON_OUTLINE = "#1f2937"

# Bibliotecas que podem estar instaladas mas o app não usa (reduz o tamanho).
EXCLUDES = ("tkinter", "PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "IPython",
            "OpenGL", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml")


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


# ----------------------------------------------------------------------- ícone

def build_icon(target: Path) -> Path:
    """Renderiza o SVG do app em vários tamanhos e grava um .ico (entradas PNG)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    _app = QGuiApplication.instance() or QGuiApplication([])
    svg = (ROOT / "resources" / "icons" / "app.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.replace("#aeb6c4", ICON_OUTLINE).encode()))
    images = []
    for size in ICON_SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dimension = 0 if size >= 256 else size  # 0 significa 256 no formato ICO
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + entries + blobs)
    return target


# ------------------------------------------------------------------ metadados

def build_version_file(target: Path) -> Path:
    parts = [int(p) for p in APP_VERSION.split(".")] + [0] * 4
    version = tuple(parts[:4])
    text = f"""# Metadados exibidos em Propriedades > Detalhes do .exe
VSVersionInfo(
  ffi=FixedFileInfo(filevers={version}, prodvers={version}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', '{EXE_NAME}'),
      StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
"""
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------- PyInstaller

def run_pyinstaller(icon: Path, version_file: Path, onefile: bool) -> Path:
    separator = ";" if os.name == "nt" else ":"
    args = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "main.py"),
        "--name", EXE_NAME,
        "--windowed",  # sem janela de console
        "--noconfirm", "--clean",
        "--onefile" if onefile else "--onedir",
        "--icon", str(icon),
        "--version-file", str(version_file),
        "--add-data", f"{ROOT / 'resources'}{separator}resources",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "pyinstaller"),
        "--specpath", str(BUILD_DIR),
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    subprocess.run(args, check=True, cwd=ROOT)
    return DIST_DIR / (f"{EXE_NAME}.exe" if onefile else f"{EXE_NAME}/{EXE_NAME}.exe")


# ------------------------------------------------------------------ enxugar

# O app desenha tudo sem OpenGL (inclusive os gráficos): o OpenGL por software
# não é usado. Das traduções do Qt, só as de português são carregadas.
UNUSED_FILES = ("opengl32sw.dll",)
KEPT_TRANSLATIONS = ("qtbase_pt_BR.qm", "qt_pt_BR.qm")


def prune(app_dir: Path) -> int:
    """Remove arquivos sabidamente não usados; retorna os bytes liberados."""
    freed = 0
    qt_dir = app_dir / "_internal" / "PySide6"
    removable = [qt_dir / name for name in UNUSED_FILES]
    translations = qt_dir / "translations"
    if translations.is_dir():
        removable += [f for f in translations.iterdir() if f.name not in KEPT_TRANSLATIONS]
    for path in removable:
        if path.is_file():
            freed += path.stat().st_size
            path.unlink()
    return freed


# ------------------------------------------------------------------- verificação

def smoke_test(exe: Path) -> None:
    """Abre o .exe gerado (sem janela visível e com dados temporários) e visita as telas."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOCALAPPDATA=tmp,
                   PXG_HUNTS_DB=str(Path(tmp) / "smoke" / "hunts.db"))
        result = subprocess.run([str(exe), "--smoke-test"], env=env, timeout=180)
        log = Path(tmp) / APP_NAME / "logs" / "app.log"
        log_text = log.read_text(encoding="utf-8") if log.exists() else "(sem log)"
        problems = ("Tradução pt-BR do Qt não encontrada", "ERROR", "Traceback")
        if (result.returncode != 0 or "Smoke test concluído" not in log_text
                or any(problem in log_text for problem in problems)):
            print(log_text)
            raise SystemExit(f"O executável falhou no teste (código {result.returncode}).")
    print("Executável testado: abriu, visitou todas as telas e fechou sem erros.")


# ------------------------------------------------------------------- pacote

def package(onefile: bool) -> Path:
    target = DIST_DIR / ZIP_NAME
    source = DIST_DIR / (f"{EXE_NAME}.exe" if onefile else EXE_NAME)
    readme = ROOT / "scripts" / "LEIA-ME.txt"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        if onefile:
            archive.write(source, f"{EXE_NAME}/{source.name}")
        else:
            for path in sorted(source.rglob("*")):
                archive.write(path, f"{EXE_NAME}/{path.relative_to(source).as_posix()}")
        archive.write(readme, f"{EXE_NAME}/LEIA-ME.txt")
    return target


def folder_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else sum(
        p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="gera um único .exe")
    parser.add_argument("--skip-test", action="store_true", help="não testa o .exe gerado")
    options = parser.parse_args()

    step("Gerando ícone e metadados")
    icon = build_icon(BUILD_DIR / "app.ico")
    version_file = build_version_file(BUILD_DIR / "version_info.txt")

    step("Empacotando com PyInstaller (pode levar alguns minutos)")
    shutil.rmtree(DIST_DIR / EXE_NAME, ignore_errors=True)
    exe = run_pyinstaller(icon, version_file, options.onefile)
    if not options.onefile:
        freed = prune(DIST_DIR / EXE_NAME)
        print(f"Arquivos não usados removidos: {freed / 1_048_576:.0f} MB")

    if not options.skip_test:
        step("Testando o executável gerado")
        smoke_test(exe)

    step("Compactando para distribuir")
    archive = package(options.onefile)
    built = DIST_DIR / (f"{EXE_NAME}.exe" if options.onefile else EXE_NAME)
    print(f"\nPronto!\n  Executável: {exe}\n"
          f"  Tamanho:    {folder_size(built) / 1_048_576:.0f} MB\n"
          f"  Para enviar: {archive} ({archive.stat().st_size / 1_048_576:.0f} MB)")


if __name__ == "__main__":
    main()
