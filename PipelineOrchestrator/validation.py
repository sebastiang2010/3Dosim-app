"""
Validacion medica obligatoria de la segmentacion.

Muestra un dialogo Qt NO MODAL que permite al medico navegar Slicer
libremente (mover slices, ocultar PET, rotar 3D) mientras revisa.
Solo cuando hace clic en APROBAR o RECHAZAR se continua.
"""

import logging

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


def validate_segmentation(context="segmentacion"):
    """
    VALIDACION MEDICA OBLIGATORIA.

    Dialogo NO modal: el medico puede usar 3D Slicer para navegar
    las imagenes, ocultar PET, examinar la segmentacion en 3D, etc.
    Solo cuando hace clic en APROBAR o RECHAZAR se continua.

    Args:
        context: "fusion" o "segmentacion" — cambia el mensaje del dialogo.

    Raises:
        RuntimeError: Si el medico rechaza
    """
    if context == "fusion":
        titulo = "Fusion CT+PET"
        msg = (
            "Un medico debe revisar la fusion CT+PET registrada\n"
            "antes de continuar con la segmentacion y calculos\n"
            "dosimetricos."
        )
        aprobado_msg = "FUSION APROBADA POR MEDICO"
        rechazado_msg = "FUSION RECHAZADA"
    else:
        titulo = "Segmentacion"
        msg = (
            "Un medico debe revisar la segmentacion\n"
            "antes de continuar con los calculos\n"
            "dosimetricos."
        )
        aprobado_msg = "SEGMENTACION APROBADA POR MEDICO"
        rechazado_msg = "SEGMENTACION RECHAZADA"

    logger.info("")
    logger.info("  ╔════════════════════════════════════════════════════╗")
    logger.info(f"  ║   VALIDACION MEDICA: {titulo:<24} ║")
    logger.info("  ║                                                  ║")
    logger.info(f"  ║   {msg:<49}║")
    logger.info("  ╚════════════════════════════════════════════════════╝")
    logger.info("")

    show_progress(f"VALIDACION MEDICA PENDIENTE: {titulo}")

    approved = _show_validation_dialog(titulo=titulo, context=context)

    if approved:
        logger.info("")
        logger.info("  ╔════════════════════════════════════════════════════╗")
        logger.info(f"  ║   {aprobado_msg:<43} ║")
        logger.info("  ║   Continuando con el pipeline...                  ║")
        logger.info("  ╚════════════════════════════════════════════════════╝")
        logger.info("")
        show_progress(f"{titulo} aprobada - continuando")
    else:
        logger.info("")
        logger.info("  ╔════════════════════════════════════════════════════╗")
        logger.info(f"  ║   {rechazado_msg:<43} ║")
        logger.info("  ║   Pipeline detenido.                              ║")
        logger.info("  ╚════════════════════════════════════════════════════╝")
        logger.info("")
        raise RuntimeError(
            f"{titulo} rechazada por el medico. "
            "Corrija y ejecute con --reset para reiniciar."
        )


def _show_validation_dialog(titulo="Segmentacion", context="segmentacion") -> bool:
    """Muestra un dialogo de confirmación estandarizado.

    Utiliza el dialogo compartido `show_confirmation_dialog` para mantener
    una apariencia y comportamiento consistentes entre todos los módulos.
    """
    from PipelineOrchestrator.utils import show_confirmation_dialog
    # Determinar pregunta e instrucciones según contexto
    if context == "fusion":
        question = "&iquest;La fusión CT+PET es correcta?"
        instructions = (
            "Navegue los cortes axial/sagital/coronal.<br>"
            "Verifique que PET y CT coincidan anatomicamente.<br>"
            "Use el slider de opacidad del PET si es necesario."
        )
    else:
        question = "&iquest;La segmentación es correcta?"
        instructions = (
            "Navegue los cortes axial/sagital/coronal.<br>"
            "Verifique que los órganos segmentados sean correctos.<br>"
            "Use la vista 3D para inspeccionar la segmentación."
        )
    # Llamar al dialogo genérico
    return show_confirmation_dialog(f"3Dosim — Validar {titulo}", question, instructions)
