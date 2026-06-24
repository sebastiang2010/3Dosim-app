"""
Anonimizacion de nodos en la escena de Slicer.

Sin archivos temporales ni pydicom: renombra los nodos directamente
en la escena de Slicer usando la API interna (slicer.mrmlScene).
Las series DICOM originales permanecen intactas en disco.
"""

import logging

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


def anonymize(ct_node, ct_dir: str = None, pet_dir: str = None, anon_dir: str = None, pet_node=None):
    """
    Anonimiza los nodos CT y PET ya cargados en la escena de Slicer
     renombrndolos. Sin copias de archivos ni pydicom.
    """
    show_progress("Anonimizando imagenes...")
    import slicer

    logger.info("  Anonimizando nodos en Slicer...")

    for node, label in [(ct_node, "CT"), (pet_node, "PET")]:
        if node is None:
            continue
        old_name = node.GetName()
        node.SetName(f"3Dosim_{label}_anon")
        logger.info(f"  {label}: '{old_name}' -> '{node.GetName()}'")

    logger.info("  Anonimizacion completada (nodos renombrados en escena)")
