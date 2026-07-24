from __future__ import annotations

import logging
import os
import sys
import traceback as traceback_module
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from . import __version__
from .diagnostics import configure_logging
from .main_window import MainWindow


def _install_exception_hook() -> None:
    def handle_exception(exc_type, exc_value, traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, traceback)
            return
        logging.getLogger("hp3458a_studio").critical(
            "Unhandled application exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        application = QtWidgets.QApplication.instance()
        if application is not None:
            QtWidgets.QMessageBox.critical(
                None,
                "Precision Multi-Instrument Lab Studio",
                "An unexpected error was recorded. Export a diagnostic report "
                "after reopening the application.\n\n"
                "发生未预期错误，日志已保留。重新打开软件后请导出诊断报告。",
            )

    sys.excepthook = handle_exception


def _show_fatal_startup_error(message: str) -> None:
    """Show startup failures even in the console-free Windows build."""
    application = QtWidgets.QApplication.instance()
    if application is not None:
        QtWidgets.QMessageBox.critical(
            None,
            "Precision Multi-Instrument Lab Studio",
            message,
        )
        return
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                message,
                "Precision Multi-Instrument Lab Studio",
                0x10,
            )
        except (AttributeError, OSError):
            logging.getLogger("hp3458a_studio").debug(
                "Native startup error dialog unavailable",
                exc_info=True,
            )


def _claim_single_instance(
    app: QtWidgets.QApplication,
) -> tuple[QtNetwork.QLocalServer | None, bool]:
    """Claim the application instance or notify an existing instance."""
    server_name = "LouisLab-3458A-Multi-Lab-Studio-v1"
    socket = QtNetwork.QLocalSocket(app)
    socket.connectToServer(server_name)
    if socket.waitForConnected(250):
        socket.write(b"ACTIVATE")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return None, False

    QtNetwork.QLocalServer.removeServer(server_name)
    server = QtNetwork.QLocalServer(app)
    if not server.listen(server_name):
        logging.getLogger("hp3458a_studio").warning(
            "Single-instance server unavailable | error=%s",
            server.errorString(),
        )
        return None, True
    return server, True


def main() -> int:
    try:
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        pg.setConfigOptions(antialias=False, useOpenGL=False)
        app = QtWidgets.QApplication(sys.argv)
        app.setApplicationName("Precision Multi-Instrument Lab Studio")
        app.setApplicationDisplayName("Precision Multi-Instrument Lab Studio")
        app.setApplicationVersion(__version__)
        app.setOrganizationName("Louis Lab")
        app.setStyle("Fusion")
        data_directory = Path(
            QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        )
        configure_logging(data_directory)
        _install_exception_hook()
        logging.getLogger("hp3458a_studio").info(
            "Application start | version=%s | platform=%s",
            __version__,
            sys.platform,
        )
        instance_server, is_primary = _claim_single_instance(app)
        if not is_primary:
            logging.getLogger("hp3458a_studio").info(
                "Existing application instance activated"
            )
            return 0

        font = QtGui.QFont("Segoe UI", 10)
        app.setFont(font)
        window = MainWindow()

        def activate_window() -> None:
            if window._shutdown_in_progress:
                return
            while (
                instance_server is not None and instance_server.hasPendingConnections()
            ):
                connection = instance_server.nextPendingConnection()
                connection.waitForReadyRead(100)
                connection.readAll()
                connection.disconnectFromServer()
            window.showNormal()
            window.raise_()
            window.activateWindow()

        if instance_server is not None:
            instance_server.newConnection.connect(activate_window)
        window.show()
        screenshot_path = os.environ.get("HP3458A_SCREENSHOT")
        if screenshot_path:

            def save_and_quit() -> None:
                window.grab().save(screenshot_path)
                window.close()

            QtCore.QTimer.singleShot(1800, save_and_quit)
        exit_code = app.exec()
        logging.getLogger("hp3458a_studio").info(
            "Application exit | code=%s", exit_code
        )
        return exit_code
    except Exception as exc:
        details = "".join(traceback_module.format_exception(exc))
        logging.getLogger("hp3458a_studio").critical(
            "Fatal application startup error", exc_info=True
        )
        _show_fatal_startup_error(
            "The application could not start. The error was saved to "
            "application.log.\n\n"
            "软件无法启动，错误已写入 application.log。\n\n"
            f"{details[-1800:]}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
