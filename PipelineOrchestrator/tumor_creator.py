"""
Gestion de tumor en el pipeline 3Dosim.
Soporta 3 modos configurados desde pipeline_config.jsonc:

  "synthetic"  → Tumor esferico automatico en el higado (default)
  "load_file"  → Carga tumor desde archivo NIfTI
  "manual"     → El usuario segmenta el tumor en 3D Slicer

En todos los modos, opcionalmente genera higado_sano = higado - tumor.

Flujo comun:
  1. Extraer mascara del higado desde TotalSegmentator
  2. Obtener mascara del tumor (segun modo)
  3. Agregar tumor como nuevo segmento
  4. (Opcional) Crear "higado_sano" = higado - tumor como nuevo segmento
"""

import logging
import numpy as np
import os
from typing import Optional, Tuple

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


# ======================================================================
# ORQUESTADOR PRINCIPAL
# ======================================================================

def create_tumor(
    segmentation_node,
    ct_node,
    tumor_config: dict,
) -> dict:
    """
    Crea un tumor en la segmentacion segun la configuracion.

    Args:
        segmentation_node: vtkMRMLSegmentationNode con segmentacion TS
        ct_node: vtkMRMLScalarVolumeNode del CT (para geometria)
        tumor_config: dict con configuracion del tumor (de pipeline_config.jsonc)

    Returns:
        dict con informacion del tumor creado.
        Claves comunes: tumor_voxels, tumor_volume_cc, mode,
                        liver_volume_cc, healthy_liver_volume_cc.
        Claves adicionales segun modo:
          synthetic: tumor_center_ijk, tumor_radius_mm
          load_file: tumor_source_path
          manual: tumor_segment_name
    """
    mode = tumor_config.get("mode", "synthetic")
    create_healthy = tumor_config.get("create_healthy_liver", True)

    logger.info("")
    logger.info("  ========================================================")
    logger.info(f"  Tumor: modo '{mode}'")
    logger.info("  ========================================================")
    logger.info("")

    if segmentation_node is None:
        raise RuntimeError("Nodo de segmentacion no disponible")
    if ct_node is None:
        raise RuntimeError("Nodo CT no disponible")

    # Extraer mascara del higado (necesaria para healthy_liver y synthetic)
    liver_segment_name = tumor_config.get("liver_segment_name", "liver")
    logger.info(f"  Extrayendo '{liver_segment_name}' de la segmentacion...")
    from PipelineOrchestrator.tumor_segmentation import _extract_segment_mask
    liver_mask = _extract_segment_mask(segmentation_node, liver_segment_name)
    if liver_mask is None:
        raise RuntimeError(
            f"No se encontro el segmento '{liver_segment_name}'. "
            "TotalSegmentator debe ejecutarse con task='total'."
        )

    spacing = ct_node.GetSpacing()
    voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
    liver_voxels = int(np.sum(liver_mask))
    liver_volume_cc = liver_voxels * voxel_vol_cc
    logger.info(f"  Higado: {liver_voxels} voxeles, {liver_volume_cc:.1f} cm^3")

    # --- Disparar segun modo ---
    if mode == "synthetic":
        result = _do_synthetic(
            segmentation_node, ct_node, tumor_config,
            liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
        )
    elif mode == "load_file":
        result = _do_load_file(
            segmentation_node, ct_node, tumor_config,
            liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
        )
    elif mode == "manual":
        result = _do_manual(
            segmentation_node, ct_node, tumor_config,
            liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
        )
    elif mode == "ts_liver_lesions":
        result = _do_ts_liver_lesions(
            segmentation_node, ct_node, tumor_config,
            liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
        )
    else:
        raise ValueError(
            f"Modo de tumor desconocido: '{mode}'. "
            "Opciones validas: 'synthetic', 'load_file', 'manual', 'ts_liver_lesions'"
        )

    result["mode"] = mode
    result["liver_volume_cc"] = round(liver_volume_cc, 1)

    # --- Crear higado sano (opcional, aplica a todos los modos) ---
    tumor_mask_ij = result.get("_tumor_mask")  # pasada internamente
    if create_healthy and tumor_mask_ij is not None:
        healthy_voxels, healthy_volume_cc = _add_healthy_liver_segment(
            segmentation_node, ct_node, liver_mask, tumor_mask_ij, voxel_vol_cc,
        )
        result["healthy_liver_voxels"] = int(healthy_voxels)
        result["healthy_liver_volume_cc"] = round(healthy_volume_cc, 1)
    else:
        result["healthy_liver_volume_cc"] = 0.0

    # Limpiar campo interno
    result.pop("_tumor_mask", None)

    logger.info("")
    logger.info("  ========================================================")
    logger.info(f"  Tumor ({mode}) creado exitosamente")
    logger.info(f"    Volumen tumor:    {result.get('tumor_volume_cc', 0):.2f} cm^3")
    logger.info(f"    Volumen higado:   {result.get('liver_volume_cc', 0):.1f} cm^3")
    if create_healthy:
        logger.info(f"    Higado sano:      {result.get('healthy_liver_volume_cc', 0):.1f} cm^3")
    logger.info("  ========================================================")
    logger.info("")

    show_progress(f"Tumor ({mode}) + higado sano creados OK")

    return result


