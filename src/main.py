"""
main.py — Aether Term application entry point.

Aether Term (formerly VARA Term) — a PyQt6 desktop BBS terminal for
connecting to amateur radio BBS systems over VARA FM, VARA HF, the
open-source Aether HF modem, and AGWPE packet TNCs.
"""

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOG_FILE = Path.home() / "Aether Term" / "logs" / "aether-term.log"


def setup_logging():
    """Configure application logging with rotating file handler."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_FILE

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

    # Console handler (info+) — a windowed build has no console
    if sys.stdout is not None:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            "[%(levelname)-7s] %(name)-20s  %(message)s"
        ))
        root.addHandler(ch)

    logging.getLogger("PyQt6").setLevel(logging.WARNING)

    return logging.getLogger("aetherterm")


def install_error_handler(log):
    """Log unexpected errors and show them, instead of exiting.

    With Python's default excepthook, PyQt6 aborts the whole program when
    an exception escapes a Qt slot — the window just vanishes.  This hook
    writes the traceback to the log and shows a dialog; the app carries on.
    Errors in background threads are logged too.
    """
    import threading
    log_file = LOG_FILE
    showing = []

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unexpected error", exc_info=(exc_type, exc, tb))
        if showing:                      # one dialog at a time
            return
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return
            showing.append(True)
            QMessageBox.critical(
                None, "Aether Term — unexpected error",
                f"{exc_type.__name__}: {exc}\n\n"
                f"The details were written to the log:\n{log_file}\n\n"
                "Aether Term keeps running; restart it if something "
                "does not work as it should.")
        except Exception:
            pass
        finally:
            showing.clear()

    def thread_hook(args):
        log.critical(f"Unexpected error in thread {args.thread.name if args.thread else '?'}",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def main():
    log = setup_logging()
    install_error_handler(log)
    log.info("=" * 60)
    log.info("Aether Term starting")
    log.info("=" * 60)

    try:
        from PyQt6.QtWidgets import QApplication
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
        message = f"Aether Term could not start:\n{e}\n\nDetails are in the log:\n{LOG_FILE}"
        # The installed build has no console for print(): show a dialog
        if QApplication.instance() is not None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "Aether Term", message)
        elif sys.stdout is not None:
            print(f"\n[FATAL] {message}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
