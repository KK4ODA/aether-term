"""
gui/theme.py — Design system for Aether Term.

Single source of truth for colors, the global stylesheet, and
reusable style helpers.  Every hex color literal in the GUI codebase
should reference a constant from this module.
"""

from PyQt6.QtGui import QColor

# ── Color palette ──────────────────────────────────────────────────
# Derived from a Discord-inspired dark theme.  Names describe role,
# not hue, so the palette can be re-skinned in one place.

C = {
    # Backgrounds (darkest → lightest)
    "bg_deep":        "#1e1f22",   # main window, menubar, toolbar, terminal
    "bg_surface":     "#2b2d31",   # panels, dialog bodies, tab panes
    "bg_elevated":    "#383a40",   # inputs, buttons, spin boxes
    "bg_hover":       "#404249",   # button hover
    "bg_dropdown":    "#313338",   # combo dropdown button

    # Borders
    "border":         "#3b3d44",   # standard borders, separators, grid
    "border_light":   "#4e505a",   # input field borders, separator text

    # Accent
    "accent":         "#5865f2",   # focus rings, selected states, primary action
    "accent_press":   "#4752c4",   # button press

    # Text
    "text":           "#dbdee1",   # primary text
    "text_secondary": "#b5bac1",   # headers, group titles, status bar
    "text_dim":       "#80848e",   # hints, muted labels, disabled text

    # Semantic
    "success":        "#23a55a",   # connected, connect button
    "success_dark":   "#1a7f42",   # connect button hover
    "error":          "#f23f43",   # disconnected, disconnect button, errors
    "error_dark":     "#b72d30",   # disconnect button hover
    "warning":        "#f0b232",   # warnings
    "info":           "#00a8fc",   # system messages, mode selector
}


# ── QColor instances for terminal text ─────────────────────────────
# Pre-built QColor objects keyed by the same names used in
# TerminalDisplay.append_text(color=...).

QCOLORS = {
    "normal":  QColor(C["text"]),
    "green":   QColor(C["success"]),
    "yellow":  QColor(C["warning"]),
    "red":     QColor(C["error"]),
    "cyan":    QColor(C["info"]),
    "dim":     QColor(C["text_dim"]),
}


# ── State-color mapping ───────────────────────────────────────────
# connection.py uses string names ("red", "yellow", "green").
# This maps them to the actual hex values.

STATE_HEX = {
    "red":    C["error"],
    "yellow": C["warning"],
    "green":  C["success"],
}


# ── Arrow SVG icons ──────────────────────────────────────────────
# Generated from theme colors and written to temp files at import
# time.  Qt's stylesheet url() only accepts file paths — it does
# NOT support data: URIs.  Using a temp directory avoids depending
# on a fixed filesystem layout (works in frozen PyInstaller builds).

import os as _os
import tempfile as _tempfile
import atexit as _atexit

_ARROW_DOWN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
    f'<path d="M0 0 L5 6 L10 0 Z" fill="{C["text_secondary"]}"/>'
    '</svg>'
)

_ARROW_UP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
    f'<path d="M0 6 L5 0 L10 6 Z" fill="{C["text_secondary"]}"/>'
    '</svg>'
)

# Write to a temp directory that persists for the process lifetime.
_icon_dir = _tempfile.mkdtemp(prefix="aetherterm_icons_")


