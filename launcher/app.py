"""
app.py — Ventana principal del lanzador 3Dosim.

3 botones (Mod1/Mod2/Mod3) que al hacer clic muestran un dialogo
de configuracion y luego lanzan 3D Slicer con el pipeline correspondiente.

Mod1 usa CT/PET separados, tumor condicional y TotalSegmentator siempre.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

from PyQt5.QtCore import (
    Qt, QTimer, QThread, QObject, pyqtSignal, QSize, QProcess, QUrl
)
from PyQt5.QtGui import (
    QFont, QIcon, QPixmap, QColor, QPalette, QTextCursor,
    QDesktopServices, QLinearGradient, QBrush, QPen, QPainter,
)
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QTextEdit, QLineEdit, QDialog,
    QDialogButtonBox, QFileDialog, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QGroupBox, QScrollArea, QSplitter,
    QTabWidget, QMessageBox, QProgressBar, QListWidget, QListWidgetItem,
    QSizePolicy, QGridLayout, QMenu, QAction, QStatusBar, QToolButton,
)

# ── Logging ──
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("Launcher")

# ── Trace file log (para debug de crash — el UI log no alcanza) ──
_TRACE_LOG = os.path.join(os.path.dirname(__file__), "trace.log")
def _trace(msg: str):
    """Escribe a trace.log con timestamp. No falla si no puede."""
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(_TRACE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# ── Paths ──
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_VERSION = "v4.0"
_SLICER_EXE = r"C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe"
_MAIN_PIPELINE = os.path.join(_PROJECT_ROOT, "PipelineOrchestrator", "main.py")
_RUN_DOSIMETRY = os.path.join(_PROJECT_ROOT, "PipelineOrchestrator", "run_dosimetry_from_scene.py")
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "PipelineOrchestrator", "pipeline_config.jsonc")
# ── Colores ──
MOD1_COLOR = "#2196F3"
MOD2_COLOR = "#FF9800"
MOD3_COLOR = "#4CAF50"
BG_DARK = "#1e1e2e"
BG_CARD = "#2a2a3e"
BG_INPUT = "#252540"
TEXT_PRIMARY = "#cdd6f4"
TEXT_SECONDARY = "#a6adc8"
TEXT_MUTED = "#6c7086"
BORDER = "#313244"
SUCCESS = "#a6e3a1"
ERROR = "#f38ba8"


# ======================================================================
# UTILITY: Load/save config.jsonc
# ======================================================================

def _load_config() -> dict:
    """Carga config.jsonc (soporta // comments)."""
    if not os.path.exists(_CONFIG_PATH):
        logger.warning(f"Config no encontrado: {_CONFIG_PATH}")
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        raw = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Error cargando config: {e}")
        return {}


def _save_config(config: dict) -> bool:
    """Guarda config.jsonc (hace backup primero)."""
    if not os.path.exists(_CONFIG_PATH):
        logger.error(f"No se puede guardar: {_CONFIG_PATH} no existe")
        return False
    try:
        # Backup
        backup = _CONFIG_PATH + ".bak"
        shutil.copy2(_CONFIG_PATH, backup)
        # Write (pretty-printed, sin // comments)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"Config guardado (backup: {backup})")
        return True
    except Exception as e:
        logger.error(f"Error guardando config: {e}")
        return False


# ======================================================================
# STYLESHEET GLOBAL
# ======================================================================

APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Roboto", sans-serif;
}}
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#title {{
    font-size: 26px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}
