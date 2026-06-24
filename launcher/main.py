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

from PyQt5.QtWidgets import QApplication
from app import LauncherWindow


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