def _write_svg(name: str, content: str) -> str:
    """Write an SVG to _icon_dir and return its forward-slash path for Qt."""
    path = _os.path.join(_icon_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path.replace("\\", "/")  # Qt needs forward slashes


_ARROW_DOWN_PATH = _write_svg("arrow_down.svg", _ARROW_DOWN_SVG)
_ARROW_UP_PATH = _write_svg("arrow_up.svg", _ARROW_UP_SVG)


def _cleanup_icons():
    """Remove temp icon files on interpreter exit."""
    import shutil
    try:
        shutil.rmtree(_icon_dir, ignore_errors=True)
    except Exception:
        pass


_atexit.register(_cleanup_icons)


# ── Global stylesheet ─────────────────────────────────────────────

def build_stylesheet() -> str:
    """Return the complete application stylesheet.

    No longer requires an arrow_path argument — SVGs are embedded
    as data URIs.
    """
    return f"""
QMainWindow {{
    background-color: {C["bg_deep"]};
}}
QWidget {{
    background-color: {C["bg_surface"]};
    color: {C["text"]};
}}
QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox,
QRadioButton, QGroupBox, QSpinBox, QMenuBar, QMenu,
QStatusBar, QTabWidget, QTabBar, QFrame,
QListWidget, QTableWidget, QHeaderView, QDialogButtonBox {{
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 10pt;
}}

/* ── Menu bar ─────────────────────────────────────────── */
QMenuBar {{
    background-color: {C["bg_deep"]};
    color: {C["text"]};
    border-bottom: 1px solid {C["border"]};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background-color: {C["bg_elevated"]};
    border-radius: 3px;
}}
QMenu {{
    background-color: {C["bg_surface"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: {C["accent"]};
    color: white;
}}

/* ── Inputs ───────────────────────────────────────────── */
QLineEdit {{
    background-color: {C["bg_elevated"]};
    color: {C["text"]};
    border: 1px solid {C["border_light"]};
    border-radius: 4px;
    padding: 6px 10px;
}}
QLineEdit:focus {{
    border-color: {C["accent"]};
}}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {{
    background-color: {C["bg_elevated"]};
    color: {C["text"]};
    border: 1px solid {C["border_light"]};
    border-radius: 4px;
    padding: 6px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {C["bg_hover"]};
    border-color: {C["accent"]};
}}
QPushButton:pressed {{
    background-color: {C["accent_press"]};
}}
QPushButton:disabled {{
    background-color: {C["bg_surface"]};
    color: {C["text_dim"]};
    border-color: {C["border"]};
}}
QPushButton#connectBtn {{
    background-color: {C["success"]};
    color: white;
    font-weight: bold;
    border: none;
}}
QPushButton#connectBtn:hover {{
    background-color: {C["success_dark"]};
}}
QPushButton#connectBtn:disabled {{
    background-color: {C["bg_surface"]};
    color: {C["text_dim"]};
}}
QPushButton#disconnectBtn {{
    background-color: {C["error"]};
    color: white;
    font-weight: bold;
    border: none;
}}
QPushButton#disconnectBtn:hover {{
    background-color: {C["error_dark"]};
}}
QPushButton#disconnectBtn:disabled {{
    background-color: {C["bg_surface"]};
    color: {C["text_dim"]};
}}

/* ── Status bar ───────────────────────────────────────── */
QStatusBar {{
    background-color: {C["bg_deep"]};
    color: {C["text_secondary"]};
    border-top: 1px solid {C["border"]};
    font-size: 9pt;
}}

/* ── Mode combo (toolbar) ─────────────────────────────── */
QComboBox#modeCombo {{
    color: {C["info"]};
    font-weight: bold;
    padding: 2px 28px 2px 8px;
    min-width: 90px;
    background-color: {C["bg_deep"]};
    border: 1px solid {C["border"]};
}}
QComboBox#modeCombo:hover {{
    border-color: {C["info"]};
}}
QComboBox#modeCombo:disabled {{
    color: {C["border_light"]};
    border-color: {C["bg_surface"]};
}}

/* ── Status dot ───────────────────────────────────────── */
QLabel#statusDot {{
    font-size: 14pt;
    padding: 0 4px;
}}

/* ── Combo boxes ──────────────────────────────────────── */
QComboBox {{
    background-color: {C["bg_elevated"]};
    color: {C["text"]};
    border: 1px solid {C["border_light"]};
    border-radius: 4px;
    padding: 4px 28px 4px 8px;
    min-height: 20px;
}}
QComboBox:hover {{
    border-color: {C["accent"]};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border-left: 1px solid {C["border_light"]};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
    background-color: {C["bg_dropdown"]};
}}
QComboBox::down-arrow {{
    image: url("{_ARROW_DOWN_PATH}");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C["bg_surface"]};
    color: {C["text"]};
    border: 1px solid {C["border_light"]};
    selection-background-color: {C["accent"]};
    outline: none;
}}

/* ── Radio buttons ────────────────────────────────────── */
QRadioButton {{
    color: {C["text"]};
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 9px;
    border: 2px solid {C["border_light"]};
    background-color: {C["bg_elevated"]};
}}
QRadioButton::indicator:hover {{
    border-color: {C["accent"]};
}}
QRadioButton::indicator:checked {{
    border-color: {C["accent"]};
    background-color: {C["accent"]};
}}

/* ── Checkboxes ───────────────────────────────────────── */
QCheckBox {{
    color: {C["text"]};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 2px solid {C["border_light"]};
    background-color: {C["bg_elevated"]};
}}
QCheckBox::indicator:hover {{
    border-color: {C["accent"]};
}}
QCheckBox::indicator:checked {{
    border-color: {C["accent"]};
    background-color: {C["accent"]};
}}

/* ── Group boxes ──────────────────────────────────────── */
QGroupBox {{
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 14px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {C["text_secondary"]};
}}

/* ── Spin boxes ───────────────────────────────────────── */
QSpinBox {{
    background-color: {C["bg_elevated"]};
    color: {C["text"]};
    border: 1px solid {C["border_light"]};
    border-radius: 4px;
    padding: 4px 8px;
}}
QSpinBox:focus {{
    border-color: {C["accent"]};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {C["bg_dropdown"]};
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {C["accent"]};
}}
QSpinBox::up-arrow {{
    image: url("{_ARROW_UP_PATH}");
    width: 8px;
    height: 5px;
}}
QSpinBox::down-arrow {{
    image: url("{_ARROW_DOWN_PATH}");
    width: 8px;
    height: 5px;
}}

/* ── Tab widget ───────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {C["border"]};
    border-radius: 4px;
    background-color: {C["bg_surface"]};
}}
QTabBar::tab {{
    background-color: {C["bg_deep"]};
    color: {C["text_dim"]};
    padding: 8px 16px;
    border: 1px solid {C["border"]};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {C["bg_surface"]};
    color: {C["text"]};
    border-bottom: 2px solid {C["accent"]};
}}
QTabBar::tab:hover:!selected {{
    background-color: {C["bg_elevated"]};
    color: {C["text"]};
}}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {{
    background-color: {C["bg_surface"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    gridline-color: {C["border"]};
    selection-background-color: {C["accent"]};
    selection-color: white;
}}
QHeaderView::section {{
    background-color: {C["bg_deep"]};
    color: {C["text_secondary"]};
    border: 1px solid {C["border"]};
    padding: 4px 8px;
    font-weight: bold;
}}

/* ── List widgets ─────────────────────────────────────── */
QListWidget {{
    background-color: {C["bg_surface"]};
    color: {C["text"]};
    border: 1px solid {C["border"]};
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {C["accent"]};
    color: white;
}}
QListWidget::item:hover {{
    background-color: {C["bg_elevated"]};
}}

/* ── Scrollbars ───────────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {C["bg_surface"]};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {C["border_light"]};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {C["accent"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""


# ── Reusable style fragments ──────────────────────────────────────
# Used by widgets that need inline styles beyond the global sheet.

def terminal_stylesheet(font_family: str, font_size: int) -> str:
    """Stylesheet for the TerminalDisplay QTextEdit."""
    return f"""
        QTextEdit {{
            background-color: {C["bg_deep"]};
            color: {C["text"]};
            border: 1px solid {C["border"]};
            border-radius: 4px;
            padding: 6px;
            font-family: "{font_family}";
            font-size: {font_size}pt;
        }}
        QScrollBar:horizontal {{
            background-color: {C["bg_deep"]};
            height: 8px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {C["border_light"]};
            border-radius: 4px;
            min-width: 20px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {C["accent"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """


def command_input_stylesheet(font_family: str, font_size: int) -> str:
    """Stylesheet for the CommandInput QLineEdit."""
    return f"""
        QLineEdit {{
            background-color: {C["bg_elevated"]};
            color: {C["text"]};
            border: 1px solid {C["border_light"]};
            border-radius: 4px;
            padding: 8px 12px;
            font-family: "{font_family}";
            font-size: {font_size}pt;
        }}
        QLineEdit:focus {{
            border-color: {C["accent"]};
        }}
    """


def macro_btn_style() -> str:
    """Stylesheet for macro quick-send buttons."""
    return f"""
        QPushButton {{
            background-color: {C["bg_elevated"]};
            color: {C["text"]};
            border: 1px solid {C["border_light"]};
            padding: 5px 14px;
            font-size: 9pt;
            border-radius: 4px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {C["accent"]};
            color: white;
            border-color: {C["accent"]};
        }}
        QPushButton:pressed {{
            background-color: {C["accent_press"]};
        }}
    """


def macro_frame_style() -> str:
    """Stylesheet for the macro button bar frame."""
    return (f"QFrame {{ background-color: {C['bg_deep']}; "
            f"border-radius: 4px; padding: 2px; }}")


def macro_label_style() -> str:
    """Stylesheet for the 'Quick:' label in the macro bar."""
    return (f"color: {C['text_dim']}; font-size: 9pt; font-weight: bold; "
            f"background: transparent; border: none;")


def connect_profile_btn_style() -> str:
    """Stylesheet for the green 'Connect to This Profile' button."""
    return f"""
        QPushButton {{
            background-color: {C["success"]}; color: white;
            font-weight: bold; padding: 8px;
            border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {C["success_dark"]}; }}
    """


def hint_style() -> str:
    """Stylesheet for italic hint labels in settings dialogs."""
    return f"color: {C['text_dim']}; padding: 4px 0 8px 0; font-style: italic;"


def info_style(padding: str = "12px") -> str:
    """Stylesheet for informational (dim) labels."""
    return f"color: {C['text_dim']}; padding: {padding};"


def sn_graph_style() -> str:
    """Stylesheet for the S/N ratio graph widget."""
    return f"background-color: {C['bg_deep']}; border-radius: 4px;"


def settings_scroll_style() -> str:
    """Stylesheet for QScrollArea wrappers inside the settings dialog.

    Makes the scroll area transparent so group boxes render against
    the normal bg_surface, and ensures the scrollbar matches the theme.
    """
    return f"""
        QScrollArea {{
            background-color: transparent;
            border: none;
        }}
        QScrollArea > QWidget > QWidget {{
            background-color: {C["bg_surface"]};
        }}
    """


def connection_bar_style() -> str:
    """Stylesheet for the two-row connection bar that replaces QToolBar."""
    return f"""
        QFrame#connectionBar {{
            background-color: {C["bg_deep"]};
            border-bottom: 1px solid {C["border"]};
        }}
        QFrame#connectionBar QLabel {{
            background-color: transparent;
            color: {C["text"]};
            font-size: 10pt;
        }}
    """
