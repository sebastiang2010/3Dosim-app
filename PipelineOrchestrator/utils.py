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
                _progress_timers.pop(id(dialog), None)
                dialog.close()
                dialog.deleteLater()
                from qt import QApplication
                QApplication.processEvents()
            except Exception:
                pass
        mensaje = f"  {description} — {elapsed:.0f}s, completado."
        logger.info(mensaje)
        show_progress(mensaje)


# Timers de dialogo de progreso vivos, para evitar su recoleccion sin usar atributos
# arbitrarios (PythonQt no acepta dlg.<atributo> en QWidgets envueltos).
_progress_timers: dict = {}


def _show_progress_dialog(description: str):
    """Muestra QDialog no-modal con indicador de progreso mientras corre un proceso."""
    try:
        from qt import QDialog, QVBoxLayout, QLabel, QApplication, QProgressBar, QTimer
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

        # Timer para mantener la UI responsiva y animar la barra indeterminada
        timer = QTimer(dlg)
        timer.setInterval(50)
        timer.timeout.connect(lambda: QApplication.processEvents())
        timer.start()
        _progress_timers[id(dlg)] = timer  # Referencia para que no se recolecte

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


# ═══════════════════════════════════════════════════════════════
# Funciones compartidas de carteles (unificadas desde modulo 1)
# ═══════════════════════════════════════════════════════════════


