"""
Utilidades compartidas del PipelineOrchestrator.
Logger, paths, helpers sin dependencias de Slicer.
"""

import logging
import os
import sys
import time
from contextlib import contextmanager


def setup_logger(name: str = "3DosimTest") -> logging.Logger:
    """Configura y retorna el logger global."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # NO propagar al root logger (evita duplicacion con logging_setup.py)
    logger.propagate = False

    # Consola: solo el mensaje, sin timestamp (el Tee de logging_setup.py
    # ya captura stdout con timestamp global)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(message)s"
    ))
    logger.addHandler(handler)

    # Archivo (si se puede determinar la ruta)
    try:
        # Intentar guardar en resultados_test/logs/
        # Buscamos la raiz del proyecto
        current = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.abspath(os.path.join(current, "..", "..", "..", ".."))
        log_dir = os.path.join(base_dir, "resultados_test", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "pipeline.log")
        
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s"
        ))
        logger.addHandler(file_handler)
        logger.info(f"Log file initialized: {log_file}")
    except Exception as e:
        print(f"No se pudo crear file handler para el logger: {e}")

    return logger


logger = setup_logger()


def add_module_path(script_path: str = None) -> bool:
    """
    Agrega el directorio Scripted/ a sys.path para importar SlicerDosimLib.

    Busca desde el directorio del script hacia arriba hasta encontrar
    la estructura Modules/Scripted/SlicerDosim/SlicerDosimLib/

    Returns: True si se pudo agregar el path
    """
    if script_path is None:
        script_path = os.path.abspath(__file__)

    # Buscar la raiz de SlicerDosim (donde esta Modules/)
    current = os.path.dirname(script_path)  # Testing/PipelineOrchestrator/
    for _ in range(6):  # Subir hasta 6 niveles
        candidate = os.path.join(current, "Modules", "Scripted")
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
            logger.info(f"  Path agregado: {candidate}")
            return True
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Fallback: buscar script_path desde el test original
    # .../Testing/Python/test_pipeline_orchestrator.py
    # ../.. = SlicerDosim/ ; +Modules/Scripted = target
    alt = os.path.normpath(os.path.join(
        os.path.dirname(script_path), "..", "..", "Modules", "Scripted"
    ))
    if os.path.isdir(alt) and alt not in sys.path:
        sys.path.insert(0, alt)
        logger.info(f"  Path agregado (fallback): {alt}")
        return True

    logger.warning("  ⚠ No se pudo agregar path de SlicerDosimLib")
    return False


def show_progress(message: str):
    """
    Muestra mensaje en la status bar de Slicer (si estamos dentro).
    """
    try:
        import slicer
        slicer.util.showStatusMessage(message, 5000)
        slicer.app.processEvents()
    except ImportError:
        pass  # Fuera de Slicer, silencioso


@contextmanager
def track_time(description: str, timeout: int = 5):
    """Context manager para procesos que pueden demorar.

    Muestra un cartel QDialog con barra de progreso INMEDIATAMENTE al inicio.
    El cartel se cierra automaticamente al terminar.

    Args:
        description: Descripcion del proceso (ej. 'Generando labelmap')
        timeout: (ignorado, mantenido por compatibilidad)

    Uso:
        with track_time("Generando labelmap dosimetrica"):
            # proceso largo
            time.sleep(10)
    """
    t0 = time.time()
    logger.info(f"  Iniciando: {description}...")
    show_progress(f"Iniciando: {description}")
    dialog = None

    # Mostrar cartel INMEDIATAMENTE
    try:
        dialog = _show_progress_dialog(description)
    except Exception:
        pass

    try:
        yield
    finally:
        elapsed = time.time() - t0
        # Cerrar dialog si se abrio
        if dialog is not None:
            try:
                dialog.close()
                dialog.deleteLater()
                from qt import QApplication
                QApplication.processEvents()
            except Exception:
                pass
        mensaje = f"  {description} — {elapsed:.0f}s, completado."
        logger.info(mensaje)
        show_progress(mensaje)


def _show_progress_dialog(description: str):
    """Muestra QDialog no-modal con indicador de progreso mientras corre un proceso."""
    try:
        from qt import QDialog, QVBoxLayout, QLabel, QApplication, QProgressBar
        import slicer
        main_w = slicer.util.mainWindow()
        dlg = QDialog(main_w)
        dlg.setWindowTitle("3Dosim — Procesando...")
        dlg.setModal(False)
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        msg = QLabel(
            f"<b>{description}</b><br><br>"
            f"Por favor espere..."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
        layout.addWidget(msg)
        progress = QProgressBar()
        progress.setRange(0, 0)  # Indeterminado
        progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 8px;
                text-align: center;
                height: 22px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 7px;
            }
        """)
        layout.addWidget(progress)
        dlg.show()
        QApplication.processEvents()
        return dlg
    except Exception:
        return None


def _show_dialog(description: str, mensaje: str = ""):
    """Muestra QDialog no-modal con mensaje de proceso completado."""
    try:
        from qt import QDialog, QVBoxLayout, QLabel, QApplication
        import slicer
        main_w = slicer.util.mainWindow()
        dlg = QDialog(main_w)
        dlg.setWindowTitle("3Dosim — Proceso completado")
        dlg.setModal(False)
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        msg = QLabel(
            f"<b>{description}</b><br><br>"
            f"{mensaje}<br>"
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
        layout.addWidget(msg)
        dlg.show()
        QApplication.processEvents()
        return dlg
    except Exception:
        return None


def kill_existing_slicer():
    """
    Cierra otras instancias de 3D Slicer abiertas (excepto la actual).

    Usa PowerShell para listar y matar procesos 'Slicer' (mas confiable que tasklist).
    Se ejecuta al inicio del pipeline para evitar conflictos
    con instancias previas de Slicer que puedan estar usando
    archivos temporales o recursos compartidos.
    """
    import subprocess
    import os
    import time

    try:
        current_pid = os.getpid()
    except AttributeError:
        logger.warning("  No se pudo obtener PID actual, saltando cierre de Slicer")
        return

    logger.info("")
    logger.info("  Buscando otras instancias de Slicer...")

    try:
        # Usar PowerShell: busca procesos 'Slicer' que no sean el actual
        ps_find = (
            f"$cur={current_pid}; "
            "Get-Process -Name 'SlicerApp-real','PythonSlicer' -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Id -ne $cur } | "
            "ForEach-Object { $_.Id.ToString() }"
        )
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_find],
            capture_output=True, text=True, timeout=15
        )

        pids = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                try:
                    pids.append(int(line))
                except ValueError:
                    continue

        if not pids:
            logger.info("  Ninguna otra instancia de Slicer encontrada")
            return

        killed = 0
        for pid in pids:
            if pid == current_pid:
                continue
            logger.info(f"  Cerrando Slicer PID {pid}...")
            kill_result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue'],
                capture_output=True, timeout=10
            )
            if kill_result.returncode == 0:
                killed += 1
                logger.info(f"    PID {pid} cerrado")
            else:
                logger.warning(f"    No se pudo cerrar PID {pid}")

        if killed > 0:
            logger.info(f"  {killed} instancias de Slicer cerradas")
        else:
            logger.info("  Ninguna otra instancia de Slicer encontrada")

        # Dar tiempo a que los procesos terminen
        if killed > 0:
            time.sleep(2)

    except FileNotFoundError:
        logger.warning("  PowerShell no disponible")
    except subprocess.TimeoutExpired:
        logger.warning("  Timeout buscando procesos Slicer")
    except Exception as e:
        logger.debug(f"  Error cerrando Slicer existente: {e}")