# ======================================================================
# MODO 1: TUMOR SINTETICO ESFERICO
# ======================================================================

def _do_synthetic(
    segmentation_node, ct_node, tumor_config,
    liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
) -> dict:
    """Crea tumor esferico sintetico en el centroide del higado."""
    tumor_radius_mm = tumor_config.get("synthetic_radius_mm", 10.0)
    segment_name = tumor_config.get("synthetic_segment_name", "Tumor_Sintetico")
    segment_color = tumor_config.get("synthetic_segment_color", [1.0, 0.0, 0.0])

    logger.info(f"  Modo: SINTETICO — esfera de {tumor_radius_mm} mm radio en higado")

    # --- 1. Calcular centroide del higado ---
    centroid = _compute_centroid(liver_mask)
    if centroid is None:
        raise RuntimeError("No se pudo calcular centroide del higado (mascara vacia)")
    cz, cy, cx = centroid
    logger.info(f"  Centroide (IJK): slice={cz}, row={cy}, col={cx}")

    # Verificar que el centroide este dentro del higado
    if liver_mask[cz, cy, cx] == 0:
        logger.warning("  Centroide en voxel NO higado. Buscando voxel mas cercano...")
        centroid = _find_nearest_liver_voxel(liver_mask, cz, cy, cx)
        cz, cy, cx = centroid
        logger.info(f"  Centroide corregido (IJK): slice={cz}, row={cy}, col={cx}")

    # --- 2. Crear mascara esferica ---
    logger.info(f"  Creando esfera de {tumor_radius_mm} mm radio...")
    tumor_mask = _create_sphere_mask(
        liver_mask.shape, cz, cy, cx,
        tumor_radius_mm, spacing
    )

    # Intersectar con el higado (el tumor solo crece dentro del parenquima)
    tumor_mask = tumor_mask & (liver_mask > 0)

    tumor_voxels = int(np.sum(tumor_mask))
    tumor_volume_cc = tumor_voxels * voxel_vol_cc
    logger.info(f"  Tumor: {tumor_voxels} voxeles, {tumor_volume_cc:.2f} cm^3")

    if tumor_voxels == 0:
        raise RuntimeError(
            "El tumor sintetico tiene 0 voxeles dentro del higado. "
            "Revise que el radio sea suficiente y el higado sea visible."
        )

    # --- 3. Agregar tumor como segmento ---
    _add_mask_as_segment(
        segmentation_node, ct_node, tumor_mask,
        segment_name=segment_name,
        color=segment_color,
    )

    return {
        "tumor_center_ijk": (int(cz), int(cy), int(cx)),
        "tumor_radius_mm": tumor_radius_mm,
        "tumor_voxels": int(tumor_voxels),
        "tumor_volume_cc": round(tumor_volume_cc, 2),
        "_tumor_mask": tumor_mask,
    }


# ======================================================================
# MODO 2: CARGAR TUMOR DESDE ARCHIVO NIfTI
# ======================================================================

