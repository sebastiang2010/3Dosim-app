"""
Validacion medica de la segmentacion tumoral (PET).

Muestra un dialogo Qt NO MODAL que permite al medico navegar Slicer
libremente mientras revisa la segmentacion tumoral superpuesta al PET.
Solo cuando hace clic en APROBAR o RECHAZAR se continua.
"""

import logging

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


def validate_tumor_segmentation(context="sintetico"):
    """
    VALIDACION MEDICA OBLIGATORIA de la segmentacion tumoral.

    Dialogo NO modal: el medico puede usar 3D Slicer para navegar
    las imagenes, examinar el tumor en 3D, ajustar ventana PET, etc.
    Solo cuando hace clic en APROBAR o RECHAZAR se continua.

    Args:
        context: "sintetico" (default) para tumor generado automaticamente,
                 otro valor para tumor segmentado manualmente.

    Raises:
        RuntimeError: Si el medico rechaza la segmentacion tumoral
    """
    logger.info("")
    logger.info("  ╔════════════════════════════════════════════════════╗")
    logger.info("  ║   VALIDACION MEDICA — TUMOR                       ║")
    logger.info("  ║                                                  ║")
    logger.info("  ║   Un medico debe revisar la segmentacion         ║")
    logger.info("  ║   tumoral antes de continuar con los             ║")
    logger.info("  ║   calculos dosimetricos.                         ║")
    logger.info("  ╚════════════════════════════════════════════════════╝")
    logger.info("")

    show_progress("VALIDACION TUMOR PENDIENTE")

    approved = _show_tumor_validation_dialog(context=context)

    if approved:
        logger.info("")
        logger.info("  ╔════════════════════════════════════════════════════╗")
        logger.info("  ║   TUMOR APROBADO POR MEDICO                       ║")
        logger.info("  ║   Continuando con el pipeline...                  ║")
        logger.info("  ╚════════════════════════════════════════════════════╝")
        logger.info("")
        show_progress("Tumor aprobado - continuando")
        return True
    else:
        logger.info("")
        logger.info("  ╔════════════════════════════════════════════════════╗")
        logger.info("  ║   TUMOR RECHAZADO                                 ║")
        logger.info("  ║   Pipeline detenido.                              ║")
        logger.info("  ║   Corrija la segmentacion tumoral y reinicie.     ║")
        logger.info("  ╚════════════════════════════════════════════════════╝")
        logger.info("")
        raise RuntimeError(
            "Segmentacion tumoral rechazada por el medico. "
            "Corrija la segmentacion y ejecute con --reset para reiniciar."
        )


def _show_tumor_validation_dialog(context="sintetico") -> bool:
    """Muestra un dialogo de confirmación para la segmentación tumoral.

    Utiliza la función genérica `show_confirmation_dialog` para mantener
    consistencia visual y de comportamiento entre los módulos.
    """
    from PipelineOrchestrator.utils import show_confirmation_dialog
    # Determinar pregunta e instrucciones según contexto
    if "sintetico" in (context or "").lower():
        question = "&iquest;La segmentación tumoral es correcta?"
        instructions = (
            "Tumor SINTÉTICO generado automáticamente:<br>"
            "✓ Esfera de 1 cm radio en el parénquima hepático.<br>"
            "✓ Segmento rojo \"Tumor_Sintetico\".<br>"
            "✓ Segmento verde \"higado_sano\" (hígado - tumor).<br><br>"
            "<b>Revise la ubicación del tumor:</b><br>"
            "1. Navegue slices axial/sagital/coronal.<br>"
            "2. Use la vista 3D para inspeccionar el tumor esférico.<br>"
            "3. Verifique que el tumor esté DENTRO del hígado.<br>"
            "4. Confirme que el tamaño (~4.2 cm³) sea razonable.<br>"
        )
    elif "load_file" in (context or "").lower() or "cargado" in (context or "").lower() or "archivo" in (context or "").lower():
        question = "&iquest;La segmentación tumoral es correcta?"
        instructions = (
            "Tumor CARGADO desde archivo NIfTI:<br>"
            "✓ Segmento presente en la segmentación.<br>"
            "✓ Segmento verde \"higado_sano\" (hígado - tumor).<br><br>"
            "<b>Revise la segmentación tumoral:</b><br>"
            "1. Navegue slices axial/sagital/coronal.<br>"
            "2. Use la vista 3D para inspeccionar el tumor.<br>"
            "3. Verifique que el tumor corresponda al PET/CT.<br>"
            "4. Confirme que la ubicación sea correcta.<br>"
        )
    elif "manual" in (context or "").lower():
        question = "&iquest;La segmentación tumoral es correcta?"
        instructions = (
            "Tumor segmentado MANUALMENTE en Slicer:<br>"
            "✓ Segmento \"Tumor_Manual\" en la segmentación.<br>"
            "✓ Segmento verde \"higado_sano\" (hígado - tumor).<br><br>"
            "<b>Verifique su propia segmentación:</b><br>"
            "1. Navegue slices axial/sagital/coronal.<br>"
            "2. Use la vista 3D para inspeccionar el resultado.<br>"
            "3. Confirme que el volumen segmentado es correcto.<br>"
        )
    else:
        question = "&iquest;La segmentación tumoral es correcta?"
        instructions = (
            "Revise la segmentación tumoral:<br>"
            "Navegue slices axial/sagital/coronal.<br>"
            "Use la vista 3D para inspeccionar el tumor.<br>"
        )
    return show_confirmation_dialog("3Dosim — Validar Tumor", question, instructions)
