"""
gui/profile_dialog.py — Connection profile manager for Aether Term.
"""

import logging
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QSpinBox, QListWidget,
    QGroupBox, QMessageBox, QLabel,
)
from PyQt6.QtCore import pyqtSignal

from gui.theme import connect_profile_btn_style

log = logging.getLogger(__name__)


class ProfileDialog(QDialog):
    """Manage connection profiles for quick-connect."""

    profile_connect = pyqtSignal(dict)  # emitted when user clicks "Connect"

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Connection Profiles")
        self.setMinimumWidth(460)
        self.setMinimumHeight(380)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        # Left: profile list
        left = QVBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_selection)
        left.addWidget(QLabel("Saved Profiles:"))
        left.addWidget(self.profile_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_profile)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_profile)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.remove_btn)
        left.addLayout(btn_row)
        layout.addLayout(left)

        # Right: profile details + connect button
        right = QVBoxLayout()
        form_group = QGroupBox("Profile Details")
        form = QFormLayout(form_group)

        self.name_input = QLineEdit()
        form.addRow("Profile Name:", self.name_input)

        self.my_call_input = QLineEdit()
        self.my_call_input.setPlaceholderText("(use global setting)")
        self.my_call_input.setToolTip(
            "Operator callsign for this profile.\n"
            "Leave blank to use the global callsign from Settings."
        )
        form.addRow("My Callsign:", self.my_call_input)

        self.my_ssid_spin = QSpinBox()
        self.my_ssid_spin.setRange(0, 15)
        self.my_ssid_spin.setToolTip("SSID (0-15) for this operator.")
        form.addRow("My SSID:", self.my_ssid_spin)

        self.tactical_input = QLineEdit()
        self.tactical_input.setPlaceholderText("(optional, e.g. BRECKEN)")
        self.tactical_input.setToolTip(
            "Tactical address to activate on the BBS after connecting.\n"
            "Must match a tactical address configured on the BBS.\n"
            "WL will poll Winlink for this address; S will send from it.\n"
            "Leave blank to skip."
        )
        form.addRow("Tactical Address:", self.tactical_input)

        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("e.g. KK4ODA-5")
        form.addRow("Target Callsign:", self.target_input)
        self.mode_combo = QComboBox()
        for label, value in (("VARA FM", "VARA FM"), ("VARA HF", "VARA HF"),
                             ("Aether HF", "Aether HF"),
                             ("Soundmodem (AGWPE)", "AGWPE"),
                             ("KISS TNC", "KISS TNC")):
            self.mode_combo.addItem(label, value)
        form.addRow("Mode:", self.mode_combo)
        self.fm_bw_combo = QComboBox()
        self.fm_bw_combo.addItems(["WIDE", "NARROW"])
        self.fm_bw_combo.setToolTip("VARA FM bandwidth shown in the status bar.\nWIDE (default) or NARROW; set the real one in VARA FM.")
        form.addRow("FM Bandwidth:", self.fm_bw_combo)
        self.bw_combo = QComboBox()
        self.bw_combo.addItems(["500", "2300", "2750"])
        self.bw_combo.setToolTip(
            "HF bandwidth for this profile.\n"
            "VARA HF: 500/2300/2750 Hz.\n"
            "Aether HF: 500 or 2300 Hz (2750 runs as 2300).")
        form.addRow("HF Bandwidth:", self.bw_combo)
        self.via1_input = QLineEdit()
        self.via1_input.setPlaceholderText("Digipeater 1 (optional)")
        self.via1_input.setToolTip("First digipeater callsign (VARA FM, Soundmodem and KISS TNC).")
        form.addRow("Via 1:", self.via1_input)
        self.via2_input = QLineEdit()
        self.via2_input.setPlaceholderText("Digipeater 2 (optional)")
        self.via2_input.setToolTip("Second digipeater callsign (VARA FM, Soundmodem and KISS TNC).")
        form.addRow("Via 2:", self.via2_input)

        right.addWidget(form_group)

        save_btn = QPushButton("Save Changes")
        save_btn.clicked.connect(self._save_current)
        right.addWidget(save_btn)

        connect_btn = QPushButton("Connect to This Profile")
        connect_btn.setStyleSheet(connect_profile_btn_style())
        connect_btn.clicked.connect(self._connect)
        right.addWidget(connect_btn)

        right.addStretch()
        layout.addLayout(right)

    def _refresh_list(self):
        self.profile_list.clear()
        for p in self.config.get_profiles():
            self.profile_list.addItem(p.get("name", "Untitled"))

    def _on_selection(self, row: int):
        profiles = self.config.get_profiles()
        if 0 <= row < len(profiles):
            p = profiles[row]
            self.name_input.setText(p.get("name", ""))
            self.my_call_input.setText(p.get("my_callsign", ""))
            self.my_ssid_spin.setValue(p.get("my_ssid", 0))
            self.tactical_input.setText(p.get("tactical_callsign", ""))
            self.target_input.setText(p.get("target_callsign", ""))
            idx = self.mode_combo.findData(p.get("mode", "VARA FM"))
            self.mode_combo.setCurrentIndex(max(idx, 0))
            self.fm_bw_combo.setCurrentText(p.get("fm_bandwidth", "WIDE"))
            self.bw_combo.setCurrentText(str(p.get("bandwidth", 500)))
            self.via1_input.setText(p.get("via1", ""))
            self.via2_input.setText(p.get("via2", ""))

    def _add_profile(self):
        profile = {
            "name": "New Profile",
            "my_callsign": "",
            "my_ssid": 0,
            "tactical_callsign": "",
            "target_callsign": "",
            "mode": "VARA FM",
            "fm_bandwidth": "WIDE",
            "bandwidth": 500,
            "via1": "",
            "via2": "",
        }
        self.config.add_profile(profile)
        self.config.save()
        self._refresh_list()
        self.profile_list.setCurrentRow(self.profile_list.count() - 1)

    def _remove_profile(self):
        row = self.profile_list.currentRow()
        if row >= 0:
            self.config.remove_profile(row)
            self.config.save()
            self._refresh_list()

    def _save_current(self):
        row = self.profile_list.currentRow()
        profiles = self.config.get_profiles()
        if 0 <= row < len(profiles):
            profiles[row] = self._current_profile_data()
            self.config.set("profiles", profiles)
            self.config.save()
            self._refresh_list()
            self.profile_list.setCurrentRow(row)

    def _connect(self):
        data = self._current_profile_data()
        if not data.get("target_callsign"):
            QMessageBox.warning(self, "Error", "Target callsign is required")
            return
        self.profile_connect.emit(data)
        self.accept()

    def _current_profile_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_input.text().strip(),
            "my_callsign": self.my_call_input.text().upper().strip(),
            "my_ssid": self.my_ssid_spin.value(),
            "tactical_callsign": self.tactical_input.text().upper().strip(),
            "target_callsign": self.target_input.text().upper().strip(),
            "mode": self.mode_combo.currentData(),
            "fm_bandwidth": self.fm_bw_combo.currentText(),
            "bandwidth": int(self.bw_combo.currentText()),
            "via1": self.via1_input.text().upper().strip(),
            "via2": self.via2_input.text().upper().strip(),
        }