def _do_load_file(
    segmentation_node, ct_node, tumor_config,
    liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
) -> dict:
    """Carga mascara de tumor desde un archivo NIfTI."""
    nifti_path = tumor_config.get("load_file_path", "")
    segment_name_loaded = tumor_config.get("load_segment_name", "Tumor_Cargado")
    segment_color = tumor_config.get("load_segment_color", [1.0, 0.0, 0.0])

    if not nifti_path:
        raise RuntimeError(
            "Modo 'load_file' requiere 'load_file_path' en pipeline_config.jsonc"
        )
    if not os.path.isfile(nifti_path):
        raise FileNotFoundError(
            f"Archivo NIfTI de tumor no encontrado: {nifti_path}"
        )

    logger.info(f"  Modo: CARGA DESDE ARCHIVO")
    logger.info(f"  Archivo: {nifti_path}")

    # Cargar NIfTI usando Slicer
    import slicer
    import vtk

    # Cargar el nodo labelmap desde NIfTI
    tumor_labelmap_node = slicer.util.loadVolume(nifti_path)
    if tumor_labelmap_node is None:
        raise RuntimeError(f"No se pudo cargar el archivo NIfTI: {nifti_path}")

    # Verificar que tenga datos
    if tumor_labelmap_node.GetImageData() is None:
        slicer.mrmlScene.RemoveNode(tumor_labelmap_node)
        raise RuntimeError(f"El archivo NIfTI cargado no contiene datos de imagen: {nifti_path}")

    # Obtener la mascara como numpy array
    tumor_mask_original = slicer.util.arrayFromVolume(tumor_labelmap_node)
    # Binarizar (cualquier valor > 0 es tumor)
    tumor_mask = (tumor_mask_original > 0).astype(np.uint8)

    tumor_voxels = int(np.sum(tumor_mask))
    tumor_volume_cc = tumor_voxels * voxel_vol_cc
    logger.info(f"  Tumor cargado: {tumor_voxels} voxeles, {tumor_volume_cc:.2f} cm^3")

    if tumor_voxels == 0:
        slicer.mrmlScene.RemoveNode(tumor_labelmap_node)
        raise RuntimeError(
            f"El archivo NIfTI '{nifti_path}' tiene 0 voxeles de tumor. "
            "Verifique que el archivo contenga una mascara valida."
        )

    # Verificar dimensiones contra el CT
    ct_dims = ct_node.GetImageData().GetDimensions()
    tumor_dims = tumor_mask.shape  # (K, J, I) en Slicer
    if (tumor_dims[2] != ct_dims[0] or
        tumor_dims[1] != ct_dims[1] or
        tumor_dims[0] != ct_dims[2]):
        logger.warning(
            f"  Dimensiones del NIfTI no coinciden con CT: "
            f"tumor {tumor_dims[2]}x{tumor_dims[1]}x{tumor_dims[0]}, "
            f"CT {ct_dims[0]}x{ct_dims[1]}x{ct_dims[2]}"
        )
        logger.warning("  Intentando re-muestrear...")
        # Re-muestrear usando el nodo cargado a la geometria del CT
        try:
            import slicer
            resampled_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeNode", "tumor_resampled_tmp")
            params = {
                'inputVolume': tumor_labelmap_node.GetID(),
                'referenceVolume': ct_node.GetID(),
                'outputVolume': resampled_node.GetID(),
                'pixelType': 'float',
                'interpolationMode': 'NearestNeighbor',
            }
            slicer.cli.run(slicer.modules.brainsresample, None, params, wait_for_completion=True)
            if resampled_node.GetImageData():
                tumor_mask = (slicer.util.arrayFromVolume(resampled_node) > 0).astype(np.uint8)
                tumor_voxels = int(np.sum(tumor_mask))
                tumor_volume_cc = tumor_voxels * voxel_vol_cc
                logger.info(f"  Re-muestreo OK: {tumor_voxels} voxeles, {tumor_volume_cc:.2f} cm^3")
                slicer.mrmlScene.RemoveNode(resampled_node)
        except Exception as e:
            logger.warning(f"  No se pudo re-muestrear: {e}")
            slicer.mrmlScene.RemoveNode(tumor_labelmap_node)
            raise RuntimeError(
                "El NIfTI del tumor tiene dimensiones diferentes al CT "
                f"(tumor: {tumor_dims[2]}x{tumor_dims[1]}x{tumor_dims[0]}, "
                f"CT: {ct_dims[0]}x{ct_dims[1]}x{ct_dims[2]}) "
                "y no se pudo re-muestrear automaticamente. "
                "Verifique que el NIfTI tenga la misma geometria que el CT."
            ) from e

    # Verificar dimensiones finales contra CT antes de intersectar
    final_dims = tumor_mask.shape  # (K, J, I) en Slicer
    if (final_dims[2] != ct_dims[0] or
        final_dims[1] != ct_dims[1] or
        final_dims[0] != ct_dims[2]):
        raise RuntimeError(
            f"Dimensiones del tumor ({final_dims[2]}x{final_dims[1]}x{final_dims[0]}) "
            f"no coinciden con CT ({ct_dims[0]}x{ct_dims[1]}x{ct_dims[2]}). "
            "El NIfTI debe tener la misma geometria que el CT."
        )

    # Intersectar con el higado (el tumor debe estar dentro del parenquima hepatico)
    tumor_in_liver = tumor_mask & (liver_mask > 0)
    tumor_outside_liver_voxels = tumor_voxels - int(np.sum(tumor_in_liver))
    if tumor_outside_liver_voxels > 0:
        logger.warning(
            f"  {tumor_outside_liver_voxels} voxeles de tumor estan FUERA del higado "
            f"({100 * tumor_outside_liver_voxels / max(tumor_voxels, 1):.1f}%)"
        )
        logger.warning("  Se usara solo la interseccion tumor ∩ higado")
        tumor_mask = tumor_in_liver
        tumor_voxels = int(np.sum(tumor_mask))
        tumor_volume_cc = tumor_voxels * voxel_vol_cc
        if tumor_voxels == 0:
            slicer.mrmlScene.RemoveNode(tumor_labelmap_node)
            raise RuntimeError(
                "El tumor cargado no intersecta con el higado. "
                "Verifique que el NIfTI este en el mismo espacio de coordenadas que el CT."
            )

    # Agregar tumor como segmento
    _add_mask_as_segment(
        segmentation_node, ct_node, tumor_mask,
        segment_name=segment_name_loaded,
        color=segment_color,
    )

    # Limpiar nodo temporal
    slicer.mrmlScene.RemoveNode(tumor_labelmap_node)

    return {
        "tumor_source_path": nifti_path,
        "tumor_voxels": int(tumor_voxels),
        "tumor_volume_cc": round(tumor_volume_cc, 2),
        "tumor_outside_liver_voxels": int(tumor_outside_liver_voxels),
        "_tumor_mask": tumor_mask,
    }


