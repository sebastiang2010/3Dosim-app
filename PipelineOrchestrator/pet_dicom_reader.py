"""
pet_dicom_reader.py - Lectura de DICOM PET raw con rescale por slice.

Replica la logica de f_Rescale_Bq.m del modulo 1 de MATLAB:
  1. Lee archivos DICOM PET uno por uno (cada slice es un archivo)
  2. Por cada slice: lee RescaleType, RescaleSlope, RescaleIntercept
  3. Si RescaleType == 'BQML':
       Bq/mL = pixel_array * RescaleSlope + RescaleIntercept
  4. Convierte Bq/mL -> Bq por voxel:
       Bq = Bq/mL * (PixelSpacing_x/10 * PixelSpacing_y/10 * SliceThickness/10)
  5. Retorna actividad total en Bq + metadata por slice

Uso:
    from PipelineOrchestrator.pet_dicom_reader import read_pet_dicom_activity
    result = read_pet_dicom_activity("/path/to/PET/dir")
    # result = {
    #     "total_bq": 1.25e9,
    #     "total_gbq": 1.25,
    #     "rescale_type": "BQML",
    #     "n_slices": 159,
    #     "slopes": [1.0, ...],
    #     "intercepts": [0.0, ...],
    #     "voxel_vol_cm3": 0.042,
    #     "activity_per_slice_bq": [array of per-slice totals],
    #     "mean_bqml": 4320.5,
    #     "max_bqml": 21500.0,
    #     "nonzero_voxels": 85432,
    #     "warnings": [],
    # }
"""

import os
import logging
import numpy as np

logger = logging.getLogger(__name__)