def show_save_scene_dialog():
    """Muestra cartel no-modal 'Guardando escena...' mientras se guarda el .mrb.

    Patron unificado de modulo 1. Si Qt no esta disponible, retorna None
    y el pipeline continua sin cartel.

    Returns:
        QDialog o None si no se pudo crear.
    """
    try:
        from qt import QDialog, QVBoxLayout, QLabel, QApplication
        import slicer
        main_w = slicer.util.mainWindow()
        dialog = QDialog(main_w)
        dialog.setWindowTitle("3Dosim — Guardando escena")
        dialog.setModal(False)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        msg = QLabel(
            "<b>Guardando escena...</b><br>"
            "Puede tomar hasta 2 minutos si la escena es grande.<br>"
            "No cerrar Slicer."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
        layout.addWidget(msg)
        dialog.show()
        QApplication.processEvents()
        return dialog
    except Exception:
        return None  # Qt no disponible, seguir sin cartel


def close_save_scene_dialog(dialog):
    """Cierra el cartel 'Guardando escena...' si existe."""
    if dialog is not None:
        try:
            dialog.close()
            dialog.deleteLater()
            from qt import QApplication
            QApplication.processEvents()
        except Exception:
            pass


def show_popup(title: str, text: str, no_slicer: bool = False):
    """
    Muestra dialogo no-modal simple en Slicer.

    Args:
        title: Titulo de la ventana.
        text: Texto a mostrar (acepta HTML basico).
        no_slicer: Si True, retorna None sin mostrar (para modo headless).

    Returns:
        QDialog o None si Qt no está disponible.
    """
    if no_slicer:
        return None
    try:
        import slicer
        from qt import QDialog, QVBoxLayout, QLabel, Qt
        dlg = QDialog(slicer.util.mainWindow())
        dlg.setWindowTitle(title)
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint |
                           Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        dlg.setModal(False)
        layout = QVBoxLayout(dlg)
        msg = QLabel(text)
        msg.setWordWrap(True)
        # Estilo unificado con Modulo 1 (save_scene / labelmap)
        msg.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
        layout.addWidget(msg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        slicer.app.processEvents()
        return dlg
    except Exception:
        return None

def show_confirmation_dialog(title: str, question_html: str, instructions_html: str = "", yes_label: str = "APROBAR", no_label: str = "RECHAZAR") -> bool:
    """Muestra un cuadro de dialogo modal con botones de confirmación.

    Args:
        title: Título de la ventana.
        question_html: Pregunta o mensaje principal (HTML).
        instructions_html: Texto de instrucciones adicional (HTML).
        yes_label: Texto del botón de aprobación.
        no_label: Texto del botón de rechazo.

    Returns:
        True si el usuario aprueba, False si rechaza.
    """
    try:
        from qt import QLabel, QVBoxLayout, QDialog, QPushButton, QHBoxLayout, Qt
        import slicer
        app = slicer.app
        main = slicer.util.mainWindow()
        dialog = QDialog(main)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(450)
        dialog.setModal(False)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout()
        layout.setSpacing(12)
        # Pregunta
        pregunta_label = QLabel(f'<h3 style="color:#2c3e50; text-align:center;">{question_html}</h3>')
        pregunta_label.setAlignment(1)  # Qt.AlignCenter
        layout.addWidget(pregunta_label)
        # Instrucciones
        if instructions_html:
            instr_label = QLabel(f'<p style="color:#555; text-align:center; font-size:12px;">{instructions_html}</p>')
            instr_label.setAlignment(1)
            instr_label.setWordWrap(True)
            layout.addWidget(instr_label)
        # Botones
        btn_row = QHBoxLayout()
        btn_row.setSpacing(20)
        btn_yes = QPushButton(yes_label)
        btn_no = QPushButton(no_label)
        btn_yes.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; font-weight:bold;"
            "  padding:14px 20px; font-size:14px; border-radius:6px; min-width:140px; }"
            "QPushButton:hover { background:#2ecc71; }"
        )
        btn_no.setStyleSheet(
            "QPushButton { background:#c0392b; color:white; font-weight:bold;"
            "  padding:14px 20px; font-size:14px; border-radius:6px; min-width:140px; }"
            "QPushButton:hover { background:#e74c3c; }"
        )
        btn_row.addStretch()
        btn_row.addWidget(btn_yes)
        btn_row.addWidget(btn_no)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        dialog.setLayout(layout)
        resultado = [None]
        def on_yes():
            resultado[0] = True
            dialog.close()
        def on_no():
            resultado[0] = False
            dialog.close()
        def on_dialog_closed(exit_code):
            if resultado[0] is None:
                resultado[0] = False
        btn_yes.clicked.connect(on_yes)
        btn_no.clicked.connect(on_no)
        dialog.finished.connect(on_dialog_closed)
        # Centrar
        dialog.adjustSize()
        main_rect = main.geometry
        dlg_rect = dialog.geometry
        dialog.move(
            main_rect.x() + (main_rect.width() - dlg_rect.width()) // 2,
            main_rect.y() + (main_rect.height() - dlg_rect.height()) // 2,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        # Event loop
        while resultado[0] is None:
            app.processEvents()
        return resultado[0]
    except Exception:
        # Fallback to console
        respuesta = input(f"{title} - {question_html} (si/no): ").strip().lower()
        return respuesta in ("si", "s", "yes", "y")


def _shade_hex(color: str, factor: float = 0.85):
    """Oscurece un color hex (#rrggbb) multiplicando cada canal por factor."""
    color = color.lstrip("#")
    if len(color) != 6:
        return color
    try:
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return color


def show_summary_dialog(title: str, body_html: str, button_label: str = "Cerrar",
                        accent_color: str = "#2ecc71", modal: bool = True,
                        width: int = 500):
    """Muestra un QDialog informativo estilizado (patron Modulo 1).

    Replica exactamente el aspecto de _show_labelmap_dialog de Modulo 1:
    titulo verde <b style='font-size:16px; color:#2ecc71;'> en el cuerpo,
    info en color #2c3e50 con padding 15px, y boton redondeado #2ecc71
    con hover #27ae60.

    Args:
        title: Titulo de la ventana.
        body_html: Cuerpo del dialogo (acepta HTML: <b>, <br>, <code>, ...).
        button_label: Texto del boton de cierre.
        accent_color: Color del boton (hex, ej. #2ecc71). Para el verde por
            defecto el hover es #27ae60 (igual que Mod1); otros colores se
            oscurecen un 15%.
        modal: True bloquea el pipeline (exec_); False lo muestra no-modal.
        width: Ancho minimo del dialogo.

    Returns:
        QDialog o None si Qt no esta disponible.
    """
    try:
        from qt import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, Qt, QApplication
        import slicer
        dlg = QDialog(slicer.util.mainWindow())
        dlg.setWindowTitle(title)
        dlg.setModal(modal)
        dlg.setMinimumWidth(width)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(dlg)
        info = QLabel(body_html)
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
        layout.addWidget(info)
        close_btn = QPushButton(button_label)
        hover_color = "#27ae60" if accent_color.lower() == "#2ecc71" else _shade_hex(accent_color)
        close_btn.setStyleSheet(
            "QPushButton {"
            f"  background-color: {accent_color}; color: white;"
            "  border: none; border-radius: 8px;"
            "  padding: 10px 24px; font-size: 14px; font-weight: bold;"
            "}"
            f"QPushButton:hover {{ background-color: {hover_color}; }}"
        )
        close_btn.clicked.connect(lambda: dlg.accept())
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        if modal:
            dlg.exec_()
        else:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            QApplication.processEvents()
        return dlg
    except Exception:
        return None


def close_popup(dlg):
    """Cierra dialogo no-modal creado con show_popup()."""
    if dlg is not None:
        try:
            dlg.close()
            dlg.deleteLater()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════


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
