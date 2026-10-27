"""
gui/kiss_settings.py — Settings for the KISS TNC mode.

How Aether Term reaches the TNC (a serial port, which is also how a
paired Bluetooth Classic radio appears; Bluetooth LE; or TCP), the TNC's
channel-access settings, and the AX.25 link settings.
"""

import threading

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QWidget,
)

from gui.theme import info_style
from tnc.transports import LINK_BLE, LINK_SERIAL, LINK_TCP, list_serial_ports

_LINKS = [
    ("Bluetooth or USB serial port (COM)", LINK_SERIAL),
    ("Bluetooth Low Energy (BLE)", LINK_BLE),
    ("TCP (Direwolf or a network TNC)", LINK_TCP),
]

HELP = (
    "<b>Using a radio's built-in TNC</b><ul>"
    "<li><b>Kenwood TH-D74 / TH-D75:</b> pair the radio in Windows Bluetooth "
    "settings (or plug in USB), then pick its COM port here: for Bluetooth, "
    "the one named <i>Standard Serial over Bluetooth link</i>. On the radio, "
    "switch the built-in TNC to <i>KISS</i> mode and choose its band and "
    "speed (1200 or 9600); the radio's manual shows how.</li>"
    "<li><b>Bluetooth LE radios and TNCs</b> (Mobilinkd TNC3/TNC4; VR-N76, "
    "VR-N7600, UV-Pro and similar): turn on the radio's KISS TNC, press "
    "<i>Scan</i> and pick the radio. <i>BLE support is new and not yet "
    "tested with these radios.</i></li>"
    "<li><b>Direwolf:</b> TCP, port 8001.</li></ul>"
    "Aether Term runs the AX.25 connection itself; the TNC only sends and "
    "receives packets.")


