"""Temas da aplicação (paleta Qt + folha de estilos QSS).

``COLORS`` é o dicionário do tema ativo. Ele é preenchido por ``use_palette``
antes de a janela ser criada, e os widgets o leem ao se desenhar; trocar de
tema exige reiniciar o aplicativo.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from app.config import ICONS_DIR

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#14171c",
        "sidebar": "#181b21",
        "surface": "#1a1e25",
        "surface_alt": "#232831",
        "surface_hover": "#2b313b",
        "border": "#303640",
        "text": "#e8eaef",
        "muted": "#9aa3b2",
        "icon": "#aeb6c4",
        "accent": "#5b8cff",
        "accent_hover": "#739dff",
        # Botão principal mais escuro que o destaque: o texto branco precisa de contraste.
        "primary": "#3b6fe0",
        "primary_hover": "#4a7bea",
        "accent_soft": "rgba(91, 140, 255, 0.16)",
        "selection": "rgba(91, 140, 255, 0.28)",
        "positive": "#3ecf8e",
        "negative": "#f06a6a",
        "warning": "#f5b841",
        "chevron": "chevron-down.svg",
        "chevron_up": "chevron-up.svg",
        # Gráficos: série validada (guia de dataviz) contra a superfície escura.
        "chart_series": "#3987e5",
        "chart_series_hover": "#6aa6ee",
        "chart_grid": "#262a33",
        "chart_baseline": "#3a3f4b",
        "chart_reference": "#6b7280",
    },
    "light": {
        "bg": "#f6f7f9",
        "sidebar": "#ffffff",
        "surface": "#ffffff",
        "surface_alt": "#f1f3f6",
        "surface_hover": "#e9ecf1",
        "border": "#e1e4ea",
        "text": "#15192a",
        "muted": "#5a6272",
        "icon": "#4b5263",
        "accent": "#2a6fd6",
        "accent_hover": "#1f5fbf",
        "primary": "#2a6fd6",
        "primary_hover": "#1f5fbf",
        "accent_soft": "rgba(42, 111, 214, 0.12)",
        "selection": "rgba(42, 111, 214, 0.18)",
        "positive": "#0f7a3a",
        "negative": "#c62828",
        "warning": "#a15c00",
        "chevron": "chevron-down-strong.svg",
        "chevron_up": "chevron-up-strong.svg",
        # Série validada contra a superfície clara (#ffffff).
        "chart_series": "#2a78d6",
        "chart_series_hover": "#1c5cab",
        "chart_grid": "#eceef1",
        "chart_baseline": "#c9cdd4",
        "chart_reference": "#9ca3af",
    },
}
DEFAULT_THEME = "dark"

# Cores clássicas dos tipos de pokémon: as mesmas nos dois temas, para serem reconhecidas.
ELEMENT_COLORS: dict[str, str] = {
    "Normal": "#a8a77a", "Fire": "#ee8130", "Water": "#6390f0", "Grass": "#7ac74c",
    "Electric": "#f7d02c", "Ice": "#96d9d6", "Fighting": "#c22e28", "Poison": "#a33ea1",
    "Ground": "#e2bf65", "Flying": "#a98ff3", "Psychic": "#f95587", "Bug": "#a6b91a",
    "Rock": "#b6a136", "Ghost": "#735797", "Dragon": "#6f35fc", "Dark": "#705746",
    "Steel": "#b7b7ce", "Fairy": "#d685ad",
}

# Tema ativo (mutável, para que ``from app.ui.theme import COLORS`` veja a troca).
COLORS: dict[str, str] = dict(PALETTES[DEFAULT_THEME])
_active_theme = DEFAULT_THEME


def use_palette(name: str) -> str:
    """Ativa um tema (nomes desconhecidos → escuro). Chamar antes de criar a janela."""
    global _active_theme
    _active_theme = name if name in PALETTES else DEFAULT_THEME
    COLORS.clear()
    COLORS.update(PALETTES[_active_theme])
    return _active_theme


def active_theme() -> str:
    return _active_theme

MONOSPACE_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New"]


def _stylesheet(c: dict[str, str]) -> str:
    icons = ICONS_DIR.as_posix()  # setas e marca de seleção desenhadas por imagem
    return f"""
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget {{ color: {c['text']}; }}
    QToolTip {{
        background: {c['surface_alt']}; color: {c['text']};
        border: 1px solid {c['border']}; padding: 6px; border-radius: 6px;
    }}

    /* Sidebar */
    #Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
    #SidebarTitle {{ font-size: 12pt; font-weight: 600; }}
    #SidebarSubtitle {{ color: {c['muted']}; font-size: 9pt; }}
    QPushButton#NavButton {{
        background: transparent; border: none; border-radius: 8px;
        color: {c['muted']}; padding: 9px 12px; text-align: left; font-size: 10pt;
    }}
    QPushButton#NavButton:hover {{ background: {c['surface_alt']}; color: {c['text']}; }}
    QPushButton#NavButton:focus {{ background: {c['surface_alt']}; color: {c['text']}; }}
    QPushButton#NavButton:checked {{
        background: {c['accent_soft']}; color: {c['accent']}; font-weight: 600;
    }}
    QPushButton#SidebarFooter {{
        background: transparent; border: none; color: {c['muted']};
        font-size: 9pt; padding: 4px 12px; text-align: left;
    }}
    QPushButton#SidebarFooter:hover {{ color: {c['text']}; }}

    /* Sub-navegação das seções (Sessões e Análise) */
    #SectionBar {{ background: transparent; }}
    QPushButton#SectionPill {{
        background: transparent; border: 1px solid transparent; border-radius: 14px;
        color: {c['muted']}; padding: 5px 14px;
    }}
    QPushButton#SectionPill:hover {{ background: {c['surface_hover']}; color: {c['text']}; }}
    QPushButton#SectionPill:focus {{ border-color: {c['accent']}; }}
    /* Sem negrito ao marcar: o botão não recalcula a largura e cortaria o texto. */
    QPushButton#SectionPill:checked {{ background: {c['accent_soft']}; color: {c['accent']}; }}

    /* Páginas */
    #PageTitle {{ font-size: 16pt; font-weight: 600; }}
    #PageSubtitle {{ color: {c['muted']}; }}
    #SectionTitle {{ font-size: 11pt; font-weight: 600; }}
    #MutedLabel {{ color: {c['muted']}; }}
    #EmptyTitle {{ font-size: 13pt; font-weight: 600; }}
    #SelectionLabel {{ color: {c['accent']}; font-weight: 600; }}

    /* Cards */
    #Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    #CardTitle {{ color: {c['muted']}; font-size: 9pt; }}
    #CardValue {{ font-size: 18pt; font-weight: 600; }}
    #CardValueCompact {{ font-size: 12pt; font-weight: 600; }}
    #CardHint {{ color: {c['muted']}; font-size: 9pt; }}
    #FieldLabel {{ color: {c['muted']}; }}
    #FieldValue {{ font-weight: 600; }}

    /* Botões */
    QPushButton {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 7px;
        padding: 7px 14px; color: {c['text']};
    }}
    QPushButton:focus {{ border-color: {c['accent']}; }}
    QPushButton::menu-indicator {{
        image: url({icons}/{c['chevron']}); width: 10px; height: 10px;
        subcontrol-position: center right; subcontrol-origin: padding; right: 8px;
    }}
    QPushButton#PrimaryButton::menu-indicator {{ image: url({icons}/chevron-down-white.svg); }}
    QPushButton:hover {{ background: {c['surface_hover']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['surface']}; }}
    QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border']}; background: {c['surface']}; }}
    QPushButton#PrimaryButton {{ background: {c['primary']}; border: 1px solid {c['primary']}; color: #ffffff; font-weight: 600; }}
    QPushButton#PrimaryButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#PrimaryButton:disabled {{
        background: {c['surface_alt']}; border-color: {c['border']}; color: {c['muted']};
    }}
    QPushButton#DangerButton:hover {{ border-color: {c['negative']}; color: {c['negative']}; }}

    /* Entradas */
    QLineEdit, QComboBox {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 7px;
        padding: 6px 10px; selection-background-color: {c['accent']};
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 24px; border: none; background: transparent;
    }}
    QComboBox::down-arrow {{ image: url({icons}/{c['chevron']}); width: 10px; height: 10px; }}

    QDateEdit {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
        padding: 6px 8px;
    }}
    QDateEdit:focus {{ border-color: {c['accent']}; }}
    QDateEdit::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 22px; border: none; background: transparent;
    }}
    QDateEdit::down-arrow {{ image: url({icons}/{c['chevron']}); width: 10px; height: 10px; }}
    QDateEdit:disabled, QComboBox:disabled, QLineEdit:disabled {{ color: {c['muted']}; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']}; border: 1px solid {c['border']};
        selection-background-color: {c['accent_soft']}; selection-color: {c['text']};
        outline: 0;
    }}
    QSpinBox {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
        padding: 5px 26px 5px 8px;
    }}
    QSpinBox:focus {{ border-color: {c['accent']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border; width: 22px; border: none; background: transparent;
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c['surface_hover']}; }}
    QSpinBox::up-arrow {{ image: url({icons}/{c['chevron_up']}); width: 10px; height: 10px; }}
    QSpinBox::down-arrow {{ image: url({icons}/{c['chevron']}); width: 10px; height: 10px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {c['muted']}; background: {c['surface']};
    }}
    QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
    QCheckBox::indicator:checked {{
        background: {c['accent']}; border-color: {c['accent']}; image: url({icons}/check.svg);
    }}
    QProgressBar {{
        background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 6px;
        text-align: center; height: 14px;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QLineEdit[invalid="true"] {{ border-color: {c['negative']}; }}
    #ErrorLabel {{ color: {c['negative']}; }}
    #WarningLabel {{ color: {c['warning']}; }}
    QPlainTextEdit#DpsNote {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px;
    }}

    /* Listas (página DPS) */
    QListWidget {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px;
        outline: 0; padding: 4px;
    }}
    QListWidget::item {{ padding: 6px; border-radius: 6px; }}
    QListWidget#DpsRanking::item {{ padding: 0px; }}
    QListWidget::item:hover {{ background: {c['surface_alt']}; }}
    QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
    QListWidget::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {c['muted']}; background: {c['surface']};
    }}
    QListWidget::indicator:checked {{
        background: {c['accent']}; border-color: {c['accent']}; image: url({icons}/check.svg);
    }}
    QProgressBar#RankingBar {{
        background: {c['surface_hover']}; border: none; border-radius: 4px;
        min-height: 8px; max-height: 8px;
    }}
    QProgressBar#RankingBar::chunk {{ background: {c['chart_series']}; border-radius: 4px; }}

    /* Painel de filtros */
    #FilterPanel {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QToolButton#FilterToggle {{
        background: transparent; border: none; font-weight: 600; padding: 4px 2px;
    }}
    QToolButton#FilterChevron {{ background: transparent; border: none; padding: 4px; }}
    QToolButton#FilterChevron:hover {{ background: {c['surface_alt']}; border-radius: 6px; }}
    #FilterBadge {{
        background: {c['accent_soft']}; color: {c['text']}; border-radius: 9px;
        padding: 1px 7px; font-size: 8.5pt; font-weight: 600;
    }}
    QPushButton#GhostButton {{ background: transparent; border: none; color: {c['muted']}; padding: 4px 8px; }}
    QPushButton#GhostButton:hover {{ color: {c['text']}; background: {c['surface_alt']}; }}

    /* Gráficos */
    #ChartTitle {{ font-weight: 600; }}

    /* Tabelas */
    QTableView {{
        background: {c['surface']}; alternate-background-color: {c['surface']};
        border: 1px solid {c['border']}; border-radius: 10px; gridline-color: transparent;
        selection-background-color: {c['selection']}; selection-color: {c['text']};
        outline: 0;
    }}
    QTableView::item {{ padding: 4px 8px; border: none; border-bottom: 1px solid {c['surface_alt']}; }}
    QHeaderView {{ background: transparent; }}
    /* Mesmo recuo das células (8px + 3px da margem de texto), para alinhar os números. */
    QHeaderView::section {{
        background: {c['surface']}; color: {c['muted']}; font-weight: 600;
        padding: 8px 11px; border: none; border-bottom: 1px solid {c['border']};
    }}
    QHeaderView::down-arrow {{ image: url({icons}/{c['chevron']}); width: 9px; height: 9px; }}
    QHeaderView::up-arrow {{ image: url({icons}/{c['chevron_up']}); width: 9px; height: 9px; }}
    QTableCornerButton::section {{ background: {c['surface']}; border: none; }}

    /* Abas */
    QTabWidget::pane {{
        border: 1px solid {c['border']}; border-radius: 10px; background: {c['surface']}; top: -1px;
    }}
    /* Abas de categoria (Bosses): sem moldura, as abas internas já têm a sua. */
    QTabWidget#CategoryTabs::pane {{ border: none; background: transparent; top: 0px; }}
    QTabBar::tab {{
        background: transparent; color: {c['muted']}; padding: 8px 16px; margin-right: 2px;
        border: none; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}

    QPlainTextEdit {{
        background: {c['surface']}; border: none; border-radius: 10px;
        selection-background-color: {c['selection']};
    }}

    /* Scroll */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {c['border']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
    QScrollBar::handle:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* Menus e status */
    QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['accent_soft']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
    QStatusBar {{ background: {c['sidebar']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
    """


def _palette(c: dict[str, str]) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["bg"],
        QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.Base: c["surface"],
        QPalette.ColorRole.AlternateBase: c["surface_alt"],
        QPalette.ColorRole.Text: c["text"],
        QPalette.ColorRole.Button: c["surface_alt"],
        QPalette.ColorRole.ButtonText: c["text"],
        QPalette.ColorRole.ToolTipBase: c["surface_alt"],
        QPalette.ColorRole.ToolTipText: c["text"],
        QPalette.ColorRole.PlaceholderText: c["muted"],
        QPalette.ColorRole.Highlight: c["accent"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: c["accent"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    return palette


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_palette(COLORS))
    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(_stylesheet(COLORS))


def monospace_font(point_size: int = 10) -> QFont:
    font = QFont()
    font.setFamilies(MONOSPACE_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(point_size)
    return font
