"""
Prompt de commit git al finalizar el pipeline exitosamente.

Busca el repositorio git, pregunta al usuario si quiere commitear,
ejecuta git add -A y git commit -m "mensaje".
"""

import logging
import os
import subprocess

logger = logging.getLogger("3DosimTest")


def find_git_repo(start_path: str = None) -> "str | None":
    """
    Busca el directorio raiz del repositorio git desde start_path hacia arriba.

    Args:
        start_path: Directorio donde empezar la busqueda.
                    Por defecto usa el directorio del archivo actual.

    Returns:
        Ruta absoluta al repo, o None si no se encuentra.
    """
    if start_path is None:
        start_path = os.path.dirname(os.path.abspath(__file__))

    current = start_path
    for _ in range(10):  # Subir hasta 10 niveles
        if os.path.isdir(os.path.join(current, ".git")):
            return os.path.abspath(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def prompt_git_commit(data_dir: str = None):
    """
    Pregunta al usuario si quiere hacer un commit git.

    Args:
        data_dir: Nombre descriptivo del directorio de datos
                  (se usa como sugerencia para el mensaje de commit)
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info("  PIPELINE COMPLETADO EXITOSAMENTE")
    logger.info("=" * 70)
    logger.info("")

    # Buscar directorio raiz del repo
    repo_dir = find_git_repo()
    if not repo_dir:
        logger.info("  No se detecto repositorio git, saltando commit")
        return

    logger.info(f"  Repositorio detectado: {repo_dir}")
    logger.info("")

    # Preguntar si quiere commitear
    commit_msg = _ask_for_commit(data_dir)
    if commit_msg is None:
        logger.info("  Commit cancelado por el usuario")
        return

    # Ejecutar git commit
    try:
        logger.info("  Ejecutando git commit...")
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True,
                       capture_output=True, text=True)

        result = subprocess.run(
            ["git", "commit", "-m", commit_msg.strip()],
            cwd=repo_dir, capture_output=True, text=True
        )

        if result.returncode == 0:
            logger.info(f"  Commit exitoso: {result.stdout.strip()}")
        else:
            stderr = (result.stderr or "") + (result.stdout or "")
            if "nothing to commit" in stderr.lower():
                logger.info("  No hay cambios nuevos para commitear")
            else:
                logger.warning(f"  Error en commit: {stderr.strip()}")

    except subprocess.CalledProcessError as e:
        logger.warning(f"  Error en git add: {e.stderr}")
    except FileNotFoundError:
        logger.warning("  Git no encontrado en el sistema")
    except Exception as e:
        logger.warning(f"  Error inesperado en git: {e}")


def _ask_for_commit(data_dir: str = None) -> "str | None":
    """
    Pregunta al usuario si quiere hacer commit.
    Returns: Mensaje de commit, o None si cancelo.
    """
    suggested_msg = "3Dosim pipeline"
    if data_dir:
        suggested_msg += f" - {os.path.basename(data_dir)}"

    try:
        from qt import QInputDialog, QMessageBox, QApplication

        reply = QMessageBox.question(
            None,
            "3Dosim - Commit git",
            "El pipeline se completo correctamente.\n\n"
            "Desea hacer un commit git de los resultados y cambios?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return None

        msg, ok = QInputDialog.getText(
            None,
            "Mensaje de commit",
            "Describa los cambios realizados:",
            text=suggested_msg
        )
        if not ok or not msg.strip():
            return None
        return msg.strip()

    except ImportError:
        # Fallback a consola
        logger.info("  (Interfaz Qt no disponible, usando consola)")
        respuesta = input("  Hacer commit git? (si/no): ").strip().lower()
        if respuesta not in ("si", "s", "yes", "y"):
            return None
        msg = input("  Mensaje de commit: ").strip()
        if not msg:
            return None
        return msg.strip()
