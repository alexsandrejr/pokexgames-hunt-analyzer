"""Página de Configurações: aparência, banco de dados e backups."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import DEFAULT_DB_PATH, database_path_from_env
from app.services.backup_service import (
    BackupError,
    BackupInfo,
    BackupService,
    inspect_backup,
)
from app.services.hunt_service import HuntService
from app.services.settings_service import (
    MAX_BACKUPS_TO_KEEP,
    MIN_BACKUPS_TO_KEEP,
    THEMES,
    AppSettings,
    SettingsStore,
)
from app.ui.icons import icon
from app.ui.widgets.page import PAGE_MARGINS, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.constants import APP_VERSION
from app.utils.formatters import (
    NUMBER_FORMATS,
    format_datetime,
    format_number,
    set_number_format,
)

BACKUP_FILTER = "Banco SQLite (*.db);;Todos os arquivos (*)"


def format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    if size_bytes >= 1024 * 1024:
        return f"{format_number(size_bytes / (1024 * 1024), decimals=1)} MB"
    return f"{format_number(size_bytes / 1024, decimals=1)} KB"


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


BACKUP_COLUMNS: list[Column[BackupInfo]] = [
    Column("Data", lambda b: b.created_at, format_datetime),
    Column("Tipo", lambda b: b.kind_label),
    Column("Tamanho", lambda b: b.size_bytes, format_size, numeric=True),
    Column("Arquivo", lambda b: b.path.name),
]


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame(objectName="Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    layout.addWidget(QLabel(title, objectName="SectionTitle"))
    return card, layout


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(8)
    return form


def _button_row(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    for button in buttons:
        row.addWidget(button)
    row.addStretch(1)
    return row


class SettingsPage(QWidget):
    data_replaced = Signal()  # o banco foi restaurado a partir de um backup
    display_changed = Signal()  # formato de números alterado (atualizar telas)
    restart_requested = Signal()

    def __init__(self, hunts: HuntService, database_path: Path,
                 backups: BackupService | None = None, store: SettingsStore | None = None,
                 settings: AppSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hunts = hunts
        self._database_path = database_path
        self._backups = backups
        self._store = store
        self.settings = settings or AppSettings()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Configurações",
                                    "Aparência, banco de dados e backups"))
        layout.addWidget(self._build_restart_notice())
        layout.addWidget(self._build_appearance())
        layout.addWidget(self._build_database())
        layout.addWidget(self._build_backups())
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ------------------------------------------------------------ construção

    def _build_restart_notice(self) -> QFrame:
        self._restart_notice = QFrame(objectName="Card")
        row = QHBoxLayout(self._restart_notice)
        row.setContentsMargins(18, 12, 12, 12)
        self._restart_label = QLabel(objectName="MutedLabel")
        self._restart_label.setWordWrap(True)
        restart = QPushButton("Reiniciar agora")
        restart.setObjectName("PrimaryButton")
        restart.clicked.connect(self.restart_requested)
        row.addWidget(self._restart_label, 1)
        row.addWidget(restart)
        self._restart_notice.hide()
        return self._restart_notice

    def _build_appearance(self) -> QFrame:
        card, layout = _card("Aparência")
        self.theme_combo = QComboBox()
        for key, label in THEMES.items():
            self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.settings.theme))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        self.number_combo = QComboBox()
        for key, fmt in NUMBER_FORMATS.items():
            self.number_combo.addItem(f"{fmt.example}  ({key})", key)
        self.number_combo.setCurrentIndex(self.number_combo.findData(self.settings.number_format))
        self.number_combo.currentIndexChanged.connect(self._on_number_format_changed)

        for combo in (self.theme_combo, self.number_combo):
            combo.setMaximumWidth(320)
        form = _form()
        form.addRow("Tema", self.theme_combo)
        form.addRow("Formato de números", self.number_combo)
        layout.addLayout(form)
        hint = QLabel("O formato de números vale para as telas, os filtros e a exportação CSV. "
                      "A troca de tema é aplicada ao reiniciar.", objectName="CardHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    def _build_database(self) -> QFrame:
        card, layout = _card("Banco de dados")
        self._db_path_label = QLabel(str(self._database_path), objectName="FieldValue")
        self._db_path_label.setWordWrap(True)
        self._db_size_label = QLabel(objectName="FieldValue")
        self._db_count_label = QLabel(objectName="FieldValue")
        self._db_version_label = QLabel(objectName="FieldValue")
        form = _form()
        form.addRow("Arquivo", self._db_path_label)
        form.addRow("Tamanho", self._db_size_label)
        form.addRow("Hunts armazenadas", self._db_count_label)
        form.addRow("Versão do aplicativo", QLabel(APP_VERSION, objectName="FieldValue"))
        layout.addLayout(form)

        open_folder = QPushButton(icon("folder"), "  Abrir pasta")
        open_folder.clicked.connect(lambda: self._open_folder(self._database_path.parent))
        self.change_db_button = QPushButton("Usar outro banco…")
        self.change_db_button.clicked.connect(self._choose_database)
        self.default_db_button = QPushButton("Voltar ao banco padrão")
        self.default_db_button.clicked.connect(lambda: self.set_database_path(None))
        layout.addLayout(_button_row(open_folder, self.change_db_button, self.default_db_button))

        env = database_path_from_env()
        if env is not None:
            note = QLabel("O banco está definido pela variável de ambiente PXG_HUNTS_DB, que "
                          "tem prioridade sobre esta configuração.", objectName="CardHint")
            note.setWordWrap(True)
            layout.addWidget(note)
            self.change_db_button.setEnabled(False)
        self.default_db_button.setEnabled(env is None and self.settings.database_path is not None)
        return card

    def _build_backups(self) -> QFrame:
        card, layout = _card("Backup")
        self.auto_backup_check = QCheckBox("Fazer backup automático ao abrir o aplicativo "
                                           "(no máximo um por dia)")
        self.auto_backup_check.setChecked(self.settings.auto_backup)
        self.auto_backup_check.toggled.connect(self._on_backup_options_changed)
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(MIN_BACKUPS_TO_KEEP, MAX_BACKUPS_TO_KEEP)
        self.keep_spin.setValue(self.settings.backups_to_keep)
        self.keep_spin.setSuffix(" backups automáticos")
        self.keep_spin.valueChanged.connect(self._on_backup_options_changed)
        self.keep_spin.setMaximumWidth(320)
        form = _form()
        form.addRow(self.auto_backup_check)
        form.addRow("Manter os últimos", self.keep_spin)
        layout.addLayout(form)

        backup_now = QPushButton("Fazer backup agora")
        backup_now.setObjectName("PrimaryButton")
        backup_now.clicked.connect(self.backup_now)
        save_copy = QPushButton("Salvar cópia em…")
        save_copy.clicked.connect(self._save_copy)
        restore_file = QPushButton("Restaurar de arquivo…")
        restore_file.clicked.connect(self._restore_from_file)
        open_backups = QPushButton(icon("folder"), "  Abrir pasta de backups")
        open_backups.clicked.connect(self._open_backups_folder)
        layout.addLayout(_button_row(backup_now, save_copy, restore_file, open_backups))

        self.backups_table = RecordTable(BACKUP_COLUMNS)
        self.backups_table.set_sortable(False)
        self.backups_table.setFixedHeight(44 + 34 * 6)
        self.backups_table.doubleClicked.connect(lambda _index: self._restore_selected())
        self.backups_table.selectionModel().selectionChanged.connect(self._update_buttons)
        self.restore_selected_button = QPushButton("Restaurar selecionado")
        self.restore_selected_button.clicked.connect(self._restore_selected)
        self._backups_hint = QLabel(objectName="CardHint")
        self._backups_hint.setWordWrap(True)
        layout.addWidget(self.backups_table)
        layout.addLayout(_button_row(self.restore_selected_button))
        layout.addWidget(self._backups_hint)

        if self._backups is None:
            for widget in (self.auto_backup_check, self.keep_spin, backup_now, save_copy,
                           restore_file, open_backups, self.backups_table):
                widget.setEnabled(False)
        return card

    # ----------------------------------------------------------------- dados

    def refresh(self) -> None:
        self._db_size_label.setText(format_size(_file_size(self._database_path)))
        self._db_count_label.setText(format_number(self._hunts.count_hunts()))
        backups = self._backups.list_backups() if self._backups else []
        self.backups_table.set_records(backups)
        if self._backups is None:
            self._backups_hint.setText("Backups indisponíveis para bancos em memória.")
        else:
            self._backups_hint.setText(
                f"Pasta: {self._backups.backups_dir}. Antes de restaurar, o banco atual é "
                "sempre salvo como backup “Antes de restaurar”. Backups manuais nunca são "
                "apagados automaticamente.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.restore_selected_button.setEnabled(
            self._backups is not None and len(self.backups_table.selected_records()) == 1)

    def _save_settings(self, **changes) -> None:
        self.settings = replace(self.settings, **changes)
        if self._store is not None:
            self._store.save(self.settings)

    def _need_restart(self, message: str) -> None:
        self._restart_label.setText(message)
        self._restart_notice.show()

    # --------------------------------------------------------------- aparência

    def _on_theme_changed(self) -> None:
        self._save_settings(theme=self.theme_combo.currentData())
        self._need_restart("O novo tema será aplicado quando o aplicativo for reiniciado.")

    def _on_number_format_changed(self) -> None:
        key = self.number_combo.currentData()
        self._save_settings(number_format=key)
        set_number_format(key)
        self.display_changed.emit()
        self.refresh()

    # ---------------------------------------------------------------- banco

    def _choose_database(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Escolher ou criar um banco", str(self._database_path.parent), BACKUP_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.set_database_path(Path(path))

    def set_database_path(self, path: Path | None) -> None:
        """Grava o novo banco (``None`` = padrão); a troca vale ao reiniciar."""
        if path is not None and path.exists():
            try:
                inspect_backup(path)
            except BackupError as exc:
                QMessageBox.warning(self, "Banco inválido", str(exc))
                return
        is_default = path is None or path.resolve() == DEFAULT_DB_PATH.resolve()
        self._save_settings(database_path=None if is_default else str(path.resolve()))
        self.default_db_button.setEnabled(not is_default)
        target = DEFAULT_DB_PATH if is_default else path
        action = "aberto" if target.exists() else "criado"
        self._need_restart(f"O banco {target} será {action} quando o aplicativo for reiniciado.")

    # --------------------------------------------------------------- backups

    def _on_backup_options_changed(self) -> None:
        self._save_settings(auto_backup=self.auto_backup_check.isChecked(),
                            backups_to_keep=self.keep_spin.value())

    def backup_now(self) -> Path | None:
        return self._run_backup(None)

    def _save_copy(self) -> None:
        suggested = Path.home() / f"hunts_copia_{datetime.now():%Y-%m-%d}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Salvar cópia do banco", str(suggested),
                                              BACKUP_FILTER)
        if path:
            self._run_backup(Path(path))

    def _run_backup(self, destination: Path | None) -> Path | None:
        try:
            path = self._backups.create_backup(destination=destination)
        except BackupError as exc:
            QMessageBox.warning(self, "Falha no backup", str(exc))
            return None
        self._announce(f"Backup salvo em {path}")
        self.refresh()
        return path

    def _restore_selected(self) -> None:
        selected = self.backups_table.selected_records()
        if len(selected) == 1:
            self.restore_from(selected[0].path)

    def _restore_from_file(self) -> None:
        start = self._backups.backups_dir if self._backups.backups_dir.exists() else Path.home()
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", str(start),
                                              BACKUP_FILTER)
        if path:
            self.restore_from(Path(path))

    def restore_from(self, path: Path) -> Path | None:
        """Confirma e restaura; retorna o backup de segurança do banco anterior."""
        try:
            count = inspect_backup(path)
        except BackupError as exc:
            QMessageBox.warning(self, "Backup inválido", str(exc))
            return None
        if not self.confirm_restore(path, count):
            return None
        try:
            safety = self._backups.restore(path)
        except BackupError as exc:
            QMessageBox.critical(self, "Falha na restauração", str(exc))
            return None
        self.data_replaced.emit()
        self.refresh()
        self._announce(f"Backup restaurado ({format_number(count)} Hunts). O banco anterior "
                       f"foi salvo em {safety.name}.")
        return safety

    def confirm_restore(self, path: Path, hunt_count: int) -> bool:
        answer = QMessageBox.question(
            self, "Restaurar backup",
            f"Restaurar “{path.name}” ({format_number(hunt_count)} Hunts)?\n\n"
            f"O banco atual ({format_number(self._hunts.count_hunts())} Hunts) será "
            "substituído. Antes disso, uma cópia dele será salva na pasta de backups.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _open_backups_folder(self) -> None:
        self._backups.backups_dir.mkdir(parents=True, exist_ok=True)
        self._open_folder(self._backups.backups_dir)

    @staticmethod
    def _open_folder(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _announce(self, message: str) -> None:
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 10000)
