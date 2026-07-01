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
from typing import Optional
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
    # Geometria DICOM (del primer slice util, para crear nodo calibrado)
    dicom_spacing = None       # (pix_x, pix_y, slice_thick) en mm
    dicom_origin = None        # (x, y, z) del primer slice en RAS
    dicom_direction = None     # 6 valores de ImageOrientationPatient

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
            # Capturar geometria DICOM del primer slice
            pix_spacing = getattr(ds, "PixelSpacing", None)
            slice_thick = getattr(ds, "SliceThickness", None)
            if pix_spacing and slice_thick:
                dicom_spacing = (float(pix_spacing[0]), float(pix_spacing[1]), float(slice_thick))
            img_pos = getattr(ds, "ImagePositionPatient", None)
            if img_pos:
                dicom_origin = (float(img_pos[0]), float(img_pos[1]), float(img_pos[2]))
            img_orient = getattr(ds, "ImageOrientationPatient", None)
            if img_orient:
                dicom_direction = tuple(float(x) for x in img_orient)

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
    # Geometria DICOM para crear nodo calibrado (cuando Slicer no coincide)
    result["dicom_spacing_mm"] = dicom_spacing         # (pix_x, pix_y, slice_thick)
    result["dicom_origin"] = dicom_origin               # (x, y, z) primer slice
    result["dicom_direction"] = dicom_direction          # 6 cosenos directores
    result["dicom_slice_positions"] = [float(slice_positions[i]) for i in sort_idx]
    # Exponer el array 3D Bq/mL para crear nodo calibrado
    result["stacked_bqml_array"] = stacked_bqml

    logger.info(f"  RescaleType: {rescale_type}")
    logger.info(f"  Slopes: {min(slopes):.4f} ~ {max(slopes):.4f}")
    logger.info(f"  Intercepts: {min(intercepts):.4f} ~ {max(intercepts):.4f}")
    logger.info(f"  Actividad total: {result['total_bq']:.4e} Bq = {result['total_gbq']:.4f} GBq")
    logger.info(f"  Bq/mL medio: {result['mean_bqml']:.2f}")

    return result


def _create_node_from_dicom_geometry(bqml_array: np.ndarray,
                                      activity: dict) -> Optional[object]:
    """Crea nodo Slicer con geometria derivada de DICOM directa.

    Usada cuando la shape del array pydicom no coincide con el nodo
    de referencia de Slicer (ej: Slicer agrega slices extra).
    """
    import slicer
    import vtk
    nz, ny, nx = bqml_array.shape  # Slicer orden: KJI

    spacing = activity.get("dicom_spacing_mm")
    origin = activity.get("dicom_origin")
    direction = activity.get("dicom_direction")
    slice_positions = activity.get("dicom_slice_positions", [])

    if not spacing or not origin or not direction or not slice_positions:
        logger.error("  Faltan datos de geometria DICOM")
        return None

    # Calcular espaciado Z real (puede diferir de SliceThickness)
    if len(slice_positions) > 1:
        z_spacing = abs(slice_positions[-1] - slice_positions[0]) / (len(slice_positions) - 1)
    else:
        z_spacing = spacing[2]

    # Crear nodo
    new_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLScalarVolumeNode", "PET_BqmL"
    )

    # Spacing: (x, y, z)
    new_node.SetSpacing(float(spacing[0]), float(spacing[1]), float(z_spacing))

    # IJKToRAS matrix from DICOM direction cosines
    # Direction cosines: row_x, row_y, row_z, col_x, col_y, col_z
    rx, ry, rz, cx, cy, cz = direction
    ijk_to_ras = vtk.vtkMatrix4x4()
    ijk_to_ras.SetElement(0, 0, rx * spacing[0])
    ijk_to_ras.SetElement(1, 0, ry * spacing[0])
    ijk_to_ras.SetElement(2, 0, rz * spacing[0])
    ijk_to_ras.SetElement(0, 1, cx * spacing[1])
    ijk_to_ras.SetElement(1, 1, cy * spacing[1])
    ijk_to_ras.SetElement(2, 1, cz * spacing[1])
    # Z axis = cross product of row and column direction
    kx = ry * cz - rz * cy
    ky = rz * cx - rx * cz
    kz = rx * cy - ry * cx
    ijk_to_ras.SetElement(0, 2, kx * z_spacing)
    ijk_to_ras.SetElement(1, 2, ky * z_spacing)
    ijk_to_ras.SetElement(2, 2, kz * z_spacing)
    # Origin (use first slice position for RAS)
    ijk_to_ras.SetElement(0, 3, origin[0])
    ijk_to_ras.SetElement(1, 3, origin[1])
    ijk_to_ras.SetElement(2, 3, origin[2])
    ijk_to_ras.SetElement(3, 3, 1.0)
    new_node.SetIJKToRASMatrix(ijk_to_ras)

    # Volcar array Bq/mL
    slicer.util.updateVolumeFromArray(new_node, bqml_array)

    # Display node
    pet_dn = new_node.GetDisplayNode()
    if not pet_dn:
        from slicer import vtkMRMLScalarVolumeDisplayNode
        pet_dn = vtkMRMLScalarVolumeDisplayNode()
        slicer.mrmlScene.AddNode(pet_dn)
        pet_dn.SetDefaultColorMap()
        new_node.SetAndObserveDisplayNodeID(pet_dn.GetID())

    new_range = (float(bqml_array.min()), float(bqml_array.max()))
    logger.info(f"  Nodo PET Bq/mL desde geometria DICOM: {new_node.GetName()}")
    logger.info(f"  Shape: {bqml_array.shape}, Spacing: {spacing[0]:.4f}x{spacing[1]:.4f}x{z_spacing:.4f}")
    logger.info(f"  Rango: {new_range[0]:.2f} ~ {new_range[1]:.2f} Bq/mL")
    return new_node