# ======================================================================
# MODO 3: SEGMENTACION MANUAL EN 3D SLICER
# ======================================================================

def _do_manual(
    segmentation_node, ct_node, tumor_config,
    liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
) -> dict:
    """
    Prepara el entorno para que el usuario segmente el tumor manualmente en Slicer.

    Flujo:
      1. Crea un segmento vacio "Tumor_Manual" en la segmentacion
      2. Activa el modulo Segment Editor para que el usuario dibuje
      3. Muestra dialogo NO MODAL con instrucciones
      4. Espera que el usuario APRUEBE (confirma que ya segmento)
      5. Extrae la mascara del segmento manual
    """
    segment_name = tumor_config.get("manual_segment_name", "Tumor_Manual")
    segment_color = tumor_config.get("manual_segment_color", [1.0, 0.5, 0.0])

    import slicer
    import vtk

    logger.info(f"  Modo: MANUAL — el usuario segmenta el tumor en 3D Slicer")
    logger.info(f"  Segmento esperado: '{segment_name}'")

    # --- 1. Verificar si ya existe el segmento (restauracion desde checkpoint) ---
    seg_ids = vtk.vtkStringArray()
    segmentation_node.GetSegmentation().GetSegmentIDs(seg_ids)
    existing_segment = None
    for i in range(seg_ids.GetNumberOfValues()):
        sid = seg_ids.GetValue(i)
        seg = segmentation_node.GetSegmentation().GetSegment(sid)
        if seg and seg.GetName() == segment_name:
            existing_segment = sid
            break

    if existing_segment:
        logger.info(f"  Segmento '{segment_name}' ya existe. Usando existente.")
        # Extraer mascara del segmento existente
        tumor_mask = _extract_segment_mask(segmentation_node, segment_name)
        if tumor_mask is None:
            raise RuntimeError(f"El segmento '{segment_name}' existe pero no tiene mascara")
    else:
        # --- 2. Crear segmento vacio ---
        logger.info(f"  Creando segmento vacio '{segment_name}'...")
        new_seg = segmentation_node.GetSegmentation().AddEmptySegment(segment_name)
        new_seg.SetColor(segment_color)

        # --- 3. Activar Segment Editor ---
        try:
            slicer.util.selectModule("SegmentEditor")
            logger.info("  Segment Editor activado. El usuario debe dibujar el tumor.")
        except Exception as e:
            logger.warning(f"  No se pudo activar Segment Editor: {e}")

        # Activar el segmento creado en el editor
        try:
            from slicer.util import getNodesByClass
            editors = getNodesByClass("vtkMRMLSegmentEditorNode")
            if editors:
                editor_node = editors[0]
                editor_node.SetSelectedSegmentID(segment_name)
        except Exception as e:
            logger.debug(f"  No se pudo seleccionar segmento en editor: {e}")

        # --- 4. Dialogo de instrucciones NO MODAL ---
        logger.info("")
        logger.info("  ========================================================")
        logger.info("  SEGMENTACION MANUAL DEL TUMOR")
        logger.info("  ========================================================")
        logger.info("")
        logger.info("  Instrucciones para el medico:")
        logger.info("    1. Use el modulo Segment Editor (ya activado)")
        logger.info("    2. Seleccione el segmento 'Tumor_Manual'")
        logger.info("    3. Dibuje el tumor en las slices usando Paint/Scissors/etc")
        logger.info("    4. Use la vista 3D para verificar la segmentacion")
        logger.info("    5. Cuando termine, haga clic en APROBAR")
        logger.info("")
        logger.info("  Si no puede segmentar ahora, marque RECHAZAR")
        logger.info("  y el tumor se podra cargar desde NIfTI como alternativa.")
        logger.info("  ========================================================")
        logger.info("")

        show_progress("Esperando segmentacion manual del tumor...")

        # Mostrar dialogo NO MODAL real
        _show_manual_tumor_dialog()

        # --- 5. Extraer mascara del segmento manual ---
        tumor_mask = _extract_segment_mask(segmentation_node, segment_name)
        if tumor_mask is None:
            raise RuntimeError(
                f"No se encontro mascara en el segmento '{segment_name}'. "
                "El usuario debe dibujar el tumor antes de APROBAR."
            )

    tumor_voxels = int(np.sum(tumor_mask))
    tumor_volume_cc = tumor_voxels * voxel_vol_cc
    logger.info(f"  Tumor manual: {tumor_voxels} voxeles, {tumor_volume_cc:.2f} cm^3")

    if tumor_voxels == 0:
        raise RuntimeError(
            f"El segmento '{segment_name}' tiene 0 voxeles. "
            "El usuario debe dibujar el tumor."
        )

    # Intersectar con higado (el tumor debe estar dentro del parenquima)
    tumor_in_liver = tumor_mask & (liver_mask > 0)
    tumor_outside = tumor_voxels - int(np.sum(tumor_in_liver))
    if tumor_outside > 0:
        logger.warning(
            f"  {tumor_outside} voxeles ({100 * tumor_outside / max(tumor_voxels, 1):.1f}%) "
            "del tumor manual estan fuera del higado."
        )
        # Permitir voxeles fuera del higado (el medico puede haber segmentado
        # extension tumoral extrahepatica), pero advertirlo.

    return {
        "tumor_voxels": int(tumor_voxels),
        "tumor_volume_cc": round(tumor_volume_cc, 2),
        "tumor_segment_name": segment_name,
        "tumor_outside_liver_voxels": int(tumor_outside),
        "_tumor_mask": tumor_mask,
    }