QLabel#subtitle {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}
QLabel#status {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
    padding: 4px 0;
}}
QLabel#section {{
    font-size: 14px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
    padding: 8px 0 4px 0;
}}
QFrame#separator {{
    background-color: {BORDER};
    max-height: 1px;
}}
QTextEdit, QLineEdit {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    font-size: 13px;
}}
QTextEdit {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}}
QComboBox {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 20px;
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    selection-background-color: #45475a;
    border: 1px solid {BORDER};
}}
QSpinBox, QDoubleSpinBox {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 22px;
}}
QCheckBox {{
    spacing: 10px;
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 5px;
    border: 2px solid {BORDER};
}}
QCheckBox::indicator:checked {{
    background-color: {MOD2_COLOR};
    border-color: {MOD2_COLOR};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {BG_DARK};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QStatusBar {{
    background-color: {BG_CARD};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: 12px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-size: 14px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {TEXT_SECONDARY};
    font-weight: normal;
    font-size: 12px;
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: 12px;
    background-color: {BG_CARD};
    height: 22px;
}}
QProgressBar::chunk {{
    background-color: {MOD1_COLOR};
    border-radius: 7px;
}}
QDialog {{
    background-color: {BG_DARK};
}}
"""


# ======================================================================
# BOTON MODULO (widget reutilizable)
# ======================================================================

class ModuleButton(QPushButton):
    """Boton estilizado para cada modulo."""

    def __init__(self, mod_id: int, title: str, subtitle: str,
                 icon: str, color: str, parent=None):
        super().__init__(parent)
        self.mod_id = mod_id
        self._color = color
        self._hover_color = self._lighten(color, 0.25)
        self._pressed_color = self._lighten(color, 0.4)
        self.setMinimumHeight(130)
        self.setMinimumWidth(260)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self._style())

        # Layout interno del boton
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(6)

        # Icono + titulo
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"font-size: 28px;")
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        title_row.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: bold;"
        )
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        title_row.addWidget(title_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Subtitulo
        sub_label = QLabel(subtitle)
        sub_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        sub_label.setWordWrap(True)
        sub_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(sub_label)

    def _lighten(self, hex_color: str, factor: float) -> str:
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _style(self) -> str:
        return f"""
        QPushButton {{
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._color}15,
                stop:1 {self._color}05);
            border: 2px solid {self._color}44;
            border-radius: 18px;
            text-align: left;
        }}
        QPushButton:hover {{
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._color}30,
                stop:1 {self._color}10);
            border-color: {self._color};
        }}
        QPushButton:pressed {{
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._color}50,
                stop:1 {self._color}20);
        }}
        """


# ======================================================================
# CONFIG DIALOG
# ======================================================================

class ConfigDialog(QDialog):
    """Dialogo de configuracion pre-ejecucion para cada modulo."""

    # Campos por modulo: (label, key, tipo, default, [opciones])
    MOD1_FIELDS = [
        ("ID Paciente",                         "patient_id",     "text",   ""),
        ("Directorio CT",                       "ct_dir",         "dir",    ""),
        ("Directorio PET",                      "pet_dir",        "dir",    ""),
        ("Modo tumor",                          "tumor_mode",     "combo",  "synthetic",
         ["synthetic", "load_file", "manual", "ts_liver_lesions"]),
        ("Radio tumor sintetico (mm)",          "tumor_radius",   "spin",   10),
        ("Archivo tumor NIfTI (load_file)",     "tumor_file",     "file",   ""),
        ("",                                     "",              "sep",    ""),
        ("Interpolacion resample PET→CT",       "resample_interp","combo",  "NearestNeighbor",
         ["NearestNeighbor", "Linear", "BSpline", "WindowedSinc", "ResampleInPlace"]),
        ("",                                     "",              "sep",    ""),
        ("TS Fast mode",                         "ts_fast",       "check",  True),
        ("TS Force CPU",                         "ts_force_cpu",  "check",  True),
    ]
    # Indices de campos de tumor condicionales en MOD1_FIELDS
    _TUMOR_RADIUS_KEY = "tumor_radius"
    _TUMOR_FILE_KEY = "tumor_file"
    MOD2_FIELDS = [
        ("Escena .mrb (de Mod1)",               "scene_path",     "file",   ""),
        ("Isotopo",                             "isotope",        "combo",  "Y-90",
         ["Y-90", "I-131", "Lu-177", "Tc-99m", "Ho-166"]),
        ("Particulas (NPS)",                     "n_particles",   "spin_int", 10000000),
        ("Flip Y (compat MATLAB)",              "flip_y",         "check",  True),
        ("Flip Z",                              "flip_z",         "check",  False),
        ("Refinar HU -> materiales",            "refine_hu",      "check",  False),
    ]
    MOD3_FIELDS = [
        ("Escena .mrb",                         "scene_path",     "file",   ""),
        ("Metodo",                              "method",         "combo",  "Kernel",
         ["Kernel", "MCTAL"]),
        ("Archivo Kernel .mat",                  "kernel_path",   "file",   ""),
        ("Archivo MCTAL/MCTALL",                 "mctal_path",    "file",   ""),
        ("Actividad GBq (-1=auto desde PET)",   "activity_gbq",   "spin",   -1.0),
        ("",                                     "",              "sep",    ""),
        ("Generar reporte PDF (tarda ~30-60s)",  "gen_pdf",       "check",  True),
    ]
    # Keys condicionales para toggle method
    _MCTAL_PATH_KEY = "mctal_path"
    _KERNEL_PATH_KEY = "kernel_path"

    MOD_INFO = {
        1: ("Modulo 1", "Segmentacion + Tumor", MOD1_COLOR, MOD1_FIELDS),
        2: ("Modulo 2", "Generacion MCNP", MOD2_COLOR, MOD2_FIELDS),
        3: ("Modulo 3", "Analisis Dosimetrico", MOD3_COLOR, MOD3_FIELDS),
    }

    def __init__(self, mod_id: int, parent=None, defaults: dict = None):
        super().__init__(parent)
        self.mod_id = mod_id
        self._defaults = defaults or {}
        self._result = {}
        self._widgets: dict[str, QWidget] = {}
        self._conditional_rows: dict[str, QWidget] = {}

        title, subtitle, color, fields = self.MOD_INFO[mod_id]

        self.setWindowTitle(f"3Dosim — {title}")
        self.setMinimumWidth(540)
        self.setModal(True)
        self.setStyleSheet(APP_STYLESHEET)

        # Layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(8)

        # Header
        hdr = QLabel(f"<span style='color:{color}; font-size:22px; font-weight:bold;'>"
                     f"{title}</span><br>"
                     f"<span style='color:{TEXT_SECONDARY}; font-size:13px;'>"
                     f"{subtitle}</span>")
        hdr.setTextFormat(Qt.RichText)
        outer.addWidget(hdr)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background: {BORDER}; max-height:1px; margin:8px 0;")
        outer.addWidget(sep)

        # Scroll area para campos
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_container = QWidget()
        form = QVBoxLayout(scroll_container)
        form.setSpacing(10)

        for field in fields:
            label, key, ftype, default = field[:4]
            options = field[4] if len(field) > 4 else None
            is_conditional = (
                key in (self._TUMOR_RADIUS_KEY, self._TUMOR_FILE_KEY) or
                key in (self._MCTAL_PATH_KEY, self._KERNEL_PATH_KEY)
            )

            # Separador
            if ftype == "sep":
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet(f"background: {BORDER}; max-height:1px; margin:6px 0;")
                form.addWidget(sep)
                continue

            row = QHBoxLayout()
            row.setSpacing(12)

            lbl = QLabel(label + ":")
            lbl.setFixedWidth(190)
            lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
            row.addWidget(lbl)

            if ftype == "check":
                w = QCheckBox()
                w.setChecked(default if isinstance(default, bool) else False)
                self._widgets[key] = w
                row.addWidget(w)
                row.addStretch()

            elif ftype == "combo":
                w = QComboBox()
                if options:
                    for opt in options:
                        w.addItem(opt)
                self._widgets[key] = w
                row.addWidget(w, 1)

            elif ftype == "spin":
                w = QDoubleSpinBox()
                w.setRange(-999999, 999999)
                w.setDecimals(2)
                w.setSingleStep(0.1)
                w.setValue(float(default) if isinstance(default, (int, float)) else 0)
                self._widgets[key] = w
                row.addWidget(w, 1)

            elif ftype == "spin_int":
                w = QSpinBox()
                w.setRange(100, 999999999)
                w.setSingleStep(1000000)
                w.setValue(int(default) if isinstance(default, (int, float)) else 10000000)
                self._widgets[key] = w
                row.addWidget(w, 1)

            elif ftype == "dir":
                w = QLineEdit(str(default) if default else "")
                self._widgets[key] = w
                row.addWidget(w, 1)
                browse = QPushButton("...")
                browse.setFixedWidth(36)
                browse.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_CARD}; color: {TEXT_PRIMARY};
                        border: 1px solid {BORDER}; border-radius: 6px;
                        font-size: 16px; font-weight: bold;
                    }}
                    QPushButton:hover {{ background: {BORDER}; }}
                """)
                browse.clicked.connect(lambda _, k=key: self._browse_dir(k))
                row.addWidget(browse)

            elif ftype == "file":
                w = QLineEdit(str(default) if default else "")
                self._widgets[key] = w
                row.addWidget(w, 1)
                browse = QPushButton("...")
                browse.setFixedWidth(36)
                browse.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_CARD}; color: {TEXT_PRIMARY};
                        border: 1px solid {BORDER}; border-radius: 6px;
                        font-size: 16px; font-weight: bold;
                    }}
                    QPushButton:hover {{ background: {BORDER}; }}
                """)
                browse.clicked.connect(lambda _, k=key: self._browse_file(k))
                row.addWidget(browse)

            # Wrap conditional rows in container for show/hide
            if is_conditional:
                container = QWidget()
                container.setLayout(row)
                self._conditional_rows[key] = container
                form.addWidget(container)
            else:
                form.addLayout(row)

        form.addStretch()
        scroll.setWidget(scroll_container)
        outer.addWidget(scroll, 1)

        # ── Botones ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: 10px;
                padding: 10px 28px; font-size: 14px;
            }}
            QPushButton:hover {{ background-color: #45475a; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        accept_btn = QPushButton("Ejecutar")
        accept_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {color}, stop:1 {color}cc);
                color: white; border: none; border-radius: 10px;
                padding: 10px 32px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color};
            }}
        """)
        accept_btn.clicked.connect(self.accept)
        btn_layout.addWidget(accept_btn)

        outer.addLayout(btn_layout)

        # ── Cargar defaults ──
        self._apply_defaults()

        # ── Tumor mode conditional visibility ──
        self._setup_tumor_mode_visibility()
        # ── Method conditional visibility ──
        self._setup_method_visibility()

    def _setup_method_visibility(self):
        """Conecta el combo 'method' para mostrar/ocultar MCTAL vs Kernel."""
        if self.mod_id != 3:
            return
        combo = self._widgets.get("method")
        if combo is None or not isinstance(combo, QComboBox):
            return
        def _toggle(selected_text: str):
            show_kernel = selected_text == "Kernel"
            show_mctal = selected_text == "MCTAL"
            for key, container in self._conditional_rows.items():
                if key == self._KERNEL_PATH_KEY:
                    container.setVisible(show_kernel)
                elif key == self._MCTAL_PATH_KEY:
                    container.setVisible(show_mctal)
            self.adjustSize()
        combo.currentTextChanged.connect(_toggle)
        _toggle(combo.currentText())

    def _setup_tumor_mode_visibility(self):
        """Conecta el combo tumor_mode para mostrar/ocultar campos condicionales."""
        combo = self._widgets.get("tumor_mode")
        if combo is None or not isinstance(combo, QComboBox):
            return
        def _toggle(selected_text: str):
            show_radius = selected_text == "synthetic"
            show_file = selected_text == "load_file"
            for key, container in self._conditional_rows.items():
                if key == self._TUMOR_RADIUS_KEY:
                    container.setVisible(show_radius)
                elif key == self._TUMOR_FILE_KEY:
                    container.setVisible(show_file)
            # Ajustar altura minima del dialogo
            self.adjustSize()
        combo.currentTextChanged.connect(_toggle)
        # Aplicar estado inicial
        _toggle(combo.currentText())

    def _apply_defaults(self):
        """Aplica valores por defecto desde config o defaults."""
        config = _load_config()
        for field in self.MOD_INFO[self.mod_id][3]:
            label, key, ftype, default = field[:4]
            options = field[4] if len(field) > 4 else None

            # Buscar valor
            value = self._defaults.get(key)
            if value is None:
                value = self._get_config_value(config, key, default)

            w = self._widgets.get(key)
            if w is None:
                continue

            try:
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(value) if value else False)
                elif isinstance(w, QComboBox):
                    idx = w.findText(str(value))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif isinstance(w, QDoubleSpinBox):
                    w.setValue(float(value))
                elif isinstance(w, QSpinBox):
                    w.setValue(int(value))
                elif isinstance(w, QLineEdit):
                    w.setText(str(value) if value else "")
            except Exception as e:
                logger.warning(f"Error default {key}: {e}")

    def _get_config_value(self, config: dict, key: str, default):
        key_map = {
            "patient_id": ("paths", "patient_id"),
            "ct_dir": ("paths", "ct_dir"),
            "pet_dir": ("paths", "pet_dir"),
            "segmenter": ("segmentation", "method"),
            "force_cpu": ("segmentation", "totalsegmentator", "force_cpu"),
            "ts_fast": ("segmentation", "totalsegmentator", "fast"),
            "ts_force_cpu": ("segmentation", "totalsegmentator", "force_cpu"),
            "tumor_mode": ("tumor", "mode"),
            "tumor_radius": ("tumor", "synthetic_radius_mm"),
            "tumor_file": ("tumor", "load_file_path"),
            "resample_interp": ("resample", "interpolation"),
            "isotope": ("mcnp_source", "isotope"),
            "n_particles": ("mcnp_run", "n_particles"),
            "flip_y": ("geometry", "flip_y"),
            "flip_z": ("geometry", "flip_z"),
            "refine_hu": ("mcnp_run", "refine_hu"),
            "kernel_path": ("paths", "kernel_path"),
        }
        path = key_map.get(key)
        if path:
            try:
                v = config
                for p in path:
                    v = v.get(p, {})
                if v != {}:
                    return v
            except Exception:
                pass
        return default

    def _browse_dir(self, key: str):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar directorio")
        _trace(f"ConfigDialog._browse_dir({key!r}) → {(path[:80] if path else 'CANCEL')!r}")
        if path and key in self._widgets:
            if isinstance(self._widgets[key], QLineEdit):
                self._widgets[key].setText(path)

    def _browse_file(self, key: str):
        """Abre selector de archivo con filtro especifico segun key."""
        if key == "scene_path":
            filtro = "Escenas (*.mrb)"
        elif key == "mctal_path":
            filtro = "Output MCNP (*.mctal *.mctall *.m)"
        elif key == "tumor_file":
            filtro = "Imagenes (*.nii *.nii.gz *.nrrd)"
        else:
            filtro = "All files (*)"
        # DEBUG: loguear al parent si existe (se ve en el panel del launcher)
        parent_win = self.parent()
        if parent_win and hasattr(parent_win, '_log'):
            parent_win._log.log(f"[FILTRO] key={key!r} → {filtro}", "info")
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo", "", filtro, filtro
        )
        _trace(f"ConfigDialog._browse_file({key!r}, filtro={filtro!r}) → {(path[:80] if path else 'CANCEL')!r}")
        if path and key in self._widgets:
            if isinstance(self._widgets[key], QLineEdit):
                self._widgets[key].setText(path)

    def get_config(self) -> dict:
        result = {}
        for field in self.MOD_INFO[self.mod_id][3]:
            label, key, ftype, default = field[:4]
            w = self._widgets.get(key)
            if w is None:
                continue
            try:
                if isinstance(w, QCheckBox):
                    result[key] = w.isChecked()
                elif isinstance(w, QComboBox):
                    result[key] = w.currentText()
                elif isinstance(w, QDoubleSpinBox):
                    result[key] = w.value()
                elif isinstance(w, QSpinBox):
                    result[key] = int(w.value())
                elif isinstance(w, QLineEdit):
                    result[key] = w.text().strip()
            except Exception:
                result[key] = default
        return result


