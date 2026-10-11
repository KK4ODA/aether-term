"""
gui/update_dialog.py — Dialog shown when a software update is available.

Git installs: shows the commit log and offers Update & Restart / Later.
Installed builds: shows the release notes and opens the release's download
page, since the new installer is what updates them.
"""

import logging
import threading
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QProgressBar,
)
from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices

from config import APP_VERSION
from gui.theme import C

log = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """Modal dialog presenting available updates and offering to apply them."""

    _apply_done = pyqtSignal(object)   # UpdateApplyResult

    def __init__(self, check_result, updater, restart_callback, parent=None):
        super().__init__(parent)
        self._result = check_result
        self._updater = updater
        self._restart = restart_callback
        self.setWindowTitle("Software Update")
        self.setMinimumWidth(520)
        self.setMinimumHeight(340)
        self._apply_done.connect(self._on_apply_done)
        self._build_ui()

    def _build_ui(self):
        if getattr(self._result, "mode", "git") == "release":
            self._build_release_ui()
            return
        layout = QVBoxLayout(self)

        from updater import get_git_hash
        git_hash = get_git_hash() or "?"

        layout.addWidget(QLabel(
            f"Current version:  v{APP_VERSION} ({git_hash})"
        ))
        layout.addWidget(QLabel(
            f"Latest available: {self._result.remote_hash}"
        ))

        layout.addSpacing(8)

        if self._result.commits:
            layout.addWidget(QLabel(
                f"<b>{len(self._result.commits)} new commit(s):</b>"
            ))
            log_view = QTextEdit()
            log_view.setReadOnly(True)
            lines = []
            for c in self._result.commits:
                lines.append(f"  {c.hash}  {c.subject}  ({c.author})")
            log_view.setPlainText("\n".join(lines))
            log_view.setMaximumHeight(180)
            layout.addWidget(log_view)

        layout.addSpacing(8)

        # Progress bar (hidden until update starts)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{C['warning']};")
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._later_btn = QPushButton("Later")
        self._later_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._later_btn)

        self._update_btn = QPushButton("Update && Restart")
        self._update_btn.setDefault(True)
        self._update_btn.setStyleSheet(
            f"background-color:{C['accent']}; color:white; padding:6px 18px;"
            f"border-radius:4px; font-weight:bold;"
        )
        self._update_btn.clicked.connect(self._on_update_clicked)
        btn_row.addWidget(self._update_btn)

        layout.addLayout(btn_row)

    def _build_release_ui(self):
        r = self._result
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Current version:  v{APP_VERSION}"))
        layout.addWidget(QLabel(f"Latest release:   <b>{r.release_name or r.release_tag}</b>"))
        layout.addSpacing(8)
        if r.release_notes:
            notes = QTextEdit()
            notes.setReadOnly(True)
            notes.setMarkdown(r.release_notes)
            notes.setMinimumHeight(180)
            layout.addWidget(notes)
        layout.addWidget(QLabel(
            "Download and run the new installer (or portable zip). "
            "Settings and saved passwords are kept."))
        self._status = QLabel("")
        layout.addWidget(self._status)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._later_btn = QPushButton("Later")
        self._later_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._later_btn)
        self._update_btn = QPushButton("Open Download Page")
        self._update_btn.setDefault(True)
        self._update_btn.setStyleSheet(
            f"background-color:{C['accent']}; color:white; padding:6px 18px;"
            f"border-radius:4px; font-weight:bold;"
        )
        self._update_btn.clicked.connect(self._open_release_page)
        btn_row.addWidget(self._update_btn)
        layout.addLayout(btn_row)

    def _open_release_page(self):
        QDesktopServices.openUrl(QUrl(self._result.release_url))
        self.accept()

    def _on_update_clicked(self):
        self._update_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Pulling latest changes ...")

        threading.Thread(
            target=self._do_apply,
            daemon=True,
            name="UpdateApply",
        ).start()

    def _do_apply(self):
        result = self._updater.apply_update()
        self._apply_done.emit(result)

    def _on_apply_done(self, result):
        self._progress.hide()
        if result.success:
            self._status.setText(
                f"Updated {result.old_hash} \u2192 {result.new_hash}.  "
                "Restarting ..."
            )
            self._status.setStyleSheet(f"color:{C['success']};")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, self._restart)
        else:
            self._status.setText(f"Update failed: {result.error}")
            self._status.setStyleSheet(f"color:{C['error']};")
            self._update_btn.setEnabled(True)
            self._later_btn.setEnabled(True)
