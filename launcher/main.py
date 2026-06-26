#!/usr/bin/env python3
"""3Dosim Launcher — Entry point standalone.

Ejecutar:
    python main.py
    python main.py --debug       (modo verbose)
"""

import sys
import os

# Asegurar que podemos importar desde la raiz del proyecto
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from app import LauncherWindow

# ── Log de errores global ──
_ERROR_LOG = os.path.join(os.path.dirname(__file__), "error.log")


def _excepthook(exc_type, exc_value, exc_tb):
    """Captura cualquier excepcion no manejada y la guarda a error.log + messagebox."""
    import traceback, datetime
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"=== {now} ===\n{tb_text}\n"
    # Escribir a archivo
    try:
        with open(_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass
    # Mostrar en consola (si existe)
    print(entry, file=sys.stderr)
    # Mostrar messagebox al usuario
    try:
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("3Dosim — Error critico")
            msg.setText(f"Ocurrio un error inesperado:\n\n{exc_value}")
            msg.setDetailedText(tb_text)
            msg.exec_()
    except Exception:
        pass


sys.excepthook = _excepthook


def main():
    import argparse
    parser = argparse.ArgumentParser(description="3Dosim Launcher")
    parser.add_argument("--debug", action="store_true", help="Modo verbose")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("3Dosim Launcher")
    app.setOrganizationName("3Dosim")

    window = LauncherWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