# ======================================================================
# MODO 4: TOTALSEGMENTATOR LIVER LESIONS (AUTOMATICO)
# ======================================================================

def _do_ts_liver_lesions(
    segmentation_node, ct_node, tumor_config,
    liver_mask, liver_volume_cc, voxel_vol_cc, spacing,
) -> dict:
    """
    Segmenta tumor hepatico automaticamente usando TotalSegmentator task='liver_lesions'.

    Flujo:
      1. Corre TotalSegmentator con task='liver_lesions' sobre el CT
      2. Obtiene mascara binaria de lesiones
      3. Enmascara solo dentro del higado
      4. Filtra lesiones menores a min_volume_cc (ruido)
      5. Agrega como segmento "Tumor_TS"

    NOTA: 'liver_lesions' NO soporta --fast. La segmentacion puede tardar
    entre 5 y 20 minutos dependiendo del tamano del CT y CPU/GPU.
    """
    import time as _time
    segment_name = tumor_config.get("ts_liver_lesions_segment_name", "Tumor_TS")
    segment_color = tumor_config.get("ts_liver_lesions_segment_color", [1.0, 0.2, 0.2])
    min_volume_cc = tumor_config.get("ts_liver_lesions_min_volume_cc", 1.0)

    import slicer
    import numpy as np
    import vtk

    logger.info("  Modo: AUTOMATICO — TotalSegmentator task='liver_lesions'")

    # --- 1. Crear nodo de segmentacion temporal para TS ---
    ts_seg_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLSegmentationNode", "__temp_ts_liver_lesions__"
    )
    ts_seg_node.SetReferenceImageGeometryParameterFromVolumeNode(ct_node)

    # --- 2. Ejecutar TotalSegmentator ---
    logger.info("  ⏳ Ejecutando TotalSegmentator task='liver_lesions'...")
    logger.info("  ┌─────────────────────────────────────────────────────────────┐")
    logger.info("  │  SIN MODO RAPIDO: liver_lesions NO soporta --fast          │")
    logger.info("  │  Tiempo estimado: 5-20 min (depende del tamano del CT)     │")
    logger.info("  │  Paciencia — Slicer mostrara barra de progreso en modulo TS│")
    logger.info("  └─────────────────────────────────────────────────────────────┘")
    logger.info("  (modelo entrenado en ~842 sujetos con lesiones hepaticas)")
    t0 = _time.time()
    try:
        slicer.util.selectModule("TotalSegmentator")
        from TotalSegmentator import TotalSegmentatorLogic
        logic = TotalSegmentatorLogic()
        logic.setupPythonRequirements()
        logic.process(
            inputVolume=ct_node,
            outputSegmentation=ts_seg_node,
            task="liver_lesions",
            fast=False,
            cpu=tumor_config.get("force_cpu", True),
            interactive=False,
        )
    except Exception as e:
        elapsed = _time.time() - t0
        logger.error(f"  FALLO tras {elapsed/60:.1f} min: {e}")
        slicer.mrmlScene.RemoveNode(ts_seg_node)
        raise RuntimeError(
            f"TotalSegmentator liver_lesions fallo tras {elapsed/60:.1f} min: {e}"
        ) from e
    elapsed = _time.time() - t0
    logger.info(f"  ✅ liver_lesions completado en {elapsed/60:.1f} min")

    # --- 3. Convertir segmentacion TS a numpy array ---
    logger.info("  Procesando resultado de liver_lesions...")
    try:
        labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode", "__temp_ts_labelmap__"
        )
        # Generar labelmap mergeado usando la geometria del CT como referencia
        ts_seg_node.GenerateMergedLabelmapForAllSegments(
            labelmap_node,
            slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY,
            ct_node,
        )
        arr = slicer.util.arrayFromVolume(labelmap_node).astype(np.uint8)
        slicer.mrmlScene.RemoveNode(labelmap_node)
    except Exception as e:
        slicer.mrmlScene.RemoveNode(ts_seg_node)
        raise RuntimeError(f"Error extrayendo labelmap de TS: {e}") from e

    slicer.mrmlScene.RemoveNode(ts_seg_node)

    # --- 4. Enmascarar solo dentro del higado ---
    tumor_mask = (arr > 0) & (liver_mask > 0)
    if not tumor_mask.any():
        logger.warning("  liver_lesions: sin lesiones dentro del higado.")
        tumor_mask = np.zeros(liver_mask.shape, dtype=np.uint8)
        n_lesions = 0
        total_voxels = 0
        total_volume_cc = 0.0
        logger.warning("  Se creara tumor vacio (0 voxeles). Pipeline continuara.")
    else:
        # --- 5. Filtrar lesiones por volumen minimo ---
        from scipy import ndimage as ndi

        labeled, num_features = ndi.label(tumor_mask)
        min_voxels = max(1, int(min_volume_cc / voxel_vol_cc))

        result = np.zeros_like(tumor_mask, dtype=np.uint8)
        lesion_count = 0
        for i in range(1, num_features + 1):
            lesion_voxels = int(np.sum(labeled == i))
            if lesion_voxels >= min_voxels:
                result[labeled == i] = 1
                lesion_count += 1

        tumor_mask = result.astype(np.uint8)
        n_lesions = lesion_count
        total_voxels = int(np.sum(tumor_mask))
        total_volume_cc = total_voxels * voxel_vol_cc

        logger.info(f"  Lesiones detectadas: {n_lesions}")
        logger.info(f"  Volumen total tumoral: {total_volume_cc:.2f} cm^3")
        if n_lesions == 0:
            logger.warning("  Todas las lesiones eran menores a {:.1f} cm^3 y fueron filtradas.".format(
                min_volume_cc))

    # --- 6. Agregar tumor como segmento ---
    if total_voxels > 0:
        _add_mask_as_segment(
            segmentation_node, ct_node, tumor_mask,
            segment_name=segment_name,
            color=segment_color,
        )
    else:
        logger.warning(f"  Agregando segmento '{segment_name}' VACIO (0 voxeles)")
        seg = segmentation_node.GetSegmentation().AddEmptySegment(segment_name)
        seg.SetColor(segment_color)

    return {
        "tumor_lesion_count": n_lesions,
        "tumor_min_volume_cc": min_volume_cc,
        "tumor_voxels": int(total_voxels),
        "tumor_volume_cc": round(total_volume_cc, 2),
        "_tumor_mask": tumor_mask.astype(bool) if isinstance(tumor_mask, np.ndarray) else tumor_mask,
    }