class KissSettingsGroup(QGroupBox):
    _ble_found = pyqtSignal(object, str)      # devices, error

    def __init__(self, config, parent=None):
        super().__init__("KISS TNC", parent)
        self.config = config
        form = QFormLayout(self)
        self.form = form

        info = QLabel(
            "A radio with a built-in KISS TNC (Kenwood TH-D74/D75, Bluetooth\n"
            "LE radios) or any KISS TNC, with no Soundmodem or other program.")
        info.setStyleSheet(info_style("0 0 6px 0"))
        form.addRow(info)

        self.link = QComboBox()
        for label, value in _LINKS:
            self.link.addItem(label, value)
        form.addRow("Connect via:", self.link)

        # Serial
        self.serial_port = QComboBox()
        self.serial_port.setEditable(True)
        self.serial_port.setToolTip(
            "The TNC's serial port. A paired Bluetooth Classic radio has one\n"
            "(\"Standard Serial over Bluetooth link\"); use the outgoing port.")
        self.serial_refresh = QPushButton("Refresh")
        self.serial_refresh.clicked.connect(self._fill_ports)
        row = QHBoxLayout()
        row.addWidget(self.serial_port, 1)
        row.addWidget(self.serial_refresh)
        self.serial_row = QWidget()
        self.serial_row.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addRow("Serial port:", self.serial_row)
        self.serial_baud = QComboBox()
        self.serial_baud.setEditable(True)
        self.serial_baud.addItems(["1200", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.serial_baud.setToolTip(
            "Speed of the serial link to the TNC (not the radio's packet\n"
            "speed). Bluetooth ports ignore it.")
        form.addRow("Baud rate:", self.serial_baud)

        # BLE
        self.ble_device = QComboBox()
        self.ble_device.setEditable(True)
        self.ble_device.setToolTip("The Bluetooth LE TNC: press Scan, or type its address.")
        self.ble_scan = QPushButton("Scan")
        self.ble_scan.clicked.connect(self._scan_ble)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.ble_device, 1)
        row.addWidget(self.ble_scan)
        self.ble_row = QWidget()
        self.ble_row.setLayout(row)
        form.addRow("BLE device:", self.ble_row)
        self.ble_status = QLabel("")
        self.ble_status.setStyleSheet(info_style("0"))
        self.ble_status.setWordWrap(True)
        form.addRow("", self.ble_status)
        self.ble_service = QLineEdit()
        self.ble_service.setPlaceholderText("standard KISS service (leave empty)")
        self.ble_service.setToolTip(
            "Only for a TNC that uses a different BLE service UUID.")
        form.addRow("BLE service:", self.ble_service)
        self._ble_found.connect(self._show_ble)

        # TCP
        self.tcp_host = QLineEdit()
        form.addRow("TCP host:", self.tcp_host)
        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.tcp_port.setToolTip("Direwolf's KISS port is 8001.")
        form.addRow("TCP port:", self.tcp_port)

        # TNC
        self.kiss_port = QSpinBox()
        self.kiss_port.setRange(0, 15)
        self.kiss_port.setToolTip("TNC port number; 0 on single-port TNCs and radios.")
        form.addRow("TNC port:", self.kiss_port)
        self.send_params = QCheckBox("Send TXDELAY, persistence and slot time to the TNC")
        self.send_params.setToolTip(
            "Set the TNC's channel access when the link opens.\n"
            "Turn off to keep what the radio is set to.")
        form.addRow(self.send_params)
        self.txdelay = QSpinBox()
        self.txdelay.setRange(0, 2550)
        self.txdelay.setSingleStep(10)
        self.txdelay.setSuffix(" ms")
        self.txdelay.setToolTip("Time between keying up and the first data.")
        form.addRow("TXDELAY:", self.txdelay)
        self.persistence = QSpinBox()
        self.persistence.setRange(0, 255)
        self.persistence.setToolTip("Chance (of 256) of sending in each free slot; 63 = 25%.")
        form.addRow("Persistence:", self.persistence)
        self.slottime = QSpinBox()
        self.slottime.setRange(0, 2550)
        self.slottime.setSingleStep(10)
        self.slottime.setSuffix(" ms")
        form.addRow("Slot time:", self.slottime)
        self.init = QLineEdit()
        self.init.setPlaceholderText(r"e.g. KISS ON\rRESTART (only for TNC2-style TNCs)")
        self.init.setToolTip(
            "Text commands sent when the link opens, before KISS, to put a\n"
            "TNC into KISS mode. Separate commands with \\r. Leave empty for\n"
            "radios: they are put into KISS mode from their own menu.")
        form.addRow("Init commands:", self.init)

        # AX.25
        self.paclen = QSpinBox()
        self.paclen.setRange(16, 256)
        self.paclen.setToolTip("Most bytes of text in one packet.")
        form.addRow("Packet length:", self.paclen)
        self.maxframe = QSpinBox()
        self.maxframe.setRange(1, 7)
        self.maxframe.setToolTip("Packets sent before waiting for an acknowledgement.")
        form.addRow("Window (MAXFRAME):", self.maxframe)
        self.frack = QSpinBox()
        self.frack.setRange(1, 30)
        self.frack.setSuffix(" s")
        self.frack.setToolTip(
            "Wait this long for an acknowledgement before asking again;\n"
            "longer through digipeaters (x 2 per digipeater + 1).")
        form.addRow("Retry time (FRACK):", self.frack)
        self.retries = QSpinBox()
        self.retries.setRange(1, 30)
        self.retries.setToolTip("Tries before a call or a link is given up.")
        form.addRow("Retries:", self.retries)

        help_label = QLabel(HELP)
        help_label.setWordWrap(True)
        help_label.setStyleSheet(info_style("0"))
        form.addRow(help_label)

        self.link.currentIndexChanged.connect(self._update_rows)
        self.send_params.toggled.connect(self._update_rows)

    # ── rows for the chosen link ───────────────────────────────────

    def _update_rows(self):
        link = self.link.currentData()
        for w, show in ((self.serial_row, link == LINK_SERIAL),
                        (self.serial_baud, link == LINK_SERIAL),
                        (self.ble_row, link == LINK_BLE),
                        (self.ble_status, link == LINK_BLE),
                        (self.ble_service, link == LINK_BLE),
                        (self.tcp_host, link == LINK_TCP),
                        (self.tcp_port, link == LINK_TCP)):
            self.form.setRowVisible(w, show)
        on = self.send_params.isChecked()
        for w in (self.txdelay, self.persistence, self.slottime):
            w.setEnabled(on)

    def _fill_ports(self):
        current = self.serial_port.currentText().strip()
        self.serial_port.clear()
        for dev, desc in list_serial_ports():
            self.serial_port.addItem(f"{dev} — {desc}" if desc != dev else dev, dev)
        if current:
            idx = self.serial_port.findData(current)
            if idx >= 0:
                self.serial_port.setCurrentIndex(idx)
            else:
                self.serial_port.setEditText(current)

    def _serial_value(self) -> str:
        data = self.serial_port.currentData()
        text = self.serial_port.currentText().strip()
        if data and self.serial_port.itemText(self.serial_port.currentIndex()) == text:
            return data
        return text.split(" — ")[0].strip()

    def _scan_ble(self):
        self.ble_scan.setEnabled(False)
        self.ble_status.setText("Scanning for Bluetooth LE devices...")

        def work():
            from tnc.ble import scan
            try:
                self._ble_found.emit(scan(), "")
            except Exception as e:                    # noqa: BLE001
                self._ble_found.emit([], str(e))
        threading.Thread(target=work, daemon=True, name="BLE-scan").start()

    def _show_ble(self, devices, error: str):
        self.ble_scan.setEnabled(True)
        if error:
            self.ble_status.setText(error)
            return
        current = self._ble_value()
        self.ble_device.clear()
        for address, name, kiss in devices:
            label = f"{name or '(no name)'} — {address}" + ("  [KISS TNC]" if kiss else "")
            self.ble_device.addItem(label, (address, name))
        n_kiss = sum(1 for d in devices if d[2])
        self.ble_status.setText(
            f"{len(devices)} device(s) found, {n_kiss} advertising a KISS TNC."
            if devices else "No Bluetooth LE devices found. Is the radio's KISS TNC on?")
        if current:
            self._select_ble(current, "")

    def _ble_value(self) -> str:
        data = self.ble_device.currentData()
        text = self.ble_device.currentText().strip()
        if data and self.ble_device.itemText(self.ble_device.currentIndex()) == text:
            return data[0]
        return text.split(" — ")[-1].split("  [")[0].strip()

    def _select_ble(self, address: str, name: str):
        for i in range(self.ble_device.count()):
            d = self.ble_device.itemData(i)
            if d and d[0] == address:
                self.ble_device.setCurrentIndex(i)
                return
        self.ble_device.addItem(f"{name} — {address}" if name else address, (address, name))
        self.ble_device.setCurrentIndex(self.ble_device.count() - 1)

    # ── load / save ────────────────────────────────────────────────

    def load_values(self):
        c = self.config
        idx = self.link.findData(c.get("kiss_link", LINK_SERIAL))
        self.link.setCurrentIndex(max(idx, 0))
        self._fill_ports()
        port = c.get("kiss_serial_port", "")
        if port:
            idx = self.serial_port.findData(port)
            if idx >= 0:
                self.serial_port.setCurrentIndex(idx)
            else:
                self.serial_port.setEditText(port)
        self.serial_baud.setCurrentText(str(c.get("kiss_serial_baud", 9600)))
        address = c.get("kiss_ble_address", "")
        if address:
            self._select_ble(address, c.get("kiss_ble_name", ""))
        self.ble_service.setText(c.get("kiss_ble_service", ""))
        self.tcp_host.setText(c.get("kiss_tcp_host", "127.0.0.1"))
        self.tcp_port.setValue(int(c.get("kiss_tcp_port", 8001)))
        self.kiss_port.setValue(int(c.get("kiss_port", 0)))
        self.send_params.setChecked(bool(c.get("kiss_send_params", True)))
        self.txdelay.setValue(int(c.get("kiss_txdelay", 300)))
        self.persistence.setValue(int(c.get("kiss_persistence", 63)))
        self.slottime.setValue(int(c.get("kiss_slottime", 100)))
        self.init.setText(c.get("kiss_init", ""))
        self.paclen.setValue(int(c.get("ax25_paclen", 128)))
        self.maxframe.setValue(int(c.get("ax25_maxframe", 4)))
        self.frack.setValue(int(c.get("ax25_frack", 7)))
        self.retries.setValue(int(c.get("ax25_retries", 10)))
        self._update_rows()

    def save_values(self):
        c = self.config
        c.set("kiss_link", self.link.currentData())
        c.set("kiss_serial_port", self._serial_value())
        try:
            c.set("kiss_serial_baud", int(self.serial_baud.currentText()))
        except ValueError:
            pass
        address = self._ble_value()
        c.set("kiss_ble_address", address)
        data = self.ble_device.currentData()
        c.set("kiss_ble_name", data[1] if data and data[0] == address else "")
        c.set("kiss_ble_service", self.ble_service.text().strip().lower())
        c.set("kiss_tcp_host", self.tcp_host.text().strip() or "127.0.0.1")
        c.set("kiss_tcp_port", self.tcp_port.value())
        c.set("kiss_port", self.kiss_port.value())
        c.set("kiss_send_params", self.send_params.isChecked())
        c.set("kiss_txdelay", self.txdelay.value())
        c.set("kiss_persistence", self.persistence.value())
        c.set("kiss_slottime", self.slottime.value())
        c.set("kiss_init", self.init.text().strip())
        c.set("ax25_paclen", self.paclen.value())
        c.set("ax25_maxframe", self.maxframe.value())
        c.set("ax25_frack", self.frack.value())
        c.set("ax25_retries", self.retries.value())
