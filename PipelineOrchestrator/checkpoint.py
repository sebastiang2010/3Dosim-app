"""
CheckpointManager - Estado persistente del pipeline.

Guarda el progreso en un archivo JSON despues de cada paso exitoso.
Si el programa se corta, al reiniciar retoma desde el ultimo checkpoint.
"""

import json
import os
import logging

logger = logging.getLogger("3DosimTest")


class CheckpointManager:
    """
    Gestiona checkpoints del pipeline.

    Uso:
        cp = CheckpointManager("./.checkpoints")
        if not cp.is_completed("load_dicom"):
            cargar_dicom()
            cp.mark_completed("load_dicom", {"path": "/data/ct"})

    Args:
        checkpoint_dir: Directorio donde se guarda el archivo JSON
    """

    CHECKPOINT_VERSION = 1

    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_file = os.path.join(checkpoint_dir, "pipeline_checkpoint.json")
        self.state = self._load()

    def _load(self) -> dict:
        """Carga el estado desde el archivo JSON."""
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r") as f:
                    state = json.load(f)
                if state.get("version") == self.CHECKPOINT_VERSION:
                    return state
                else:
                    logger.warning(
                        "Version de checkpoint incompatible, reiniciando"
                    )
            except (json.JSONDecodeError, KeyError):
                pass
        return {"version": self.CHECKPOINT_VERSION, "completed": [], "data": {}}

    def is_completed(self, step_name: str) -> bool:
        """Verifica si un paso ya fue completado."""
        return step_name in self.state["completed"]

    def mark_completed(self, step_name: str, data: dict = None):
        """Marca un paso como completado y guarda el checkpoint."""
        if step_name not in self.state["completed"]:
            self.state["completed"].append(step_name)
        if data:
            self.state["data"][step_name] = data
        self._save()
        logger.info(f"  Checkpoint guardado: {step_name}")

    def get_data(self, step_name: str) -> dict:
        """Recupera datos guardados de un paso previo."""
        return self.state["data"].get(step_name, {})

    def _save(self):
        """Persiste el estado a JSON."""
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        with open(self.checkpoint_file, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def reset(self):
        """Elimina todos los checkpoints (empieza de cero)."""
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
        self.state = {"version": self.CHECKPOINT_VERSION, "completed": [], "data": {}}
        logger.info("  Checkpoints reiniciados")

    @property
    def completed_steps(self) -> list:
        """Lista de nombres de pasos completados."""
        return list(self.state["completed"])