def create_calibrated_pet_node(pet_dir: str, reference_node) -> Optional[object]:
    """Crea un nodo volumen Slicer con valores calibrados en Bq/mL reales.

    Lee los DICOM PET raw con pydicom (per-slice RescaleSlope/Intercept),
    construye el array 3D corregido y lo carga en un nuevo nodo Slicer
    usando la geometria (origin, spacing, IJKToRAS) del reference_node.

    Args:
        pet_dir: Directorio con archivos DICOM PET.
        reference_node: vtkMRMLScalarVolumeNode cargado por Slicer (referencia
                        de geometria y dimensiones).

    Returns:
        vtkMRMLScalarVolumeNode con Bq/mL calibrados, o None si falla.
    """
    if not os.path.isdir(pet_dir):
        logger.error(f"  Directorio PET no encontrado: {pet_dir}")
        return None
    if reference_node is None:
        logger.error("  reference_node es None, no se puede crear nodo calibrado")
        return None

    try:
        import slicer
        import vtk
    except ImportError:
        logger.warning("  slicer no disponible, no se puede crear nodo PET calibrado")
        return None

    # 1. Leer actividad PET con pydicom
    logger.info("  Leyendo DICOM PET raw para calibracion Bq/mL...")
    activity = read_pet_dicom_activity(pet_dir)
    if activity.get("error"):
        logger.warning(f"  No se pudo leer actividad PET: {activity['error']}")
        return None

    bqml_array = activity.get("stacked_bqml_array")
    if bqml_array is None:
        logger.warning("  stacked_bqml_array no disponible en resultado PET")
        return None

    # 2. Verificar dimensiones contra el nodo de referencia (Slicer)
    try:
        ref_array = slicer.util.arrayFromVolume(reference_node)
    except Exception:
        logger.warning("  No se pudo leer array del nodo referencia")
        return None

    logger.info(f"  Array pydicom shape: {bqml_array.shape}")
    logger.info(f"  Array Slicer  shape: {ref_array.shape}")

    if bqml_array.shape != ref_array.shape:
        # Intentar con geometria derivada de DICOM directa
        logger.warning(
            f"  Dimensiones NO coinciden: pydicom {bqml_array.shape} vs "
            f"Slicer {ref_array.shape}. Usando geometria DICOM directa..."
        )
        return _create_node_from_dicom_geometry(bqml_array, activity)

    # 3. Verificar rango de valores
    logger.info(f"  Rango Bq/mL pydicom:  {float(bqml_array.min()):.2f} ~ {float(bqml_array.max()):.2f}")
    logger.info(f"  Rango Bq/mL Slicer:   {float(ref_array.min()):.2f} ~ {float(ref_array.max()):.2f}")

    # 4. Crear nuevo nodo volumen con la misma geometria
    new_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLScalarVolumeNode", "PET_BqmL"
    )
    new_node.SetOrigin(reference_node.GetOrigin())
    new_node.SetSpacing(reference_node.GetSpacing())
    ijk_to_ras = vtk.vtkMatrix4x4()
    reference_node.GetIJKToRASMatrix(ijk_to_ras)
    new_node.SetIJKToRASMatrix(ijk_to_ras)

    slicer.util.updateVolumeFromArray(new_node, bqml_array)

    # 5. Crear display node para que sea visible
    pet_dn = new_node.GetDisplayNode()
    if not pet_dn:
        from slicer import vtkMRMLScalarVolumeDisplayNode
        pet_dn = vtkMRMLScalarVolumeDisplayNode()
        slicer.mrmlScene.AddNode(pet_dn)
        pet_dn.SetDefaultColorMap()
        new_node.SetAndObserveDisplayNodeID(pet_dn.GetID())

    new_range = (float(bqml_array.min()), float(bqml_array.max()))
    logger.info(f"  Nodo PET calibrado creado: {new_node.GetName()}")
    logger.info(f"  Rango escalar Bq/mL: {new_range[0]:.2f} ~ {new_range[1]:.2f}")
    logger.info(f"  Total: {activity['total_bq']:.4e} Bq = {activity['total_gbq']:.4f} GBq")

    return new_node
