"""
Wrapper pragmatico para iniciar el servidor MONAI Label.

Intenta iniciar el servidor automaticamente. Si falla, muestra
instrucciones claras para hacerlo manualmente.

Flujo:
  1. Verifica si el servidor ya esta corriendo
  2. Si no, verifica que exista main.py en el app_dir
  3. Lanza el servidor en proceso separado
  4. Espera hasta timeout a que responda
  5. Fallback: instrucciones para inicio manual

Uso desde pipeline:
    from PipelineOrchestrator.monailabel_server import start_server
    proc = start_server(timeout=60)
"""

import argparse
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger("3DosimTest")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_RESULTS_DIR = os.path.join(_BASE_DIR, "resultados_test")

_APP_DIR = os.path.join(_RESULTS_DIR, ".monai_app")
_STUDIES_DIR = os.path.join(_RESULTS_DIR, ".monai_studies")
_SERVER_URL = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# Verificar servidor
# ---------------------------------------------------------------------------

def check_server(server_url: str = _SERVER_URL) -> bool:
    """Verifica si el servidor MONAI Label responde en server_url."""
    try:
        req = urllib.request.Request(f"{server_url}/info/")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _get_python_slicer() -> str:
    """Devuelve la ruta a PythonSlicer.exe."""
    candidates = [
        r"C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\bin\PythonSlicer.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return "PythonSlicer.exe"


def _ensure_app_directory(app_dir: str) -> bool:
    """
    Verifica que app_dir tenga main.py valido.
    Si no existe, crea un main.py funcional con DeepEdit.
    """
    main_py = os.path.join(app_dir, "main.py")
    if os.path.exists(main_py):
        return True

    # Crear estructura
    for subdir in ["model", "lib", "logs", "bin"]:
        os.makedirs(os.path.join(app_dir, subdir), exist_ok=True)

    # main.py con DeepEdit (placeholder que usa SegResNet si es posible)
    content = '''import os
import logging
from monailabel.interfaces.app import MONAILabelApp
from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.deepedit import DeepEdit
from monai.networks.nets import SegResNet

logger = logging.getLogger(__name__)

class MyApp(MONAILabelApp):
    """3Dosim MONAI Label app with DeepEdit support."""

    def __init__(self, app_dir, studies, conf):
        super().__init__(
            app_dir, studies, conf,
            name="3Dosim DeepEdit",
            description="Liver tumor segmentation with DeepEdit",
            labels=["tumor"],
        )

    def init_infers(self):
        # Intentar cargar un modelo preentrenado si existe en model/
        model_path = os.path.join(self.app_dir, "model", "pretrained.pt")
        
        # Si no existe, DeepEdit funcionara como un 'blank' segmenter 
        # que aprende de los clicks del usuario o usa pesos default si se bajan.
        infers = {
            "DeepEdit": DeepEdit(
                path=model_path if os.path.exists(model_path) else None,
                network=SegResNet(spatial_dims=3, in_channels=2, out_channels=1), # 1 label + clicks
                labels={"tumor": 1},
                type=InferType.DEEPEDIT,
            )
        }
        return infers
'''
    with open(main_py, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"  Creado main.py con DeepEdit en {main_py}")

    # __init__.py
    init_py = os.path.join(app_dir, "__init__.py")
    if not os.path.exists(init_py):
        with open(init_py, "w") as f:
            f.write("")

    return True


def _install_dependencies(python_exe: str):
    """Instala dependencias criticas si faltan."""
    deps = ["sortedcontainers", "pytorch-ignite", "expiring-dict"]
    logger.info("  Verificando dependencias criticas...")
    for dep in deps:
        try:
            subprocess.run(
                [python_exe, "-m", "pip", "install", dep],
                capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            logger.info(f"    ✓ {dep} OK")
        except Exception as e:
            logger.warning(f"    ✗ Error instalando {dep}: {e}")


# ---------------------------------------------------------------------------
# Inicio del servidor
# ---------------------------------------------------------------------------

def start_server(
    port: int = 8000,
    server_url: str = _SERVER_URL,
    timeout: int = 60,
) -> Optional[subprocess.Popen]:
    """
    Inicia el servidor MONAI Label si no esta corriendo ya.

    Returns:
        subprocess.Popen si se lanzo el servidor,
        None si ya estaba corriendo o si no se pudo iniciar
    """
    logger.info("")
    logger.info("  ========================================================")
    logger.info("  MONAI Label Server - Inicio automatico")
    logger.info("  ========================================================")
    logger.info("")

    # --- 1. Verificar si ya esta corriendo ---
    if check_server(server_url):
        logger.info(f"  MONAI Label server ya activo en {server_url}")
        logger.info("  ========================================================")
        return None

    logger.info(f"  Servidor NO detectado en {server_url}")
    logger.info(f"  Iniciando en puerto {port}...")

    # --- 2. Crear directorios ---
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    os.makedirs(_STUDIES_DIR, exist_ok=True)

    # --- 3. Encontrar PythonSlicer ---
    python_exe = _get_python_slicer()
    logger.info(f"  Usando: {python_exe}")

    if not os.path.exists(python_exe):
        logger.error(f"  PythonSlicer.exe no encontrado: {python_exe}")
        return None

    # --- 4. Instalar dependencias y preparar app ---
    _install_dependencies(python_exe)

    if not _ensure_app_directory(_APP_DIR):
        logger.error("  No se pudo preparar el directorio de la app")
        return None

    # --- 5. Comando ---
    cmd = [
        python_exe, "-m", "monailabel.main",
        "start_server",
        "--app", _APP_DIR,
        "--port", str(port),
        "--studies", _STUDIES_DIR,
    ]
    logger.info(f"  Comando: {' '.join(cmd)}")

    # --- 5. Lanzar proceso ---
    try:
        log_file = os.path.join(_RESULTS_DIR, "monailabel_server.log")
        log_fh = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info(f"  Proceso lanzado: PID {proc.pid}")
        logger.info(f"  Log: {log_file}")
    except Exception as e:
        logger.error(f"  Error lanzando servidor: {e}")
        return None

    # --- 6. Esperar que responda ---
    logger.info(f"  Esperando respuesta (timeout={timeout}s)...")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if check_server(server_url):
            elapsed = time.time() - t0
            logger.info(f"  Servidor listo en {elapsed:.1f}s!")
            logger.info(f"  URL: {server_url}")
            logger.info("  ========================================================")
            return proc
        time.sleep(1)

    # Timeout - el server puede haber fallado
    logger.warning(f"  Timeout tras {timeout}s - el servidor no responde")
    logger.warning(f"  Revise el log: {log_file}")
    logger.info("")
    logger.info("  Para iniciar manualmente:")
    logger.info(f"    {python_exe} -m monailabel.main start_server "
                f"--app {_APP_DIR} --port {port} --studies {_STUDIES_DIR}")
    logger.info("  ========================================================")

    return proc  # el proceso puede seguir corriendo


# ---------------------------------------------------------------------------
# MAIN (prueba directa)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="MONAI Label Server Wrapper")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    proc = start_server(port=args.port, timeout=args.timeout)
    if proc is None:
        if check_server():
            print("Ya hay un servidor corriendo.")
        else:
            print("No se pudo iniciar el servidor.")
    else:
        print(f"MONAI Label server PID: {proc.pid}")
        print("Presione Ctrl+C para detener.")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
