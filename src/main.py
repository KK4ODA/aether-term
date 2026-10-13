"""
main.py — Aether Term application entry point.

Aether Term (formerly VARA Term) — a PyQt6 desktop BBS terminal for
connecting to amateur radio BBS systems over VARA FM, VARA HF, the
open-source Aether HF modem, and AGWPE packet TNCs.
"""

import sys
import os
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logging():
    """Configure application logging with rotating file handler."""
    logs_dir = Path.home() / "Aether Term" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "aether-term.log"

    # Root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File handler (detailed)
    fh = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)-25s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(fh)

    # Console handler (info+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "[%(levelname)-7s] %(name)-20s  %(message)s"
    ))
    root.addHandler(ch)

    logging.getLogger("PyQt6").setLevel(logging.WARNING)

    return logging.getLogger("aetherterm")


def main():
    log = setup_logging()
    log.info("=" * 60)
    log.info("Aether Term starting")
    log.info("=" * 60)

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
    except ImportError:
        print("\n[ERROR] PyQt6 is not installed.")
        print("  Run:  python -m pip install PyQt6\n")
        sys.exit(1)

    try:
        from config import Config
        from passwords import PasswordStore
        from gui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("Aether Term")
        app.setApplicationDisplayName(
            "Aether Term — BBS Terminal Client for VARA and Aether HF")

        # Load configuration
        config = Config()

        from updater import Updater
        updater = Updater(config)

        # Load password store
        password_store = PasswordStore(config.app_data_dir)

        # Create and show main window
        window = MainWindow(config, password_store)
        window.show()

        # Check for a newer version in the background; if there is one the
        # user is asked (git clone: pull and restart; installed build:
        # download and run the new installer).  Help → Check for Updates
        # runs the same check by hand.
        window.set_updater(updater)
        if config.get("check_updates_on_startup", True):
            window.start_update_check()

        log.info("Aether Term GUI launched")
        sys.exit(app.exec())

    except Exception as e:
        log.exception(f"Fatal error: {e}")
        print(f"\n[FATAL] {e}")
        print(f"Check logs at: {Path.home() / 'Aether Term' / 'logs' / 'aether-term.log'}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
