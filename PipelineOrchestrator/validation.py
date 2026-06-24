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
    """
    Muestra dialogo NO MODAL — Slicer COMPLETAMENTE operativo.
    El medico navega libremente (slices, ocultar PET, rotar 3D, etc.)

    Args:
        titulo: Titulo del dialogo.
        context: "fusion" o "segmentacion" — cambia texto de instrucciones.

    Returns:
        True si el medico aprueba, False si rechaza.
    """
    try:
        from qt import QLabel, QVBoxLayout, QDialog, QPushButton, QHBoxLayout, QEventLoop
        import slicer

        app = slicer.app
        main = slicer.util.mainWindow()

        # Dialogo NO MODAL sin WindowStaysOnTopHint
        dialog = QDialog(main)
        dialog.setWindowTitle(f"3Dosim — Validar {titulo}")
        dialog.setMinimumWidth(450)
        dialog.setModal(False)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        if context == "fusion":
            pregunta = '&iquest;La fusion CT+PET es correcta?'
            instrucciones = (
                'Navegue los cortes axial/sagital/coronal.<br>'
                'Verifique que PET y CT coincidan anatomicamente.<br>'
                'Use el slider de opacidad del PET si es necesario.'
            )
        else:
            pregunta = '&iquest;La segmentacion es correcta?'
            instrucciones = (
                'Navegue los cortes axial/sagital/coronal.<br>'
                'Verifique que los organos segmentados sean correctos.<br>'
                'Use la vista 3D para inspeccionar la segmentacion.'
            )

        titulo_label = QLabel(
            f'<h3 style="color:#2c3e50; text-align:center;">{pregunta}</h3>'
        )
        titulo_label.setAlignment(1)  # Qt.AlignCenter
        layout.addWidget(titulo_label)
        
        # Instrucciones
        instr_label = QLabel(
            f'<p style="color:#555; text-align:center; font-size:12px;">'
            f'{instrucciones}</p>'
        )
        instr_label.setAlignment(1)
        instr_label.setWordWrap(True)
        layout.addWidget(instr_label)

        # Botones lado a lado
        btn_row = QHBoxLayout()
        btn_row.setSpacing(20)

        btn_yes = QPushButton("APROBAR")
        btn_no = QPushButton("RECHAZAR")

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

        # Posicionar centrado sobre Slicer (geometry es propiedad en Slicer Qt)
        dialog.adjustSize()
        main_rect = main.geometry
        dlg_rect = dialog.geometry
        dialog.move(
            main_rect.x() + (main_rect.width() - dlg_rect.width()) // 2,
            main_rect.y() + (main_rect.height() - dlg_rect.height()) // 2,
        )

        logger.info("  VALIDACION MEDICA — dialogo NO MODAL, Slicer COMPLETAMENTE operativo")
        logger.info("  Navegue slices, oculte PET, revise en 3D, luego APROBAR o RECHAZAR")

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        # Event loop REAL de Qt: Slicer responde 100%, el medico
        # puede navegar slices, modificar ROIs, rotar 3D, etc.
        loop = QEventLoop()
        dialog.finished.connect(lambda _: loop.quit())
        loop.exec()

        return resultado[0]

    except ImportError:
        # Fallback a consola
        logger.info("  (Interfaz Qt no disponible, usando consola)")
        respuesta = input("  La segmentacion es correcta? (si/no): ").strip().lower()
        return respuesta in ("si", "s", "yes", "y")
