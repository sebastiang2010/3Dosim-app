"""
logging_setup.py - Logging global para 3Dosim pipeline en Slicer.

Captura TODO:
  - Mensajes de logging (info/warning/error) de TODOS los modulos
  - stdout/stderr (print, tracebacks de excepciones no capturadas)

Se escribe a:
  C:\\MAT\\3Dosim\\ai-pipe\\exports\\3Dosim-pipeline_YYYYMMDD_HHMMSS.log

Llamar al inicio de main.py (antes que cualquier otro import del pipeline).
"""

import logging
import os
import sys
import time
from typing import TextIO


_LOG_DIR = r"C:\MAT\3Dosim\ai-pipe\exports"
_LOG_PREFIX = "3Dosim-pipeline"


# ── Tee: duplica stdout/stderr a consola + archivo ──────────────────────

class _Tee:
    """Duplica escrituras: a stream original + a archivo de log."""

    def __init__(self, original_stream: TextIO, log_file) -> None:
        self.original = original_stream
        self._log_file = log_file

    def write(self, data: str) -> None:
        if self.original:
            try:
                self.original.write(data)
                self.original.flush()
            except Exception:
                pass
        if self._log_file:
            try:
                self._log_file.write(data)
                self._log_file.flush()
            except Exception:
                pass

    def flush(self) -> None:
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass
        if self._log_file:
            try:
                self._log_file.flush()
            except Exception:
                pass


# ── Setup principal ─────────────────────────────────────────────────────

def setup_global_logging() -> str:
    """Configura logging global.

    Crea FileHandler en el root logger + Tee de stdout/stderr.
    Retorna la ruta absoluta al archivo de log.
    """
    os.makedirs(_LOG_DIR, exist_ok=True)

    # Nombre con timestamp
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    # Abrir archivo en modo append con utf-8
    try:
        log_file = open(log_path, "w", encoding="utf-8")
    except Exception as e:
        # Fallback: escribir a donde se pueda
        fallback = os.path.join(os.path.dirname(__file__), "..", "pipeline_crash.log")
        log_file = open(fallback, "w", encoding="utf-8")
        log_path = fallback

    # 1. FileHandler en el ROOT logger → captura logging de TODOS los modulos
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    # Evitar duplicados si ya hay handlers
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        root_logger.addHandler(fh)

    # 2. Tee stdout → archivo (captura prints)
    sys.stdout = _Tee(sys.stdout, log_file)

    # 3. Tee stderr → archivo (captura tracebacks, errores)
    sys.stderr = _Tee(sys.stderr, log_file)

    # Escribir encabezado
    log_file.write(f"\n")
    log_file.write(f"{'='*80}\n")
    log_file.write(f" 3Dosim Pipeline - Log iniciado: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f" Python: {sys.version}\n")
    log_file.write(f" Archivo: {log_path}\n")
    log_file.write(f"{'='*80}\n")
    log_file.write(f"\n")
    log_file.flush()

    print(f"[3Dosim] Log global: {log_path}")
    return log_path
