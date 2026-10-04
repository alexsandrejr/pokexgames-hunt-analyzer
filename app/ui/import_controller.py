"""Fluxo de importação na interface: arquivos, pastas, arrastar e soltar e JSON/TSV colado.

* Um único arquivo: em caso de duplicidade, o usuário decide (Cancelar/Importar).
* Vários arquivos (seleção múltipla, pasta ou arrastar e soltar): duplicatas são
  ignoradas sem perguntar e aparecem no resumo final; com muitos arquivos, uma
  barra de progresso permite cancelar.

A categoria das sessões vem de ``category_provider`` (a janela principal informa a
aba de Bosses aberta); ``None`` deixa o ``HuntService`` decidir (pasta, inimigos ou Hunt).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QWidget

from app.config import IMPORTS_DIR
from app.services.categories import Category, category_dir
from app.services.dto import ImportResult, ImportStatus
from app.services.hunt_service import HuntService
from app.services.json_files import ANALYZER_EXTENSIONS, collect_analyzer_files
from app.ui.hunts.paste_json_dialog import PasteJsonDialog

ANALYZER_FILE_FILTER = ("Analyzer (*.json *.tsv *.txt);;JSON (*.json);;TSV (*.tsv *.txt);;"
                        "Todos os arquivos (*)")
PROGRESS_THRESHOLD = 5  # a partir de quantos arquivos mostrar a barra de progresso
MAX_REPORT_LINES = 15


def dropped_paths(mime: QMimeData) -> list[Path]:
    """Arquivos .json/.tsv e pastas locais de um arrastar e soltar."""
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.is_dir() or (path.is_file() and path.suffix.lower() in ANALYZER_EXTENSIONS):
            paths.append(path)
    return paths


class ImportController(QObject):
    hunts_imported = Signal(list)  # ids das Hunts criadas
    status_message = Signal(str)

    def __init__(self, service: HuntService, parent_widget: QWidget,
                 paste_save_dir: Path = IMPORTS_DIR) -> None:
        super().__init__(parent_widget)
        self._service = service
        self._parent = parent_widget
        # Pasta onde os textos colados são salvos como arquivo .json (bosses: subpastas).
        self.paste_save_dir = paste_save_dir
        # Categoria em que as próximas importações devem entrar (None: automática).
        self.category_provider: Callable[[], Category | None] = lambda: None

    @staticmethod
    def _start_dir() -> str:
        return str(IMPORTS_DIR if IMPORTS_DIR.exists() else Path.home())

    def choose_and_import(self) -> list[ImportResult]:
        paths, _ = QFileDialog.getOpenFileNames(
            self._parent, "Importar JSON/TSV do Analyzer", self._start_dir(),
            ANALYZER_FILE_FILTER)
        return self.import_paths(paths) if paths else []

    def choose_folder_and_import(self) -> list[ImportResult]:
        folder = QFileDialog.getExistingDirectory(
            self._parent, "Importar todos os JSON/TSV de uma pasta", self._start_dir())
        return self.import_paths([folder]) if folder else []

    def import_paths(self, paths: Iterable[str | Path]) -> list[ImportResult]:
        """Importa arquivos e pastas (as pastas são percorridas com subpastas)."""
        files = collect_analyzer_files(paths)
        if not files:
            self.show_batch_report("Nenhum arquivo .json ou .tsv foi encontrado.", [])
            return []
        category = self.category_provider()
        if len(files) == 1:
            results = [self._import_confirming_duplicate(
                lambda force: self._service.import_file(files[0], allow_duplicate=force,
                                                        category=category))]
            cancelled = False
        else:
            results, cancelled = self._import_batch(files, category)
        self._finish(results, cancelled)
        return results

    def _import_batch(self, files: Sequence[Path],
                      category: Category | None) -> tuple[list[ImportResult], bool]:
        progress = None
        if len(files) >= PROGRESS_THRESHOLD:
            progress = QProgressDialog("Importando Hunts…", "Cancelar", 0, len(files),
                                       self._parent)
            progress.setWindowTitle("Importação")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(300)
        results: list[ImportResult] = []
        for index, path in enumerate(files):
            if progress is not None:
                progress.setLabelText(f"Importando {index + 1} de {len(files)}: {path.name}")
                progress.setValue(index)
                if progress.wasCanceled():
                    break
            # Duplicatas: ignoradas.
            results.append(self._service.import_file(path, category=category))
        cancelled = len(results) < len(files)
        if progress is not None:
            progress.setValue(len(files))
        return results, cancelled

    def paste_and_import(self) -> ImportResult | None:
        category = self.category_provider()
        save_dir = (category_dir(self.paste_save_dir, category) if category is not None
                    else self.paste_save_dir)
        dialog = PasteJsonDialog(save_dir, self._parent, category)
        if dialog.exec() != PasteJsonDialog.DialogCode.Accepted:
            return None
        return self.import_pasted(dialog.text())

    def import_pasted(self, text: str) -> ImportResult:
        """Importa o texto colado (JSON ou TSV); se importado, também vira um arquivo .json."""
        category = self.category_provider()
        result = self._import_confirming_duplicate(
            lambda force: self._service.import_pasted_text(
                text, self.paste_save_dir, allow_duplicate=force, category=category
            )
        )
        self._finish([result])
        return result

    def _import_confirming_duplicate(
        self, do_import: Callable[[bool], ImportResult]
    ) -> ImportResult:
        result = do_import(False)
        if result.status == ImportStatus.DUPLICATE and self.confirm_duplicate(result):
            result = do_import(True)
        return result

    def _finish(self, results: Sequence[ImportResult], cancelled: bool = False) -> None:
        if results:
            self._report(results, cancelled)
        imported = [r.hunt_id for r in results if r.status == ImportStatus.IMPORTED]
        if imported:
            self.hunts_imported.emit(imported)

    def confirm_duplicate(self, result: ImportResult) -> bool:
        box = QMessageBox(self._parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Hunt duplicada")
        box.setText(f"{result.message}\n\nDeseja importar novamente?")
        box.setInformativeText(f"Arquivo: {result.source_name}")
        cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        force = box.addButton("Importar mesmo assim", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is force

    def _report(self, results: Sequence[ImportResult], cancelled: bool = False) -> None:
        summary = summarize_results(results, cancelled)
        self.status_message.emit(summary)
        errors = [r for r in results if r.status == ImportStatus.ERROR]
        warnings = [r for r in results if r.status == ImportStatus.IMPORTED and r.warnings]
        duplicates = [r for r in results if r.status == ImportStatus.DUPLICATE]

        if len(results) == 1 and errors:
            error = errors[0]
            box = QMessageBox(QMessageBox.Icon.Warning, "Erro na importação", error.message,
                              QMessageBox.StandardButton.Ok, self._parent)
            box.setInformativeText(f"Arquivo: {error.source_name}")
            if error.detail:
                box.setDetailedText(error.detail)
            box.exec()
        elif len(results) > 1 and (errors or warnings or duplicates or cancelled):
            self.show_batch_report(summary, report_lines(results))

    def show_batch_report(self, summary: str, details: list[str]) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, "Resultado da importação", summary,
                          QMessageBox.StandardButton.Ok, self._parent)
        if details:
            box.setInformativeText("\n".join(details))
        box.exec()


def report_lines(results: Sequence[ImportResult]) -> list[str]:
    """Detalhes por arquivo (erros, avisos e duplicatas), limitados a poucas linhas."""
    lines = [f"• {r.source_name}: {r.message}" for r in results
             if r.status == ImportStatus.ERROR]
    lines += [f"• {r.source_name}: {w}" for r in results
              if r.status == ImportStatus.IMPORTED for w in r.warnings]
    lines += [f"• {r.source_name}: já importada (ignorada)" for r in results
              if r.status == ImportStatus.DUPLICATE]
    if len(lines) > MAX_REPORT_LINES:
        hidden = len(lines) - MAX_REPORT_LINES
        lines = lines[:MAX_REPORT_LINES] + [f"… e mais {hidden}."]
    return lines


def summarize_results(results: Sequence[ImportResult], cancelled: bool = False) -> str:
    imported = sum(r.status == ImportStatus.IMPORTED for r in results)
    duplicates = sum(r.status == ImportStatus.DUPLICATE for r in results)
    errors = sum(r.status == ImportStatus.ERROR for r in results)

    if len(results) == 1 and not cancelled:
        result = results[0]
        if result.status == ImportStatus.DUPLICATE:
            return f"Importação cancelada: {result.source_name} já estava importada."
        if result.saved_path is not None:
            return f"{result.message} JSON salvo em {result.saved_path}"
        return f"{result.message} ({result.source_name})"

    parts = [f"{imported} importada(s)"]
    if duplicates:
        parts.append(f"{duplicates} duplicada(s) ignorada(s)")
    if errors:
        parts.append(f"{errors} com erro")
    prefix = "Importação cancelada" if cancelled else "Importação concluída"
    return f"{prefix}: " + ", ".join(parts) + "."
