"""
fusion_dialog.py - Dialogo informativo post-fusion CT+PET.

Muestra en un QDialog NO MODAL:
  - Datos del paciente
  - Info del CT (dimensiones, spacing)
  - Info del PET DICOM (RescaleType, actividad)
  - Actividad total Bq, GBq, Bq/ml
  - Verificaciones de consistencia

NO bloquea el pipeline. El usuario puede cerrarlo cuando quiera.
"""

import logging

logger = logging.getLogger(__name__)


def show_fusion_info_dialog(
    pet_activity: dict,
    ct_dims: tuple = None,
    ct_spacing: tuple = None,
    ct_slices: int = 0,
    pet_dims: tuple = None,
    pet_spacing: tuple = None,
    pet_slices_loaded: int = 0,
    ct_node_name: str = "",
    pet_node_name: str = "",
    patient_id: str = "",
    patient_weight_kg: float = None,
    registration_method: str = "Elastix rigid",
    registration_time_s: float = 0.0,
    registration_conserved: bool = True,
):
    """
    Muestra un dialogo NO MODAL con toda la informacion de la fusion.

    Args:
        pet_activity: dict retornado por read_pet_dicom_activity()
        ct_dims: (nx, ny) dimensiones del CT
        ct_spacing: (sx, sy, sz) espaciado del CT en mm
        ct_slices: numero de slices del CT
        pet_dims: (nx, ny) dimensiones del PET
        pet_spacing: (sx, sy, sz) espaciado del PET en mm
        pet_slices_loaded: numero de slices PET cargados en Slicer
        ct_node_name: nombre del nodo CT en Slicer
        pet_node_name: nombre del nodo PET en Slicer
        patient_id: identificador del paciente
        patient_weight_kg: peso del paciente (kg)
        registration_method: metodo de registro usado
        registration_time_s: tiempo de registro en segundos
        registration_conserved: si la actividad se conservo post-registro
    """
    try:
        from qt import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QPushButton, QFont, QFrame, QApplication,
        )
        import slicer
    except ImportError:
        logger.warning("Qt no disponible, no se puede mostrar dialogo de fusion")
        return

    main_window = slicer.util.mainWindow()
    dialog = QDialog(main_window)
    dialog.setWindowTitle("3Dosim — Fusion CT+PET completada")
    dialog.setMinimumWidth(520)
    dialog.setModal(True)  # Bloquea hasta que el usuario cierre

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 15, 20, 15)
    layout.setSpacing(8)

    # ── Helper: agregar seccion con titulo ──
    def _add_section(title):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        lbl = QLabel(f"<b>{title}</b>")
        lbl.setStyleSheet("font-size: 13px; color: #2c3e50;")
        layout.addWidget(lbl)

    def _add_info(label, value, icon=""):
        if value is None or value == "":
            value = "—"
        hl = QHBoxLayout()
        hl.setSpacing(10)
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(20)
        hl.addWidget(icon_lbl)
        lbl = QLabel(f"<b>{label}:</b>")
        lbl.setFixedWidth(160)
        lbl.setStyleSheet("color: #555;")
        hl.addWidget(lbl)
        val = QLabel(str(value))
        val.setWordWrap(True)
        val.setStyleSheet("color: #000;")
        hl.addWidget(val, 1)
        layout.addLayout(hl)

    def _add_verification(ok: bool, text: str):
        icon = "✅" if ok else "⚠️"
        color = "#27ae60" if ok else "#e67e22"
        hl = QHBoxLayout()
        hl.setSpacing(10)
        hl.addWidget(QLabel(icon))
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color};")
        hl.addWidget(lbl, 1)
        layout.addLayout(hl)

    # ── Titulo ──
    title = QLabel("<h2>Fusion CT + PET completada</h2>")
    title.setStyleSheet("color: #2c3e50; margin-bottom: 5px;")
    layout.addWidget(title)

    # ── Paciente ──
    _add_section("Paciente")
    _add_info("ID", patient_id or pet_node_name or ct_node_name)
    if patient_weight_kg:
        _add_info("Peso", f"{patient_weight_kg:.1f} kg")

    # ── CT ──
    _add_section("CT")
    if ct_dims and ct_spacing:
        _add_info("Dimensiones",
                   f"{ct_dims[0]} × {ct_dims[1]} × {ct_slices}")
        _add_info("Espaciado",
                   f"{ct_spacing[0]:.3f} × {ct_spacing[1]:.3f} × {ct_spacing[2]:.3f} mm")
    _add_info("Nodo Slicer", ct_node_name)

    # ── PET (DICOM raw) ──
    _add_section("PET (desde DICOM raw)")

    if pet_activity.get("error"):
        _add_verification(False, f"Error leyendo PET: {pet_activity['error']}")
    else:
        _add_info("RescaleType",
                   pet_activity.get("rescale_type", "N/A"))
        if pet_activity.get("slopes"):
            s_min = min(pet_activity["slopes"])
            s_max = max(pet_activity["slopes"])
            if abs(s_max - s_min) < 0.001:
                _add_info("RescaleSlope", f"{s_min:.4f} (constante)")
            else:
                _add_info("RescaleSlope",
                           f"{s_min:.4f} ~ {s_max:.4f} ({pet_activity['n_slices']} slices)")
        if pet_activity.get("intercepts"):
            i_min = min(pet_activity["intercepts"])
            i_max = max(pet_activity["intercepts"])
            if abs(i_max - i_min) < 0.001:
                _add_info("RescaleIntercept", f"{i_min:.4f} (constante)")
            else:
                _add_info("RescaleIntercept",
                           f"{i_min:.4f} ~ {i_max:.4f} ({pet_activity['n_slices']} slices)")
        _add_info("Slices DICOM", pet_activity.get("n_slices", 0))
        _add_info("Vol. voxel",
                   f"{pet_activity.get('voxel_vol_cm3', 0):.6f} cm³")

    if pet_dims and pet_spacing:
        _add_info("Dimensiones (Slicer)",
                   f"{pet_dims[0]} × {pet_dims[1]} × {pet_slices_loaded}")
        _add_info("Espaciado (Slicer)",
                   f"{pet_spacing[0]:.3f} × {pet_spacing[1]:.3f} × {pet_spacing[2]:.3f} mm")

    # ── Actividad ──
    _add_section("Actividad (desde DICOM raw)")

    total_bq = pet_activity.get("total_bq", 0)
    total_gbq = pet_activity.get("total_gbq", 0)
    _add_info("Total", f"{total_bq:.4e} Bq")
    _add_info("Total", f"{total_gbq:.4f} GBq")
    # mCi (1 mCi = 37 MBq)
    total_mci = total_bq / 3.7e7
    _add_info("Total", f"{total_mci:.2f} mCi")

    mean_bqml = pet_activity.get("mean_bqml", 0)
    max_bqml = pet_activity.get("max_bqml", 0)
    _add_info("Concentracion media", f"{mean_bqml:.2f} Bq/mL")
    _add_info("Concentracion max", f"{max_bqml:.2f} Bq/mL")

    nonzero = pet_activity.get("nonzero_voxels", 0)
    _add_info("Voxeles activos", f"{nonzero:,}")

    # ── Registro ──
    _add_section("Registro PET → CT")
    _add_info("Metodo", registration_method)
    if registration_time_s > 0:
        _add_info("Duracion", f"{registration_time_s:.1f} s")
    if registration_conserved:
        _add_verification(True, "Actividad conservada post-registro")
    else:
        _add_verification(False, "Actividad NO conservada — verificar")

    # ── Verificaciones ──
    _add_section("Verificaciones")

    # 1. Unidades
    rt = pet_activity.get("rescale_type", "")
    if rt.upper() == "BQML":
        _add_verification(True, f"Unidades PET: {rt} (Bq/mL — correcto)")
    elif rt:
        _add_verification(False, f"Unidades PET: {rt} (no es BQML — verificar)")
    else:
        _add_verification(False, "Unidades PET: no disponible")

    # 2. Rango de actividad
    if total_gbq > 0.1 and total_gbq < 50:
        _add_verification(True, f"Actividad {total_gbq:.3f} GBq — rango normal")
    elif total_gbq <= 0.1 and total_gbq > 0:
        _add_verification(False, f"Actividad {total_gbq:.4f} GBq — muy baja, verificar")
    elif total_gbq >= 50:
        _add_verification(False, f"Actividad {total_gbq:.2f} GBq — muy alta, verificar")
    else:
        _add_verification(False, "Actividad en cero — revisar DICOM PET")

    # 3. Solapamiento CT/PET
    if ct_dims and pet_dims:
        if abs(ct_dims[0] - pet_dims[0]) < 10:
            _add_verification(True, "Dimensiones CT/PET similares")
        else:
            _add_verification(False,
                               f"Dimensiones distintas: CT {ct_dims[0]}×{ct_dims[1]}, "
                               f"PET {pet_dims[0]}×{pet_dims[1]}")

    # 4. Voxeles activos
    if nonzero > 100:
        _add_verification(True, f"{nonzero:,} voxeles con actividad > 0")
    elif nonzero > 0:
        _add_verification(False, f"Solo {nonzero} voxeles con actividad — verificar")
    else:
        _add_verification(False, "Sin voxeles activos — revisar PET")

    # Warnings del reader
    for w in pet_activity.get("warnings", []):
        _add_verification(False, w[:120])

    # ── Boton cerrar ──
    btn_layout = QHBoxLayout()
    btn_layout.addStretch(1)
    close_btn = QPushButton("Cerrar")
    close_btn.setStyleSheet("""
        QPushButton {
            padding: 8px 24px;
            font-size: 13px;
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
        }
        QPushButton:hover { background-color: #2980b9; }
    """)
    close_btn.clicked.connect(dialog.accept)  # accept() cierra correctamente el modal
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)

    # Mostrar MODAL — bloquea hasta que el usuario cierre
    try:
        dialog.exec()
        logger.info("  Dialogo de fusion cerrado por el usuario")
    except Exception as e:
        logger.warning(f"  Error en dialogo de fusion: {e}")