def read_pet_dicom_activity(pet_dir: str) -> dict:
    """
    Lee todos los archivos DICOM PET en un directorio y computa la actividad
    real usando la formula de f_Rescale_Bq.m (MATLAB modulo 1).

    Args:
        pet_dir: Directorio con archivos DICOM PET (un archivo por slice)

    Returns:
        dict con claves: total_bq, total_gbq, rescale_type, n_slices,
                         slopes, intercepts, voxel_vol_cm3,
                         activity_per_slice_bq, mean_bqml, max_bqml,
                         nonzero_voxels, warnings, error (si falla)
    """
    result = {
        "total_bq": 0.0,
        "total_gbq": 0.0,
        "rescale_type": None,
        "n_slices": 0,
        "slopes": [],
        "intercepts": [],
        "voxel_vol_cm3": 0.0,
        "activity_per_slice_bq": [],
        "mean_bqml": 0.0,
        "max_bqml": 0.0,
        "nonzero_voxels": 0,
        "warnings": [],
        "error": None,
    }

    if not os.path.isdir(pet_dir):
        result["error"] = f"Directorio PET no encontrado: {pet_dir}"
        logger.error(result["error"])
        return result

    try:
        import pydicom
    except ImportError:
        result["error"] = "pydicom no disponible"
        logger.error(result["error"])
        return result

    # --- 1. Listar archivos DICOM del PET ---
    dcm_files = sorted([
        f for f in os.listdir(pet_dir)
        if os.path.isfile(os.path.join(pet_dir, f))
    ])

    if not dcm_files:
        result["error"] = f"No se encontraron archivos en {pet_dir}"
        return result

    logger.info(f"  Leyendo {len(dcm_files)} archivos DICOM PET desde {pet_dir}")

    # --- 2. Leer cada slice ---
    slices_bqml = []        # lista de arrays 2D en Bq/mL (por slice)
    slices_bq = []          # lista de arrays 2D en Bq (por slice)
    slopes = []
    intercepts = []
    rescale_type = None
    voxel_vol_cm3 = None
    slice_positions = []
    all_warnings = []

    for fname in dcm_files[:500]:  # safety cap
        fpath = os.path.join(pet_dir, fname)
        try:
            ds = pydicom.dcmread(fpath, force=True)
        except Exception as e:
            all_warnings.append(f"No se pudo leer {fname}: {e}")
            continue

        # Verificar que sea PET
        modality = getattr(ds, "Modality", None)
        if modality != "PT":
            continue

        try:
            pixel_array = ds.pixel_array.astype(np.float64)
        except Exception:
            continue

        if pixel_array.size == 0:
            continue

        # --- 2a. Leer RescaleType (solo del primer slice util) ---
        if rescale_type is None:
            rescale_type = getattr(ds, "RescaleType", None) or ""

        # --- 2b. Leer RescaleSlope y RescaleIntercept ---
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        slopes.append(slope)
        intercepts.append(intercept)

        # --- 2c. Aplicar rescale: raw -> Bq/mL (solo si BQML) ---
        if rescale_type.upper() == "BQML":
            bqml_slice = pixel_array * slope + intercept
        else:
            # Si no es BQML, asumimos que ya son Bq/mL o no podemos convertir
            bqml_slice = pixel_array
            if len(all_warnings) < 3:
                all_warnings.append(
                    f"RescaleType='{rescale_type}' no es BQML. "
                    "Se usan valores sin rescale. "
                    "Verificar unidades manualmente."
                )

        slices_bqml.append(bqml_slice)

        # --- 2d. Calcular volumen del voxel (mm -> cm) ---
        if voxel_vol_cm3 is None:
            pix_spacing = getattr(ds, "PixelSpacing", [1.0, 1.0])
            slice_thick = getattr(ds, "SliceThickness", 1.0)
            # MATLAB: vPET = [PixelSpacing; SliceThickness] ./ 10
            # mm -> cm: dividir por 10 cada dimension
            sx_cm = float(pix_spacing[0]) / 10.0
            sy_cm = float(pix_spacing[1]) / 10.0
            sz_cm = float(slice_thick) / 10.0
            voxel_vol_cm3 = sx_cm * sy_cm * sz_cm  # cm^3 (= mL)
            logger.info(f"  Voxel PET: {sx_cm*10:.3f} x {sy_cm*10:.3f} x {sz_cm*10:.3f} mm")
            logger.info(f"  Volumen voxel: {voxel_vol_cm3:.6f} cm^3 (= mL)")

        # --- 2e. Bq/mL -> Bq por voxel ---
        # MATLAB: I = I .* prod(vPET)
        bq_slice = bqml_slice * voxel_vol_cm3
        slices_bq.append(bq_slice)

        # Posicion del slice (para ordenamiento)
        img_pos = getattr(ds, "ImagePositionPatient", None)
        if img_pos:
            slice_positions.append(float(img_pos[2]))
        else:
            slice_positions.append(len(slices_bq))

    # --- 3. Consolidar resultados ---
    if not slices_bq:
        result["error"] = "No se encontraron slices PET en los archivos DICOM"
        return result

    result["n_slices"] = len(slices_bq)
    result["rescale_type"] = rescale_type
    result["slopes"] = slopes
    result["intercepts"] = intercepts
    result["voxel_vol_cm3"] = voxel_vol_cm3
    result["warnings"] = all_warnings

    # Stackear slices (ordenados por posicion Z)
    sort_idx = np.argsort(slice_positions)
    stacked_bq = np.stack([slices_bq[i] for i in sort_idx], axis=0)

    # Actividad total
    total_bq = float(np.sum(stacked_bq))
    result["total_bq"] = total_bq
    result["total_gbq"] = total_bq / 1e9

    # Actividad por slice
    result["activity_per_slice_bq"] = [float(np.sum(slices_bq[i])) for i in sort_idx]

    # Estadisticas Bq/mL
    stacked_bqml = np.stack([slices_bqml[i] for i in sort_idx], axis=0)
    result["mean_bqml"] = float(np.mean(stacked_bqml[stacked_bqml > 0])) if np.any(stacked_bqml > 0) else 0.0
    result["max_bqml"] = float(np.max(stacked_bqml))
    result["min_bqml"] = float(np.min(stacked_bqml[stacked_bqml > 0])) if np.any(stacked_bqml > 0) else 0.0
    result["nonzero_voxels"] = int(np.sum(stacked_bq > 0))

    logger.info(f"  RescaleType: {rescale_type}")
    logger.info(f"  Slopes: {min(slopes):.4f} ~ {max(slopes):.4f}")
    logger.info(f"  Intercepts: {min(intercepts):.4f} ~ {max(intercepts):.4f}")
    logger.info(f"  Actividad total: {result['total_bq']:.4e} Bq = {result['total_gbq']:.4f} GBq")
    logger.info(f"  Bq/mL medio: {result['mean_bqml']:.2f}")

    return result