def _show_manual_tumor_dialog():
    """Dialogo NO MODAL para segmentacion manual del tumor."""
    from qt import (
        QLabel, QVBoxLayout, QDialog, QPushButton,
        QHBoxLayout, QEventLoop,
    )
    import slicer

    app = slicer.app
    main = slicer.util.mainWindow()

    dialog = QDialog(main)
    dialog.setWindowTitle("3Dosim — Segmentar Tumor Manualmente")
    dialog.setMinimumWidth(500)
    dialog.setModal(False)

    layout = QVBoxLayout()
    layout.setSpacing(12)

    titulo = QLabel(
        '<h3 style="color:#e67e22; text-align:center;">'
        'Segmente el tumor manualmente</h3>'
    )
    titulo.setAlignment(1)
    layout.addWidget(titulo)

    instrucciones = QLabel(
        '<p style="color:#555; font-size:13px;">'
        '<b>1.</b> Use el modulo <b>Segment Editor</b> (ya activado)<br>'
        '<b>2.</b> Seleccione el segmento <b>"Tumor_Manual"</b><br>'
        '<b>3.</b> Dibuje el tumor en las slices (Paint/Scissors/Level Tracing)<br>'
        '<b>4.</b> Use la vista 3D para verificar la segmentacion<br>'
        '<b>5.</b> Cuando termine, haga clic en <b>APROBAR</b><br><br>'
        '<i>Si no puede segmentar ahora, marque RECHAZAR y use '
        'la opcion load_file como alternativa.</i>'
        '</p>'
    )
    instrucciones.setAlignment(1)
    instrucciones.setWordWrap(True)
    layout.addWidget(instrucciones)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(20)

    btn_yes = QPushButton("APROBAR (tumor ya segmentado)")
    btn_no = QPushButton("RECHAZAR (no puedo segmentar ahora)")

    btn_yes.setStyleSheet(
        "QPushButton { background:#27ae60; color:white; font-weight:bold;"
        "  padding:12px 16px; font-size:13px; border-radius:6px; min-width:180px; }"
        "QPushButton:hover { background:#2ecc71; }"
    )
    btn_no.setStyleSheet(
        "QPushButton { background:#c0392b; color:white; font-weight:bold;"
        "  padding:12px 16px; font-size:13px; border-radius:6px; min-width:180px; }"
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

    dialog.adjustSize()
    dialog.show()

    loop = QEventLoop()
    dialog.finished.connect(lambda _: loop.quit())
    loop.exec()

    if not resultado[0]:
        raise RuntimeError(
            "Segmentacion manual del tumor cancelada por el medico."
        )


# ======================================================================
# HIGADO SANO (compartido por todos los modos)
# ======================================================================

def _add_healthy_liver_segment(
    segmentation_node, ct_node,
    liver_mask, tumor_mask, voxel_vol_cc,
) -> Tuple[int, float]:
    """
    Crea segmento 'higado_sano' = higado - tumor.
    Se agrega como segmento verde en la segmentacion.

    Returns:
        (healthy_voxels, healthy_volume_cc)
    """
    logger.info("  Creando higado sano = higado - tumor...")
    healthy_mask = (liver_mask > 0) & (~tumor_mask.astype(bool))
    healthy_voxels = int(np.sum(healthy_mask))
    healthy_volume_cc = healthy_voxels * voxel_vol_cc
    logger.info(f"  Higado sano: {healthy_voxels} voxeles, {healthy_volume_cc:.1f} cm^3")

    if healthy_voxels > 0:
        _add_mask_as_segment(
            segmentation_node, ct_node, healthy_mask.astype(np.uint8),
            segment_name="higado_sano",
            color=[0.0, 1.0, 0.0],  # Verde
        )
    else:
        logger.warning("  Higado sano vacio (tumor == higado completo)")

    return healthy_voxels, healthy_volume_cc


# ======================================================================
# FUNCIONES DE BAJO NIVEL (sin cambios significativos)
# ======================================================================

def _compute_centroid(mask: np.ndarray) -> Optional[Tuple[int, int, int]]:
    """Calcula el centroide de una mascara binaria 3D."""
    coords = np.argwhere(mask > 0)
    if coords.size == 0:
        return None
    centroid = coords.mean(axis=0).astype(int)
    return (centroid[0], centroid[1], centroid[2])


def _find_nearest_liver_voxel(
    mask: np.ndarray, z: int, y: int, x: int
) -> Tuple[int, int, int]:
    """Busca el voxel de higado mas cercano al punto (z, y, x)."""
    liver_coords = np.argwhere(mask > 0)
    if liver_coords.size == 0:
        raise RuntimeError("No hay voxeles de higado en la mascara")
    target = np.array([z, y, x])
    dists = np.sum((liver_coords - target) ** 2, axis=1)
    nearest = liver_coords[np.argmin(dists)]
    return (nearest[0], nearest[1], nearest[2])


def _create_sphere_mask(
    shape: Tuple[int, int, int],
    cz: int, cy: int, cx: int,
    radius_mm: float,
    spacing: Tuple[float, float, float],
) -> np.ndarray:
    """
    Crea una mascara binaria esferica 3D.

    Args:
        shape: (K, J, I) dimensiones del volumen
        cz, cy, cx: centro en coordenadas IJK (z=slice, y=row, x=col)
        radius_mm: radio en mm
        spacing: (sx, sy, sz) espaciado en mm

    Returns:
        numpy array uint8 con 1 en la esfera
    """
    sz, sy, sx = spacing
    Z, Y, X = np.ogrid[:shape[0], :shape[1], :shape[2]]
    dist_mm = np.sqrt(
        ((Z - cz) * sz) ** 2 +
        ((Y - cy) * sy) ** 2 +
        ((X - cx) * sx) ** 2
    )
    mask = (dist_mm <= radius_mm).astype(np.uint8)
    return mask


def _add_mask_as_segment(
    segmentation_node,
    ref_volume_node,
    mask: np.ndarray,
    segment_name: str = "Tumor",
    color: list = None,
):
    """
    Convierte una mascara numpy 3D a un segmento en el nodo de segmentacion.

    Args:
        segmentation_node: vtkMRMLSegmentationNode destino
        ref_volume_node: volumen de referencia (para geometria IJK->RAS)
        mask: numpy array 3D uint8 con la mascara
        segment_name: nombre del nuevo segmento
        color: [R, G, B] color del segmento (default [1,0,0])
    """
    import slicer
    import vtk

    if color is None:
        color = [1.0, 0.0, 0.0]

    # Crear labelmap temporal con la mascara
    labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode", f"__temp_{segment_name}__"
    )
    labelmap_node.SetOrigin(ref_volume_node.GetOrigin())
    labelmap_node.SetSpacing(ref_volume_node.GetSpacing())
    ijk_to_ras = vtk.vtkMatrix4x4()
    ref_volume_node.GetIJKToRASMatrix(ijk_to_ras)
    labelmap_node.SetIJKToRASMatrix(ijk_to_ras)

    # Copiar la mascara al labelmap
    arr = np.zeros(mask.shape, dtype=np.int16)
    arr[mask > 0] = 1
    slicer.util.updateVolumeFromArray(labelmap_node, arr)

    # Renombrar labelmap temporal para que el segmento herede el nombre
    labelmap_node.SetName(f"__import_{segment_name}__")

    # Importar labelmap a segmentacion usando API de Slicer
    num_segs_before = segmentation_node.GetSegmentation().GetNumberOfSegments()
    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
        labelmap_node, segmentation_node
    )
    num_segs_after = segmentation_node.GetSegmentation().GetNumberOfSegments()

    # Buscar el nuevo segmento creado y renombrarlo
    if num_segs_after > num_segs_before:
        seg_ids = vtk.vtkStringArray()
        segmentation_node.GetSegmentation().GetSegmentIDs(seg_ids)
        for i in range(seg_ids.GetNumberOfValues()):
            sid = seg_ids.GetValue(i)
            seg = segmentation_node.GetSegmentation().GetSegment(sid)
            if seg and seg.GetName().startswith("__import_"):
                seg.SetName(segment_name)
                seg.SetColor(color)
                break

    slicer.mrmlScene.RemoveNode(labelmap_node)

    logger.info(f"  Segmento '{segment_name}' agregado con {int(np.sum(mask))} voxeles")