# ======================================================================
# LOG PANEL
# ======================================================================

class LogPanel(QTextEdit):
    """Panel de registro de eventos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(180)
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: #11111b;
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
            }}
        """)

    def log(self, msg: str, level: str = "info"):
        colors = {"info": TEXT_SECONDARY, "ok": SUCCESS, "error": ERROR, "warn": "#f9e2af"}
        c = colors.get(level, TEXT_SECONDARY)
        ts = time.strftime("%H:%M:%S")
        self.append(f"<span style='color:{TEXT_MUTED};'>[{ts}]</span> "
                     f"<span style='color:{c};'>{msg}</span>")
        # Auto-scroll
        sb = self.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())


# ── Helper: traer ventana Slicer al frente ──
def _bring_window_to_front(pid: int):
    """Trae la ventana principal de Slicer al frente usando PowerShell."""
    try:
        subprocess.Popen(
            f'powershell -command "(Get-Process -Id {pid}).MainWindowHandle | '
            f'ForEach-Object {{ [void][User32]::SetForegroundWindow($_) }}"',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

# Alternativa usando PowerShell con legacy AppActivate
def _activate_slicer_window():
    """Activa cualquier ventana que tenga 'Slicer' en el titulo."""
    try:
        subprocess.Popen(
            'powershell -command "(New-Object -ComObject WScript.Shell).AppActivate(\'Slicer\')"',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


# ======================================================================
# DIALOGO DE CONFIGURACION GLOBAL (paths)
# ======================================================================

class SettingsDialog(QDialog):
    """Dialogo para configurar paths globales del pipeline."""

    PATH_FIELDS = [
        ("Directorio escenas .mrb",                 "scene_output_dir"),
        ("Directorio screenshots",                  "screenshot_output_dir"),
        ("Directorio imagenes NIfTI/NRRD",          "image_output_dir"),
        ("Directorio MCNP output",                  "mcnp_output_dir"),
        ("Directorio de resultados (relativo)",     "results_dir_rel"),
        ("Path tissue_config.json",                 "tissue_config_path"),
        ("Path archivo fuente MCNP (.src)",         "source_file_path"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuracion Global — Paths")
        self.setMinimumWidth(580)
        self._widgets: dict[str, QLineEdit] = {}

        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
            }}
            QLabel {{
                color: {TEXT_SECONDARY};
                font-size: 13px;
            }}
            QLineEdit {{
                background: {BG_INPUT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
            }}
            QPushButton {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {BORDER};
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # Titulo
        title = QLabel("Rutas del pipeline")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        outer.addWidget(title)

        subtitle = QLabel("Configure los directorios donde se guardan escenas, resultados, etc.")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        # Form
        config = _load_config()
        paths = config.get("paths", {})

        for label, key in self.PATH_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(10)

            lbl = QLabel(label + ":")
            lbl.setFixedWidth(200)
            row.addWidget(lbl)

            w = QLineEdit(str(paths.get(key, "")))
            self._widgets[key] = w
            row.addWidget(w, 1)

            browse = QPushButton("...")
            browse.setFixedWidth(36)
            browse.clicked.connect(lambda checked=False, k=key: self._browse(k))
            row.addWidget(browse)

            outer.addLayout(row)

        outer.addStretch()

        # Botones
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Guardar")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #00897b; color: white;
                border: none; border-radius: 8px;
                padding: 8px 24px; font-weight: bold;
            }
            QPushButton:hover { background-color: #00695c; }
        """)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        outer.addLayout(btn_layout)

    def _browse(self, key: str):
        """Abre selector de directorio."""
        path = QFileDialog.getExistingDirectory(self, "Seleccionar directorio")
        if path and key in self._widgets:
            self._widgets[key].setText(path)

    def _on_save(self):
        """Guarda los paths en config.jsonc."""
        try:
            cfg = _load_config()
            paths = cfg.setdefault("paths", {})
            for key, w in self._widgets.items():
                val = w.text().strip()
                if val:
                    paths[key] = val
            _save_config(cfg)
            QMessageBox.information(self, "Configuracion",
                                     "Paths guardados correctamente.")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {e}")


# ======================================================================
# VENTANA PRINCIPAL
# ======================================================================

class _SlicerDoneSignal(QObject):
    """Worker QObject para emitir señal thread->main de forma segura."""
    finished = pyqtSignal(int, int)  # mod_id, return_code
    log_line = pyqtSignal(str, str)  # text, level (info|warn|error|ok)


class LauncherWindow(QMainWindow):
    """Ventana principal con 3 botones, log y dialogo de config."""

    MODULES = [
        (1, "Modulo 1", "Segmentacion IA + Tumor",
         "🔬", MOD1_COLOR,
         "Carga DICOM, TotalSegmentator, tumor sintetico,\n"
         "higado sano, body, export labelmap"),
        (2, "Modulo 2", "Generacion MCNP",
         "⚛", MOD2_COLOR,
         "Carga escena .mrb, geometria voxelizada,\n"
         "materiales, fuente PET, tallies"),
        (3, "Modulo 3", "Analisis Dosimetrico",
         "📊", MOD3_COLOR,
         "Parseo MCTAL, DVH, BED, EUD, EQD2,\n"
         "TCP/NTCP, reporte PDF"),
    ]

    def __init__(self):
        super().__init__()
        self._slicer_process: Optional[QProcess] = None
        self._build_ui()
        # Señal para comunicacion thread-safe desde el monitor thread
        self.slicer_done = _SlicerDoneSignal()
        self.slicer_done.finished.connect(self._on_slicer_done)

    def _build_ui(self):
        self.setWindowTitle("3Dosim Launcher v4.0")
        self.setMinimumSize(820, 680)
        self.setStyleSheet(APP_STYLESHEET)

        # ── Central widget ──
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(10)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(14)

        logo = QLabel("🎯")
        logo.setStyleSheet("font-size: 42px;")
        header.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        t = QLabel("3Dosim Launcher")
        t.setObjectName("title")
        title_box.addWidget(t)
        st = QLabel("Dosimetria 3D para Medicina Nuclear — Radioembolizacion Hepatica")
        st.setObjectName("subtitle")
        title_box.addWidget(st)
        header.addLayout(title_box, 1)

        # Version badge
        ver = QLabel("v4.0")
        ver.setStyleSheet(f"""
            background: #00897b; color: white;
            padding: 4px 12px; border-radius: 10px;
            font-size: 12px; font-weight: bold;
        """)
        header.addWidget(ver)

        # Settings gear button
        gear = QPushButton("⚙")
        gear.setToolTip("Configurar paths del pipeline")
        gear.setFixedSize(36, 36)
        gear.setStyleSheet(f"""
            QPushButton {{
                background: {BG_CARD}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER}; border-radius: 18px;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background: {BORDER}; color: {TEXT_PRIMARY};
            }}
        """)
        gear.clicked.connect(self._on_settings)
        header.addWidget(gear)

        layout.addLayout(header)

        # Separador
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Subtitulo seccion
        sec = QLabel("Seleccione modulo a ejecutar:")
        sec.setObjectName("section")
        layout.addWidget(sec)

        # ── 3 Botones ──
        for mod_id, title, subtitle, icon, color, desc in self.MODULES:
            btn = ModuleButton(mod_id, title, subtitle, icon, color)
            btn.clicked.connect(lambda checked=False, m=mod_id: self._on_module_click(m))

            # Sombra sutil en cada boton
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(18)
            shadow.setColor(QColor(0, 0, 0, 50))
            shadow.setOffset(0, 3)
            btn.setGraphicsEffect(shadow)

            # Descripcion debajo
            desc_label = QLabel(desc)
            desc_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; "
                                      f"padding-left: 8px;")
            layout.addWidget(btn)
            layout.addWidget(desc_label)

        layout.addSpacing(6)

        # ── Status + Progress ──
        self._status = QLabel("Listo. Seleccione un modulo para comenzar.")
        self._status.setObjectName("status")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── Log ──
        self._log = LogPanel()
        layout.addWidget(self._log, 1)

        # ── Status bar ──
        self._sbar = QStatusBar()
        self._sbar.setStyleSheet(f"""
            QStatusBar {{
                background: {BG_CARD};
                border-top: 1px solid {BORDER};
                color: {TEXT_MUTED};
                font-size: 11px;
                padding: 2px 12px;
            }}
            QStatusBar::item {{ border: none; }}
        """)
        self.setStatusBar(self._sbar)
        self._sbar.showMessage("Listo")
        self._sbar.insertPermanentWidget(0, QLabel("v4.0 · PyQt5 · 3D Slicer"))

        # ── Log startup ──
        self._log.log("3Dosim Launcher iniciado")
        self._log.log(f"Slicer: {_SLICER_EXE}")
        self._log.log(f"Pipeline main: {_MAIN_PIPELINE}")

    def _on_settings(self):
        """Abre dialogo de configuracion global de paths."""
        dlg = SettingsDialog(self)
        dlg.exec()

    # ────────────────────────────────────────────────────────────
    # EVENTOS
    # ────────────────────────────────────────────────────────────

    def _on_module_click(self, mod_id: int):
        """Manejador: ejecuta modulo.
        Todos los modulos muestran dialogo de config pre-poblado.
        """
        _trace(f"_on_module_click({mod_id}) — inicio")
        self._log.log(f"▶ Preparando Modulo {mod_id}...")
        config = _load_config()
        defaults = self._get_defaults(mod_id, config)

        # Todos los modulos muestran dialogo de config
        dialog = ConfigDialog(mod_id, self, defaults=defaults)
        if dialog.exec() != QDialog.Accepted:
            self._log.log(f"Mod{mod_id}: configuracion cancelada", "warn")
            return

        user_config = dialog.get_config()
        _trace(f"_on_module_click({mod_id}) — config aceptada: {user_config}")
        self._log.log(f"Mod{mod_id}: Configuracion aceptada", "ok")
        for k, v in user_config.items():
            s = str(v)
            if len(s) > 50:
                s = s[:47] + "..."
            if v:
                self._log.log(f"  {k} = {s}")

        self._launch_slicer(mod_id, user_config)

    def _get_defaults(self, mod_id: int, config: dict) -> dict:
        """Extrae defaults de config.jsonc para el modulo.
        Todos los campos se pre-pueblan para que el usuario solo tenga que
        aceptar (o ajustar si quiere).
        """
        defaults = {}
        paths = config.get("paths", {})

        # Default data dirs
        _DEFAULT_PARENT = r"C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2"
        _DEFAULT_CT = os.path.join(_DEFAULT_PARENT, "CT")
        _DEFAULT_PET = os.path.join(_DEFAULT_PARENT, "PET")

        if mod_id == 1:
            # Intentar inferir patient_id del nombre del directorio padre de CT
            auto_patient = os.path.basename(os.path.dirname(paths.get("ct_dir", _DEFAULT_CT)))
            defaults["patient_id"] = paths.get("patient_id", auto_patient)
            defaults["ct_dir"] = paths.get("ct_dir", _DEFAULT_CT)
            defaults["pet_dir"] = paths.get("pet_dir", _DEFAULT_PET)
            tc = config.get("tumor", {})
            defaults["tumor_mode"] = tc.get("mode", "synthetic")
            defaults["tumor_radius"] = tc.get("synthetic_radius_mm", 10)
            defaults["tumor_file"] = tc.get("load_file_path", "")
            ts = config.get("segmentation", {}).get("totalsegmentator", {})
            defaults["ts_fast"] = ts.get("fast", True)
            defaults["ts_force_cpu"] = ts.get("force_cpu", True)
            defaults["resample_interp"] = config.get("resample", {}).get("interpolation", "NearestNeighbor")

        elif mod_id == 2:
            # Auto-detectar scene_path desde scene_output_dir del config central
            scene_dir = config.get("scene_output_dir", "")
            if not scene_dir:
                data_dir = config.get("paths", {}).get("ct_dir", _DEFAULT_PARENT)
                scene_dir = os.path.join(os.path.dirname(data_dir), "ai-pipe", "scenes")
            scene_guess = os.path.join(scene_dir, "3Dosim.mrb")
            defaults["scene_path"] = scene_guess if os.path.exists(scene_guess) else ""
            defaults["isotope"] = config.get("mcnp_source", {}).get("isotope", "Y-90")
            defaults["n_particles"] = config.get("mcnp_run", {}).get("n_particles", 10000000)
            defaults["flip_y"] = config.get("geometry", {}).get("flip_y", True)
            defaults["flip_z"] = config.get("geometry", {}).get("flip_z", False)
            defaults["refine_hu"] = config.get("mcnp_run", {}).get("refine_hu", False)

        elif mod_id == 3:
            # Auto-detectar escena (funciona bien)
            scene_dir = config.get("scene_output_dir", "")
            if not scene_dir:
                data_dir = config.get("paths", {}).get("ct_dir", _DEFAULT_PARENT)
                scene_dir = os.path.join(os.path.dirname(data_dir), "ai-pipe", "scenes")
            scene_guess = os.path.join(scene_dir, "3Dosim.mrb")
            defaults["scene_path"] = scene_guess if os.path.exists(scene_guess) else ""
            # Kernel es el metodo default V4, kernel_path es fijo del proyecto
            defaults["kernel_path"] = os.path.join(
                _PROJECT_ROOT, "kernel", "kernel.mat"
            )

        return defaults

    # ────────────────────────────────────────────────────────────
    # LAUNCH SLICER
    # ────────────────────────────────────────────────────────────

    def _kill_slicer(self):
        """Mata cualquier proceso Slicer existente para evitar single-instance conflict."""
        try:
            import subprocess
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-Process -Name 'Slicer' -ErrorAction SilentlyContinue | Stop-Process -Force"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                self._log.log("Slicer previo cerrado (evita single-instance conflict)", "ok")
            # Esperar a que el proceso termine
            import time
            time.sleep(1)
        except Exception as e:
            self._log.log(f"Error cerrando Slicer previo: {e}", "warn")

    def _launch_slicer(self, mod_id: int, config: dict):
        """Lanza Slicer con el pipeline correspondiente."""
        _trace(f"_launch_slicer({mod_id}) — inicio")
        # Matar Slicer previo ANTES de lanzar uno nuevo (single-instance)
        self._kill_slicer()
        if not os.path.exists(_SLICER_EXE):
            _trace(f"_launch_slicer — SLICER_EXE no existe: {_SLICER_EXE}")
            QMessageBox.critical(self, "Error",
                                 f"Slicer no encontrado:\n{_SLICER_EXE}")
            return
        if not os.path.exists(_MAIN_PIPELINE):
            _trace(f"_launch_slicer — MAIN_PIPELINE no existe: {_MAIN_PIPELINE}")
            QMessageBox.critical(self, "Error",
                                 f"Pipeline no encontrado:\n{_MAIN_PIPELINE}")
            return

        # 1. Guardar config temporal con las opciones del usuario
        _trace(f"_launch_slicer({mod_id}) — aplicando config override")
        self._apply_config_override(mod_id, config)

        # 2. Construir comando como LISTA (sin comillas embebidas — shell=False)
        script_path = _MAIN_PIPELINE if mod_id in (1, 2) else _RUN_DOSIMETRY
        cmd = [_SLICER_EXE, "--python-script", script_path]

        if mod_id == 1:
            cmd += ["--modulo", "1"]
            ct_dir = config.get("ct_dir", "")
            pet_dir = config.get("pet_dir", "")
            if ct_dir and pet_dir:
                parent = os.path.commonpath([ct_dir, pet_dir])
            elif ct_dir:
                parent = os.path.dirname(ct_dir)
            elif pet_dir:
                parent = os.path.dirname(pet_dir)
            else:
                parent = r"C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2"
            cmd += ["--data-dir", parent]
            cmd += ["--segmenter", "totalsegmentator"]
            if config.get("ts_fast", True):
                cmd.append("--fast")
            if config.get("ts_force_cpu", True):
                cmd.append("--force-cpu")
            pid = config.get("patient_id", "").strip()
            if pid:
                cmd += ["--patient-id", pid]
            cmd.append("--reset")

        elif mod_id == 2:
            cmd += ["--modulo", "2"]
            scene = config.get("scene_path", "")
            if scene:
                if not os.path.exists(scene):
                    QMessageBox.warning(self, "Error",
                                        f"Escena no encontrada:\n{scene}")
                    return
            cmd += ["--scene-path", scene]
            iso = config.get("isotope", "Y-90")
            cmd += ["--isotope", iso]
            nps = config.get("n_particles", 10000000)
            cmd += ["--n-particles", str(nps)]
            if config.get("flip_y", True):
                cmd.append("--flip")
            if config.get("flip_z", False):
                cmd.append("--flip-z")
            if config.get("refine_hu", False):
                cmd.append("--refine-hu")
            cmd.append("--reset")

        elif mod_id == 3:
            scene = config.get("scene_path", "")
            if not scene:
                QMessageBox.warning(self, "Error",
                    "Debe seleccionar una escena .mrb (use el boton '...' junto a 'Escena .mrb')")
                return
            if not os.path.exists(scene):
                QMessageBox.warning(self, "Error",
                                    f"Escena no encontrada:\n{scene}")
                return
            cmd += ["--scene-path", scene]

            method = config.get("method", "Kernel")
            if method == "Kernel":
                kernel = config.get("kernel_path", "")
                if not kernel or not os.path.exists(kernel):
                    QMessageBox.warning(self, "Error",
                                        f"Kernel .mat no encontrado:\n{kernel}")
                    return
                cmd += ["--kernel", kernel]
            else:  # MCTAL
                mctal = config.get("mctal_path", "")
                if not mctal:
                    QMessageBox.warning(self, "Error",
                        "Debe seleccionar un archivo MCTAL para el metodo MCTAL.")
                    return
                if not os.path.exists(mctal):
                    QMessageBox.warning(self, "Error",
                                        f"MCTAL no encontrado:\n{mctal}")
                    return
                cmd += ["--mctal", mctal]

            act = config.get("activity_gbq", -1.0)
            if act > 0:
                cmd += ["--activity", str(act)]

            gen_pdf = config.get("gen_pdf", True)
            if not gen_pdf:
                cmd.append("--no-pdf")

            # Mantener Slicer abierto para visualizar dosis
            cmd.append("--show")

        # String solo para display (con comillas en paths con espacios)
        cmd_str = " ".join(
            f'"{x}"' if " " in x else x for x in cmd
        )

        self._log.log(f"🚀 Lanzando Slicer...")
        self._log.log(f"  $ {cmd_str[:200]}...", "info")
        if mod_id == 3:
            self._log.log("  - Carga de escena: ~2 min (64 MB)")
            self._log.log("  - Kernel FFT: ~30-50s")
            self._log.log("  - Slicer se cierra solo al terminar")
        self._status.setText(f"Ejecutando Mod{mod_id} en Slicer...")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # Indeterminate

        # Ruta al pipeline.log para monitorear progreso
        _RESULTADOS_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "resultados_test"
        )
        _PIPELINE_LOG = os.path.join(_RESULTADOS_DIR, "logs", "pipeline.log")

        # Capturar stderr para diagnóstico
        _stderr_lines = []

        # Ejecutar en hilo para no bloquear UI
        def run(cmd_list=cmd, pipeline_log=_PIPELINE_LOG, stderr_lines=_stderr_lines):
            try:
                proc = subprocess.Popen(
                    cmd_list,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                # Monitorear pipeline.log en tiempo real + stderr
                last_size = 0
                validation_detected = False
                if os.path.exists(pipeline_log):
                    last_size = os.path.getsize(pipeline_log)
                while proc.poll() is None:
                    # Leer stderr en vivo
                    err_line = proc.stderr.readline() if proc.stderr else ""
                    if err_line:
                        stderr_lines.append(err_line.rstrip())
                    # Leer pipeline.log
                    if os.path.exists(pipeline_log):
                        curr_size = os.path.getsize(pipeline_log)
                        if curr_size > last_size:
                            with open(pipeline_log, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(last_size)
                                for line in f:
                                    if line.strip():
                                        QTimer.singleShot(0, lambda l=line: self._log.log(l.strip()[:250]))
                                        if ("VALIDACION MEDICA" in line or "validacion medica" in line.lower()) and not validation_detected:
                                            validation_detected = True
                                            QTimer.singleShot(100, lambda: _activate_slicer_window())
                                            QTimer.singleShot(300, lambda: _activate_slicer_window())
                            last_size = curr_size
                    time.sleep(0.5)
                # Leer stderr restante
                if proc.stderr:
                    for line in proc.stderr:
                        line = line.rstrip()
                        if line:
                            stderr_lines.append(line)
                return_code = proc.returncode

                # Leer resto del log (usando TIMER para no tocar UI desde thread)
                if os.path.exists(pipeline_log):
                    with open(pipeline_log, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_size)
                        for line in f:
                            if line.strip():
                                QTimer.singleShot(0, lambda l=line: self._log.log(l.strip()[:250]))

                # Si fallo y hay stderr, mostrarlo (tambien via timer)
                if return_code != 0 and stderr_lines:
                    for l in stderr_lines[-20:]:
                        QTimer.singleShot(0, lambda ll=l: self._log.log(f"  {ll}", "error"))

                _trace(f"_launch_slicer: Slicer termino (rc={return_code})")
                # Usar señal Qt en vez de QTimer.singleShot (mas robusta entre threads)
                self.slicer_done.finished.emit(mod_id, return_code)
            except Exception as e:
                _trace(f"_launch_slicer: EXCEPCION en thread: {e}")
                QTimer.singleShot(0, lambda: self._log.log(f"Error lanzando Slicer: {e}", "error"))
                QTimer.singleShot(0, lambda: self._progress.setVisible(False))

        _trace(f"_launch_slicer({mod_id}) — iniciando thread")
        threading.Thread(target=run, daemon=True).start()
        _trace(f"_launch_slicer({mod_id}) — thread iniciado, retornando")

    def _on_slicer_done(self, mod_id: int, return_code: int):
        """Callback cuando Slicer termina."""
        _trace(f"_on_slicer_done(mod={mod_id}, rc={return_code})")
        self._progress.setVisible(False)
        if return_code == 0:
            self._log.log(f"✅ Mod{mod_id} completado exitosamente", "ok")
            self._status.setText("Pipeline completado.")
            QTimer.singleShot(200, lambda:
                QMessageBox.information(self, "Completado",
                    f"Modulo {mod_id} finalizado correctamente."))
        else:
            self._log.log(f"❌ Mod{mod_id} termino con codigo {return_code}", "error")
            self._status.setText("Pipeline finalizo con errores.")
            QTimer.singleShot(200, lambda:
                QMessageBox.warning(self, "Finalizado",
                    f"Modulo {mod_id} termino con codigo {return_code}.\n"
                    f"Revise el log para mas detalles."))

    # ────────────────────────────────────────────────────────────
    # CONFIG OVERRIDE
    # ────────────────────────────────────────────────────────────

    def _apply_config_override(self, mod_id: int, config: dict):
        """Escribe la config del usuario en config.jsonc antes de lanzar Slicer."""
        try:
            cfg = _load_config()
            if not cfg:
                return

            if mod_id == 1:
                # Paths
                paths_cfg = cfg.setdefault("paths", {})
                if "patient_id" in config and config["patient_id"]:
                    paths_cfg["patient_id"] = config["patient_id"]
                if "ct_dir" in config:
                    paths_cfg["ct_dir"] = config["ct_dir"]
                if "pet_dir" in config:
                    paths_cfg["pet_dir"] = config["pet_dir"]
                # Tumor
                tc = cfg.setdefault("tumor", {})
                if "tumor_mode" in config:
                    tc["mode"] = config["tumor_mode"]
                if "tumor_radius" in config:
                    tc["synthetic_radius_mm"] = config["tumor_radius"]
                if "tumor_file" in config:
                    tc["load_file_path"] = config["tumor_file"]
                # TotalSegmentator
                seg = cfg.setdefault("segmentation", {})
                ts = seg.setdefault("totalsegmentator", {})
                if "ts_fast" in config:
                    ts["fast"] = config["ts_fast"]
                if "ts_force_cpu" in config:
                    ts["force_cpu"] = config["ts_force_cpu"]
                # Resample
                resample = cfg.setdefault("resample", {})
                if "resample_interp" in config:
                    resample["interpolation"] = config["resample_interp"]

            elif mod_id == 2:
                if "isotope" in config:
                    cfg.setdefault("mcnp_source", {})["isotope"] = config["isotope"]
                if "n_particles" in config:
                    cfg.setdefault("mcnp_run", {})["n_particles"] = config["n_particles"]
                if "flip_y" in config:
                    cfg.setdefault("geometry", {})["flip_y"] = config["flip_y"]
                if "flip_z" in config:
                    cfg.setdefault("geometry", {})["flip_z"] = config["flip_z"]
                if "refine_hu" in config:
                    cfg.setdefault("mcnp_run", {})["refine_hu"] = config["refine_hu"]

            _save_config(cfg)
            self._log.log("Config actualizada para la ejecucion", "ok")

        except Exception as e:
            self._log.log(f"Error actualizando config: {e}", "warn")


# ======================================================================
# MAIN GUARD
# ======================================================================

if __name__ == "__main__":
    # Hook para atrapar excepciones silenciosas (evita cierre inesperado)
    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(os.path.join(os.path.dirname(__file__), "error.log"), "a") as f:
                f.write(f"UNHANDLED EXCEPTION:\n{msg}\n")
        except Exception:
            pass
        # Mostrar tambien en consola
        print(f"UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_value}", file=sys.stderr)
    sys.excepthook = _excepthook

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Evita cierre si algo raro pasa

    w = LauncherWindow()
    w.show()
    sys.exit(app.exec_())
