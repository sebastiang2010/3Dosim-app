"""
Segmentacion con TotalSegmentator (via TotalSegmentatorLogic.process()).

Solo modo "totalsegmentator" disponible.
El modo simple fue eliminado porque no es util para dosimetria.
"""

import logging
import time

logger = logging.getLogger("3DosimTest")


def check_totalsegmentator() -> bool:
    """Verifica si TotalSegmentator esta instalado como modulo de Slicer."""
    import slicer
    try:
        has_module = hasattr(slicer.modules, 'totalsegmentator')
        if has_module:
            logger.info("  TotalSegmentator (modulo de Slicer) detectado")
        else:
            logger.info("  TotalSegmentator NO disponible como modulo de Slicer")
        return has_module
    except Exception:
        logger.info("  TotalSegmentator NO disponible")
        return False


def load_ts_config(config_path=None) -> dict:
    """
    Carga la configuracion de TotalSegmentator desde un archivo JSONC.

    Args:
        config_path: Ruta al .jsonc. Si es None, busca en el directorio del script.

    Returns:
        dict con parametros: task, fast, force_cpu, subset, ...
    """
    import json
    import os
    import re

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "totalsegmentator_config.jsonc"
        )

    defaults = {
        "task": "total",
        "fast": True,
        "force_cpu": True,
        "subset": None,
        "interactive": False,
        "use_standard_segment_names": True,
    }

    if not os.path.exists(config_path):
        logger.info(f"  Config JSONC no encontrado: {config_path}")
        logger.info(f"  Usando valores por defecto: {defaults}")
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'//.*', '', content)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        config = json.loads(content)
        defaults.update(config)
        logger.info(f"  Config cargada desde: {config_path}")
        for k, v in defaults.items():
            logger.info(f"    {k}: {v}")
    except Exception as e:
        logger.warning(f"  Error cargando config JSONC: {e}")
        logger.info(f"  Usando valores por defecto: {defaults}")

    return defaults


def run_segmentation(ct_node, output_dir: str, force_cpu: bool = True):
    """
    Ejecuta TotalSegmentator via TotalSegmentatorLogic.process().

    Args:
        ct_node: Nombre del nodo CT en la escena de Slicer (ej: "3Dosim_CT_anon")
        output_dir: Directorio de salida
        force_cpu: True fuerza CPU, False permite GPU si disponible

    Returns:
        segmentation_node: vtkMRMLSegmentationNode con segmentacion completa
    """
    import slicer

    if not check_totalsegmentator():
        raise RuntimeError(
            "TotalSegmentator no esta instalado como modulo de Slicer.\n"
            "Instalelo desde Extension Manager y reinicie Slicer."
        )

    # Si es string (nombre de nodo), resolver a nodo
    ct_name = ct_node if isinstance(ct_node, str) else ct_node.GetName()
    return _run_totalsegmentator(ct_name, output_dir, force_cpu=force_cpu)


def _run_totalsegmentator(ct_node_name: str, output_dir: str, force_cpu: bool = True):
    """
    Ejecuta TotalSegmentator via TotalSegmentatorLogic.process().

    Args:
        ct_node_name: Nombre del volumen CT en la escena de Slicer
        output_dir: Directorio de salida
        force_cpu: True fuerza CPU
    """
    import slicer

    logger.info("")
    logger.info("  ========================================================")
    logger.info("  TotalSegmentator via TotalSegmentatorLogic.process()")
    logger.info("  ========================================================")
    logger.info("")

    t_start = time.time()

    config = load_ts_config()
    task = config.get("task", "total")
    fast = config.get("fast", True)
    cpu = config.get("force_cpu", force_cpu)
    subset = config.get("subset", None)
    interactive = config.get("interactive", False)

    # Buscar el volumen CT por su nombre en la escena de Slicer
    ct_node = slicer.util.getNode(ct_node_name)
    if ct_node is None:
        raise RuntimeError(f"No se encontro volumen '{ct_node_name}' en la escena")
    logger.info(f"  Volumen CT encontrado: '{ct_node.GetName()}'")

    # Cambiar al modulo TotalSegmentator para que el usuario vea el progreso
    try:
        slicer.util.selectModule("TotalSegmentator")
        slicer.app.processEvents()
        logger.info("  Cambiado al modulo TotalSegmentator")
    except Exception:
        pass

    # Crear nodo de segmentacion de salida
    seg_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    seg_node.SetName("TotalSegmentator_Seg")
    seg_node.CreateDefaultDisplayNodes()

    try:
        from TotalSegmentator import TotalSegmentatorLogic

        logic = TotalSegmentatorLogic()
        logic.logCallback = lambda msg: logger.info(f"  [TS] {msg}")
        logic.clearOutputFolder = True
        logic.useStandardSegmentNames = config.get("use_standard_segment_names", True)

        device_str = "CPU" if cpu else "auto (GPU si disponible)"
        logger.info(f"  Device: {device_str}")
        logger.info(f"  Task: {task} (fast={fast})")
        if subset:
            logger.info(f"  Subset: {subset}")

        # Paso 1: asegurar que los paquetes Python de TS esten instalados
        logger.info("  Verificando/instalando dependencias Python de TotalSegmentator...")
        logic.setupPythonRequirements()
        logger.info("  Dependencias OK")

        # Paso 2: ejecutar segmentacion
        logger.info("  Ejecutando TotalSegmentator (Slicer no responde hasta terminar)...")
        logic.process(
            inputVolume=ct_node,
            outputSegmentation=seg_node,
            fast=fast,
            cpu=cpu,
            task=task,
            subset=subset,
            interactive=interactive,
        )
        logger.info("  TotalSegmentator completado")

    except Exception as e:
        logger.error(f"  TotalSegmentator FALLO: {e}")
        raise RuntimeError(f"TotalSegmentator fallo: {e}")

    elapsed = int(time.time() - t_start)
    logger.info(f"  TotalSegmentator completado en {elapsed}s")
    logger.info(f"  Nodo: {seg_node.GetName()}")

    return seg_node
