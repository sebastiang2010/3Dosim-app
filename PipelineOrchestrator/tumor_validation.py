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
    """
    Muestra dialogo NO MODAL para validar segmentacion tumoral.
    Slicer COMPLETAMENTE operativo durante la revision.

    Args:
        context: "sintetico" o "manual" — cambia las instrucciones.

    Returns:
        True si el medico aprueba, False si rechaza.
    """
    try:
        from qt import QLabel, QVBoxLayout, QDialog, QPushButton, QHBoxLayout, QEventLoop, Qt
        import slicer

        app = slicer.app
        main = slicer.util.mainWindow()

        # Dialogo NO MODAL pero siempre visible encima de Slicer
        dialog = QDialog(main)
        dialog.setWindowTitle("3Dosim — Validar Tumor")
        dialog.setMinimumWidth(450)
        dialog.setModal(False)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        titulo = QLabel(
            '<h3 style="color:#2c3e50; text-align:center;">'
            '&iquest;La segmentacion tumoral es correcta?</h3>'
        )
        titulo.setAlignment(1)  # Qt.AlignCenter
        layout.addWidget(titulo)

        ctx = context.lower() if context else ''
        if 'sintetico' in ctx or 'synthetic' in ctx:
            instrucciones_html = (
                '<p style="color:#555; text-align:center; font-size:12px;">'
                'Tumor SINTETICO generado automaticamente:<br>'
                '  ✓ Esfera de 1 cm radio en el parenquima hepatico<br>'
                '  ✓ Segmento rojo "Tumor_Sintetico" en la segmentacion<br>'
                '  ✓ Segmento verde "higado_sano" (higado - tumor)<br>'
                '<br>'
                '<b>Revise la ubicacion del tumor:</b><br>'
                '1. Navegue slices axial/sagital/coronal<br>'
                '2. Use la vista 3D para inspeccionar el tumor esferico<br>'
                '3. Verifique que el tumor este DENTRO del higado<br>'
                '4. Confirme que el tamano (~4.2 cm³) sea razonable<br>'
                '<br>'
                'Si el tumor sintetico no es adecuado,<br>'
                'marque RECHAZAR y ejecute con --reset.<br>'
                'Luego APROBAR o RECHAZAR.</p>'
            )
        elif 'load_file' in ctx or 'cargado' in ctx or 'archivo' in ctx:
            instrucciones_html = (
                '<p style="color:#555; text-align:center; font-size:12px;">'
                'Tumor CARGADO desde archivo NIfTI:<br>'
                '  ✓ Segmento en la segmentacion<br>'
                '  ✓ Segmento verde "higado_sano" (higado - tumor)<br>'
                '<br>'
                '<b>Revise la segmentacion tumoral:</b><br>'
                '1. Navegue slices axial/sagital/coronal<br>'
                '2. Use la vista 3D para inspeccionar el tumor<br>'
                '3. Verifique que el tumor corresponda al PET/CT<br>'
                '4. Confirme que la ubicacion es correcta<br>'
                '<br>'
                'Luego APROBAR o RECHAZAR.</p>'
            )
        elif 'manual' in ctx:
            instrucciones_html = (
                '<p style="color:#555; text-align:center; font-size:12px;">'
                'Tumor segmentado MANUALMENTE en Slicer:<br>'
                '  ✓ Segmento "Tumor_Manual" en la segmentacion<br>'
                '  ✓ Segmento verde "higado_sano" (higado - tumor)<br>'
                '<br>'
                '<b>Verifique su propia segmentacion:</b><br>'
                '1. Navegue slices axial/sagital/coronal<br>'
                '2. Use la vista 3D para inspeccionar el resultado<br>'
                '3. Confirme que el volumen segmentado es correcto<br>'
                '<br>'
                'Luego APROBAR o RECHAZAR.</p>'
            )
        else:
            instrucciones_html = (
                '<p style="color:#555; text-align:center; font-size:12px;">'
                'Revise la segmentacion tumoral:<br>'
                'Navegue slices axial/sagital/coronal.<br>'
                'Use la vista 3D para inspeccionar el tumor.<br>'
                '<br>'
                'Luego APROBAR o RECHAZAR.</p>'
            )
        instrucciones = QLabel(instrucciones_html)
        instrucciones.setAlignment(1)
        instrucciones.setWordWrap(True)
        layout.addWidget(instrucciones)

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

        # Posicionar centrado sobre Slicer
        dialog.adjustSize()
        main_rect = main.geometry
        dlg_rect = dialog.geometry
        dialog.move(
            main_rect.x() + (main_rect.width() - dlg_rect.width()) // 2,
            main_rect.y() + (main_rect.height() - dlg_rect.height()) // 2,
        )

        logger.info("  VALIDACION TUMOR — dialogo siempre visible, Slicer COMPLETAMENTE operativo")
        logger.info("  Navegue slices, revise tumor en 3D, luego APROBAR o RECHAZAR (dialogo siempre al frente)")

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        # Event loop REAL de Qt
        loop = QEventLoop()
        dialog.finished.connect(lambda _: loop.quit())
        loop.exec()

        return resultado[0]

    except ImportError:
        # Fallback a consola
        logger.info("  (Interfaz Qt no disponible, usando consola)")
        respuesta = input("  La segmentacion tumoral es correcta? (si/no): ").strip().lower()
        return respuesta in ("si", "s", "yes", "y")
