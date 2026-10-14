"""
gui/hamlib_settings.py — Hamlib CAT/PTT settings panel for the Aether Term settings dialog.

This module provides HamlibSettingsGroup (a QGroupBox) that can be dropped
into the existing Modem Configuration tab, plus a HamlibDownloadDialog for
the auto-update feature.

Integration:
    In settings_dialog.py _build_modem_tab(), add:
        from gui.hamlib_settings import HamlibSettingsGroup
        self.hamlib_group = HamlibSettingsGroup(self.config, parent=self)
        layout.addWidget(self.hamlib_group)

    In _load_values():
        self.hamlib_group.load_values()

    In _save_and_close():
        self.hamlib_group.save_values()
"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QVBoxLayout,
    QLineEdit, QSpinBox, QComboBox, QCheckBox, QPushButton,
    QLabel, QFileDialog, QDialog, QProgressBar, QTextEdit,
)

log = logging.getLogger(__name__)

# Import the rig model table from the hamlib module
try:
    from vara.hamlib import COMMON_RIG_MODELS
except ImportError:
    COMMON_RIG_MODELS = {1: "Hamlib Dummy (test)"}


class HamlibSettingsGroup(QGroupBox):
    """Hamlib CAT / PTT configuration panel.

    Drop this into the Modem Configuration tab of SettingsDialog.
    """

    def __init__(self, config, parent=None):
        super().__init__("Hamlib CAT Control", parent)
        self.config = config
        self._build_ui()

    def _build_ui(self):
        form = QFormLayout(self)

        # Info label
        info = QLabel(
            "Hamlib provides CAT (Computer Aided Transceiver) control\n"
            "and PTT via rigctld. Supports 300+ radio models."
        )
        info.setStyleSheet("color: #80848e; padding: 0 0 6px 0;")
        form.addRow(info)

        # Rig Model selector
        self.rig_model_combo = QComboBox()
        self.rig_model_combo.setEditable(True)
        self.rig_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.rig_model_combo.setToolTip("Select your radio model from the Hamlib database.\nType to search. Must match your actual radio.")
        self._populate_rig_models()
        form.addRow("Rig Model:", self.rig_model_combo)

        # Serial port / device
        self.device_input = QLineEdit()
        self.device_input.setPlaceholderText("e.g. COM3 or /dev/ttyUSB0")
        self.device_input.setToolTip("Serial port for CAT control.\nWindows: COM3, COM4, etc.\nLinux: /dev/ttyUSB0, etc.")
        form.addRow("Serial Port:", self.device_input)

        # Serial speed
        self.serial_speed = QComboBox()
        self.serial_speed.addItems([
            "Auto", "4800", "9600", "19200", "38400", "57600", "115200",
        ])
        self.serial_speed.setToolTip("Baud rate for CAT control serial port.\nAuto = let Hamlib detect. Check your radio manual.")
        form.addRow("Serial Speed:", self.serial_speed)

        # rigctld network settings
        self.rigctld_host = QLineEdit()
        self.rigctld_host.setPlaceholderText("127.0.0.1")
        self.rigctld_host.setToolTip("Network address of the Hamlib rigctld daemon.\nUsually 127.0.0.1 for local.")
        form.addRow("rigctld Host:", self.rigctld_host)

        self.rigctld_port = QSpinBox()
        self.rigctld_port.setRange(1, 65535)
        self.rigctld_port.setValue(4532)
        self.rigctld_port.setToolTip("TCP port for rigctld (default: 4532).")
        form.addRow("rigctld Port:", self.rigctld_port)

        # Auto-launch rigctld
        self.auto_launch_cb = QCheckBox(
            "Auto-launch rigctld with Aether Term")
        form.addRow(self.auto_launch_cb)

        # rigctld executable path
        self.rigctld_path = QLineEdit()
        self.rigctld_path.setPlaceholderText(
            r"%APPDATA%\Aether Term\hamlib\bin\rigctld.exe")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_rigctld)
        path_row = QHBoxLayout()
        path_row.addWidget(self.rigctld_path)
        path_row.addWidget(browse_btn)
        form.addRow("rigctld Path:", path_row)

        # Extra rigctld arguments
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("e.g. --set-conf=rts_state=ON")
        self.extra_args.setToolTip("Additional rigctld command-line arguments.\nAdvanced: only use if you know what you're doing.")
        form.addRow("Extra Args:", self.extra_args)

        # Download / Update button
        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("Download / Update Hamlib...")
        self.download_btn.clicked.connect(self._open_download_dialog)
        btn_row.addWidget(self.download_btn)

        self.version_label = QLabel("")
        btn_row.addWidget(self.version_label)
        btn_row.addStretch()
        form.addRow(btn_row)

    def _populate_rig_models(self):
        """Fill the rig model dropdown with common models."""
        self.rig_model_combo.clear()
        for model_id, name in sorted(
                COMMON_RIG_MODELS.items(), key=lambda x: x[1]):
            self.rig_model_combo.addItem(f"{name}  [{model_id}]", model_id)

    def _browse_rigctld(self):
        if os.name == "nt":
            filt = "Executables (*.exe);;All Files (*)"
        else:
            filt = "All Files (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Select rigctld Executable", "", filt)
        if path:
            self.rigctld_path.setText(path)

    def _open_download_dialog(self):
        dlg = HamlibDownloadDialog(self.config, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Update version label and rigctld path if auto-detected
            self._update_version_label()
            if dlg.installed_rigctld_path:
                self.rigctld_path.setText(dlg.installed_rigctld_path)

    def _update_version_label(self):
        try:
            from vara.hamlib_download import HamlibDownloader
            dl = HamlibDownloader()
            ver = dl.installed_version
            if ver:
                self.version_label.setText(f"Installed: v{ver}")
            else:
                self.version_label.setText("")
        except Exception:
            pass

    # ── Load / Save ───────────────────────────────────────────────

    def load_values(self):
        c = self.config

        # Rig model
        model_id = c.get("hamlib_rig_model", 1)
        for i in range(self.rig_model_combo.count()):
            if self.rig_model_combo.itemData(i) == model_id:
                self.rig_model_combo.setCurrentIndex(i)
                break

        self.device_input.setText(c.get("hamlib_device", ""))
        speed = str(c.get("hamlib_serial_speed", 0))
        idx = self.serial_speed.findText(speed)
        self.serial_speed.setCurrentIndex(idx if idx >= 0 else 0)

        self.rigctld_host.setText(c.get("hamlib_rigctld_host", "127.0.0.1"))
        self.rigctld_port.setValue(c.get("hamlib_rigctld_port", 4532))
        self.auto_launch_cb.setChecked(c.get("hamlib_auto_launch", True))
        self.rigctld_path.setText(c.get("hamlib_rigctld_path", ""))
        self.extra_args.setText(c.get("hamlib_extra_args", ""))

        self._update_version_label()

    def save_values(self):
        c = self.config
        # NOTE: hamlib_enabled is set by the parent dialog based on the
        # unified "HF Radio Control" dropdown, not by a checkbox here.

        model_id = self.rig_model_combo.currentData()
        if model_id is not None:
            c.set("hamlib_rig_model", model_id)
        else:
            # User may have typed a raw model number
            text = self.rig_model_combo.currentText()
            try:
                c.set("hamlib_rig_model", int(text))
            except ValueError:
                c.set("hamlib_rig_model", 1)

        c.set("hamlib_device", self.device_input.text().strip())
        speed_text = self.serial_speed.currentText()
        c.set("hamlib_serial_speed",
              0 if speed_text == "Auto" else int(speed_text))
        c.set("hamlib_rigctld_host", self.rigctld_host.text().strip()
              or "127.0.0.1")
        c.set("hamlib_rigctld_port", self.rigctld_port.value())
        c.set("hamlib_auto_launch", self.auto_launch_cb.isChecked())
        c.set("hamlib_rigctld_path", self.rigctld_path.text().strip())
        c.set("hamlib_extra_args", self.extra_args.text().strip())


# ╔════════════════════════════════════════════════════════════════╗
# ║  Download / Update Dialog                                      ║
# ╚════════════════════════════════════════════════════════════════╝

class _CheckWorker(QThread):
    """Background worker thread for checking Hamlib updates."""
    finished = pyqtSignal(dict)

    def run(self):
        try:
            from vara.hamlib_download import HamlibDownloader
            dl = HamlibDownloader()
            result = dl.check_update()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({"error": str(e)})


class _DownloadWorker(QThread):
    """Background worker thread for downloading Hamlib."""
    progress = pyqtSignal(int, int, str)  # bytes, total, message
    finished = pyqtSignal(dict)            # result dict

    def __init__(self, url: str = ""):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from vara.hamlib_download import HamlibDownloader
            dl = HamlibDownloader()
            result = dl.download_and_install(
                url=self.url,
                progress_callback=self._on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({"success": False, "error": str(e),
                                "version": ""})

    def _on_progress(self, downloaded: int, total: int, msg: str):
        self.progress.emit(downloaded, total, msg)


class HamlibDownloadDialog(QDialog):
    """Dialog for checking, downloading, and installing Hamlib."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.installed_rigctld_path = ""
        self.setWindowTitle("Hamlib Download / Update")
        self.setMinimumWidth(480)
        self._worker: Optional[_DownloadWorker] = None
        self._checker: Optional[_CheckWorker] = None
        self._download_url = ""
        self._build_ui()
        # Auto-check on open
        self._check_update()

    def closeEvent(self, event):
        """Ensure background workers are stopped before dialog closes."""
        for worker in (self._checker, self._worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Checking for latest Hamlib release...")
        layout.addWidget(self.status_label)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(150)
        layout.addWidget(self.info_text)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download && Install")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self.download_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

    def _check_update(self):
        """Check for updates using a QThread."""
        self._checker = _CheckWorker()
        self._checker.finished.connect(self._on_check_complete)
        self._checker.start()

    def _on_check_complete(self, info: dict):
        if info.get("error"):
            self.status_label.setText(f"Error: {info['error']}")
            self.info_text.setPlainText(
                "Could not check for updates. You can manually download "
                "Hamlib from:\nhttps://github.com/Hamlib/Hamlib/releases")
            # Even on error, allow manual download attempt
            self.download_btn.setEnabled(True)
            self.download_btn.setText("Retry Download")
            return

        current = info.get("current_version", "")
        latest = info.get("latest_version", "")
        has_update = info.get("update_available", False)

        if current:
            status = f"Installed: v{current}  |  Latest: v{latest}"
        else:
            status = f"Not installed  |  Latest: v{latest}"

        if has_update:
            status += "  — Update available!"
            self.download_btn.setEnabled(True)
        elif current:
            status += "  — Up to date"
        else:
            self.download_btn.setEnabled(True)

        self.status_label.setText(status)

        notes = info.get("release_notes", "")
        asset = info.get("asset_name", "")
        text = ""
        if asset:
            text += f"Asset: {asset}\n\n"
        if notes:
            text += f"Release notes:\n{notes}"
        self.info_text.setPlainText(text)

        self._download_url = info.get("download_url", "")

    def _start_download(self):
        url = self._download_url

        self.download_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_bar.setValue(0)

        self._worker = _DownloadWorker(url=url)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_download_finished)
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int, msg: str):
        if total > 0:
            pct = int(100 * downloaded / total)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(pct)
            self.progress_label.setText(
                f"{msg}  ({downloaded // 1024} / {total // 1024} KB)")
        else:
            self.progress_bar.setMaximum(0)  # indeterminate
            self.progress_label.setText(msg)

    def _on_download_finished(self, result: dict):
        self.progress_bar.setVisible(False)

        if result.get("success"):
            version = result.get("version", "")
            self.status_label.setText(
                f"Hamlib {version} installed successfully!")
            self.progress_label.setText("Installation complete.")

            # Update the rigctld path for the caller
            try:
                from vara.hamlib_download import HamlibDownloader
                dl = HamlibDownloader()
                self.installed_rigctld_path = dl.rigctld_path
            except Exception:
                pass

            self.download_btn.setText("Done")
            self.download_btn.setEnabled(False)
        else:
            error = result.get("error", "Unknown error")
            self.status_label.setText(f"Installation failed: {error}")
            self.progress_label.setText("")
            self.download_btn.setEnabled(True)
            self.download_btn.setText("Retry")
