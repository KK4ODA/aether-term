"""
gui/terminal_widget.py — Terminal display and command input for Aether Term.

A read-only monospaced text area for BBS output with color coding,
plus a single-line command input with history (up/down arrows).
"""

import logging
from typing import List

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLineEdit, QMenu
from PyQt6.QtGui import QFont, QFontDatabase, QTextCursor, QAction, QTextCharFormat
from PyQt6.QtCore import pyqtSignal, Qt

from gui.theme import QCOLORS, terminal_stylesheet, command_input_stylesheet

log = logging.getLogger(__name__)


def _get_monospace_font(preferred: str = "Consolas", size: int = 11) -> QFont:
    """Return a guaranteed monospace QFont.

    Tries the preferred font first, then falls through a list of
    well-known monospace fonts, and finally asks Qt for its default
    fixed-pitch font as a last resort.
    """
    candidates = [preferred, "Consolas", "Courier New",
                  "Lucida Console", "DejaVu Sans Mono",
                  "Liberation Mono", "Source Code Pro"]
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            font = QFont(name, size)
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setFixedPitch(True)
            return font
    # Last resort: ask Qt for the system fixed-pitch font
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(size)
    return font


class TerminalDisplay(QTextEdit):
    """Read-only scrollable terminal output with color support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        # NoWrap preserves ASCII art alignment — horizontal scroll if needed
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._auto_scroll = True

        # Guaranteed monospaced font
        self._mono_font = _get_monospace_font("Consolas", 11)
        self.setFont(self._mono_font)

        # CRITICAL: Set the document's default font — QTextCursor.insertText
        # uses the document font, not the widget font
        self.document().setDefaultFont(self._mono_font)

        # Set tab stop to 8 spaces (standard terminal)
        from PyQt6.QtGui import QFontMetricsF
        fm = QFontMetricsF(self._mono_font)
        self.setTabStopDistance(fm.horizontalAdvance(" ") * 8)

        log.info(f"Terminal font: {self._mono_font.family()}, "
                 f"fixedPitch={self._mono_font.fixedPitch()}, "
                 f"size={self._mono_font.pointSize()}pt")

        # Dark background — font-family MUST be set here to override
        # the global "Segoe UI" stylesheet on QWidget
        self.setStyleSheet(terminal_stylesheet(
            self._mono_font.family(), self._mono_font.pointSize()))

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _make_format(self, color: str) -> QTextCharFormat:
        """Create a QTextCharFormat with the correct monospace font and color."""
        fmt = QTextCharFormat()
        fmt.setFont(self._mono_font)
        fmt.setForeground(QCOLORS.get(color, QCOLORS["normal"]))
        return fmt

    def append_text(self, text: str, color: str = "normal"):
        """Append text with the specified color."""
        # Strip carriage returns — QTextEdit can mishandle them
        text = text.replace("\r", "")

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, self._make_format(color))

        if self._auto_scroll:
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

    def append_line(self, text: str, color: str = "normal"):
        """Append a line with newline."""
        self.append_text(text + "\n", color)

    def append_system(self, text: str):
        """Append a system message in cyan."""
        self.append_line(text, "cyan")

    def append_error(self, text: str):
        """Append an error message in red."""
        self.append_line(text, "red")

    def append_warning(self, text: str):
        """Append a warning in yellow."""
        self.append_line(text, "yellow")

    def append_success(self, text: str):
        """Append a success message in green."""
        self.append_line(text, "green")

    def clear_terminal(self):
        self.clear()

    def set_font_size(self, size: int):
        self._mono_font = _get_monospace_font(self._mono_font.family(), size)
        self._apply_font()

    def set_font_family(self, family: str):
        self._mono_font = _get_monospace_font(family, self._mono_font.pointSize())
        self._apply_font()

    def _apply_font(self):
        """Apply _mono_font to widget, document, stylesheet, and tab stops."""
        self.setFont(self._mono_font)
        self.document().setDefaultFont(self._mono_font)
        from PyQt6.QtGui import QFontMetricsF
        self.setTabStopDistance(
            QFontMetricsF(self._mono_font).horizontalAdvance(" ") * 8)
        # Update stylesheet font to override global Segoe UI
        self.setStyleSheet(terminal_stylesheet(
            self._mono_font.family(), self._mono_font.pointSize()))

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        select_all = QAction("Select All", self)
        select_all.triggered.connect(self.selectAll)
        menu.addAction(select_all)

        menu.addSeparator()

        clear_action = QAction("Clear Screen", self)
        clear_action.triggered.connect(self.clear_terminal)
        menu.addAction(clear_action)

        menu.exec(self.mapToGlobal(pos))


class CommandInput(QLineEdit):
    """Single-line command input with history (up/down arrows)."""

    command_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._history_pos = -1
        self._max_history = 100

        self.setPlaceholderText("Type command and press Enter...")
        mono = _get_monospace_font("Consolas", 11)
        self.setFont(mono)

        self.setStyleSheet(command_input_stylesheet(
            mono.family(), mono.pointSize()))

        self.returnPressed.connect(self._on_enter)

    def _on_enter(self):
        text = self.text().strip()
        if text:
            self._history.append(text)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._history_pos = -1
            self.command_entered.emit(text)
        self.clear()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._navigate_history(-1)
        elif key == Qt.Key.Key_Down:
            self._navigate_history(1)
        else:
            super().keyPressEvent(event)

    def _navigate_history(self, direction: int):
        if not self._history:
            return

        if self._history_pos == -1:
            if direction == -1:
                self._history_pos = len(self._history) - 1
            else:
                return
        else:
            self._history_pos += direction

        if self._history_pos < 0:
            self._history_pos = 0
        elif self._history_pos >= len(self._history):
            self._history_pos = -1
            self.clear()
            return

        self.setText(self._history[self._history_pos])


class TerminalWidget(QWidget):
    """Combined terminal display + command input."""

    command_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.display = TerminalDisplay()
        self.input = CommandInput()
        self.input.command_entered.connect(self.command_entered)

        layout.addWidget(self.display, stretch=1)
        layout.addWidget(self.input, stretch=0)

    def set_input_enabled(self, enabled: bool):
        self.input.setEnabled(enabled)
        if enabled:
            self.input.setFocus()

    def set_font_size(self, size: int):
        self.display.set_font_size(size)
        mono = _get_monospace_font(self.input.font().family(), size)
        self.input.setFont(mono)
        self.input.setStyleSheet(command_input_stylesheet(
            mono.family(), mono.pointSize()))
