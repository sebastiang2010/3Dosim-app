"""
Segmentacion tumoral hepatica — flujo simplificado.

Algoritmo:
  1. Intentar iniciar servidor MONAI Label automaticamente
  2. Extraer mascara del higado desde la segmentacion de TotalSegmentator
  3. Calcular bounding box del higado + padding anatomico (10 mm)
  4. Crear nodo de segmentacion tumoral VACIO
  5. Mostrar instrucciones segun disponibilidad del servidor

El tumor lo segmenta el medico usando:
  - Si server MONAI Label activo: interfaz web http://localhost:8000
  - Si server no activo: usar MONAIAuto3DSeg u otra herramienta

NO usa SUV threshold.
"""

import logging
import os
import numpy as np
from typing import Optional

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress
from PipelineOrchestrator.monailabel_server import start_server, check_server


def prepare_tumor_segmentation(
    segmentation_node,
    ct_node,
    pet_node=None,
    segment_name: str = "liver",
    padding_mm: float = 10.0,
):
    """
    Prepara el entorno para segmentacion tumoral.

    Flujo:
      1. Intenta iniciar servidor MONAI Label automaticamente
      2. Extrae el higado de TotalSegmentator
      3. Calcula bounding box hepatica con padding
      4. Crea nodo de tumor VACIO
      5. Muestra instrucciones segun disponibilidad del servidor

    Args:
        segmentation_node: vtkMRMLSegmentationNode de TotalSegmentator
        ct_node: vtkMRMLScalarVolumeNode del CT
        pet_node: vtkMRMLScalarVolumeNode del PET (opcional)
        segment_name: nombre del segmento del higado (default "liver")
        padding_mm: padding alrededor del higado en mm (default 10)

    Returns:
        dict con:
            "tumor_node": vtkMRMLSegmentationNode (vacio)
            "liver_mask": numpy array 3D de la mascara hepatica
            "bbox": (rmin, rmax, cmin, cmax, zmin, zmax) bounding box
            "liver_volume_cc": volumen del higado en cm^3
            "server_ok": bool, True si MONAI Label server responde

    Raises:
        RuntimeError: si no se encuentra el higado en la segmentacion
    """
    import slicer
    import vtk

    logger.info("")
    logger.info("  ========================================================")
    logger.info("  Preparacion para segmentacion tumoral")
    logger.info("  ========================================================")
    logger.info("")

    show_progress("Preparando ROI hepatica para segmentacion tumoral...")

    # --- 1. Verificar nodos ---
    if segmentation_node is None:
        raise RuntimeError("Nodo de segmentacion no disponible")
    if ct_node is None:
        raise RuntimeError("Nodo CT no disponible")

    logger.info(f"  Segmentacion: {segmentation_node.GetName()}")
    logger.info(f"  CT: {ct_node.GetName()}")
    if pet_node:
        logger.info(f"  PET: {pet_node.GetName()}")
    logger.info(f"  Organo mascara: '{segment_name}'")
    logger.info(f"  Padding: {padding_mm} mm")

    # --- 2. Iniciar servidor MONAI Label (si no esta corriendo) ---
    logger.info("  Verificando / iniciando servidor MONAI Label...")
    server_proc = start_server(timeout=60)  # Increased timeout to 60 seconds
    server_ok = check_server()
    if server_ok:
        logger.info(f"  ✓ Servidor MONAI Label activo en http://127.0.0.1:8000")
    else:
        logger.warning(f"  ✗ Servidor MONAI Label NO disponible tras 60 segundos")

    # --- 3. Extraer mascara del higado ---
    logger.info("  Extrayendo mascara del higado desde TotalSegmentator...")
    liver_mask = _extract_segment_mask(segmentation_node, segment_name)
    if liver_mask is None:
        raise RuntimeError(
            f"No se encontro el segmento '{segment_name}' en la segmentacion. "
            "TotalSegmentator debe ejecutarse con task='total'."
        )

    liver_voxels = int(np.sum(liver_mask))
    spacing = ct_node.GetSpacing()
    voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
    liver_volume_cc = liver_voxels * voxel_vol_cc
    logger.info(f"  Higado: {liver_voxels} voxeles, {liver_volume_cc:.1f} cm^3")

    # --- 4. Calcular bounding box + padding ---
    logger.info("  Calculando bounding box hepatica con padding...")
    bbox = _compute_bbox_with_padding(liver_mask, spacing, padding_mm)
    rmin, rmax, cmin, cmax, zmin, zmax = bbox
    logger.info(f"  Bounding box (IJK):")
    logger.info(f"    Filas:    {rmin} - {rmax}  ({rmax - rmin} px)")
    logger.info(f"    Columnas: {cmin} - {cmax}  ({cmax - cmin} px)")
    logger.info(f"    Slice:    {zmin} - {zmax}  ({zmax - zmin} px)")

    logger.info(f"    Dimension fisica: "
                f"{(rmax - rmin) * spacing[1]:.0f} x {(cmax - cmin) * spacing[0]:.0f} x "
                f"{(zmax - zmin) * spacing[2]:.0f} mm")

    # --- 5. Crear nodo de tumor vacio ---
    logger.info("  Creando nodo de tumor vacio...")
    tumor_node = _create_empty_tumor_node_fallback(ct_node)
    logger.info(f"  Nodo creado: '{tumor_node.GetName()}'")

    # --- 6. Instrucciones segun disponibilidad del servidor ---
    logger.info("")
    logger.info("  ========================================================")
    logger.info("  SEGMENTACION TUMORAL - INSTRUCCIONES")
    logger.info("  ========================================================")
    logger.info("")

    if server_ok:
        logger.info("  MONAI Label server ACTIVO en http://127.0.0.1:8000")
        logger.info("")
        logger.info("  Opcion 1 - Interfaz Web (recomendado):")
        logger.info("    Abra un browser en http://127.0.0.1:8000")
        logger.info("    Seleccione DeepEdit y segmenta el tumor")
        logger.info("")
        logger.info("  Opcion 2 - MONAIAuto3DSeg en Slicer (automatico):")
        logger.info("    1. Vaya al modulo MONAIAuto3DSeg")
        logger.info("    2. Seleccione el modelo 'liver_tumor' (o similar)")
        logger.info("    3. Establezca el volumen de referencia como el CT")
        logger.info("    4. Establezca el volumen de segmento como el nodo 'Tumor_MONAI'")
        logger.info("    5. Haga clic en 'Apply'")
        logger.info("")
    else:
        logger.info("  MONAI Label server NO disponible")
        logger.info("")
        logger.info("  Para iniciarlo manualmente:")
        logger.info("    PythonSlicer.exe -m monailabel.main start_server"
                    " --app .monai_app --port 8000 --studies .monai_studies")
        logger.info("")
        logger.info("  Luego abra http://127.0.0.1:8000 en su browser")
        logger.info("")
        logger.info("  Alternativa: use MONAIAuto3DSeg para segmentar el tumor automaticamente")
        logger.info("    1. Vaya al modulo MONAIAuto3DSeg")
        logger.info("    2. Seleccione el modelo 'liver_tumor' (o similar)")
        logger.info("    3. Establezca el volumen de referencia como el CT")
        logger.info("    4. Establezca el volumen de segmento como el nodo 'Tumor_MONAI'")
        logger.info("    5. Haga clic en 'Apply'")
        logger.info("")

    logger.info("  El nodo 'Tumor_MONAI' esta listo para recibir la mascara")
    logger.info("  ========================================================")

    show_progress("Nodo de tumor creado — revise instrucciones en consola")

    return {
        "tumor_node": tumor_node,
        "liver_mask": liver_mask,
        "bbox": bbox,
        "liver_volume_cc": round(liver_volume_cc, 1),
        "padding_mm": padding_mm,
        "server_ok": server_ok,
    }


def _extract_segment_mask(segmentation_node, segment_name: str) -> Optional[np.ndarray]:
    """
    Extrae un segmento especifico de un vtkMRMLSegmentationNode como numpy array.

    Args:
        segmentation_node: vtkMRMLSegmentationNode
        segment_name: nombre del segmento a extraer (ej: "liver")

    Returns:
        numpy array 3D uint8 con la mascara, o None si no se encuentra
    """
    import slicer
    import vtk

    seg = segmentation_node.GetSegmentation()
    if seg is None:
        return None

    # Buscar segmento por nombre (exacto o parcial)
    segment_ids = vtk.vtkStringArray()
    seg.GetSegmentIDs(segment_ids)

    found_id = None
    for i in range(segment_ids.GetNumberOfValues()):
        sid = segment_ids.GetValue(i)
        segment = seg.GetSegment(sid)
        if segment:
            seg_name = segment.GetName()
            if seg_name.lower() == segment_name.lower():
                found_id = sid
                break

    if found_id is None:
        # Busqueda parcial (por si TS lo nombro distinto)
        for i in range(segment_ids.GetNumberOfValues()):
            sid = segment_ids.GetValue(i)
            segment = seg.GetSegment(sid)
            if segment and segment_name.lower() in segment.GetName().lower():
                found_id = sid
                logger.info(f"  Segmento encontrado por coincidencia parcial: "
                            f"'{segment.GetName()}'")
                break

    if found_id is None:
        logger.warning(f"  Segmento '{segment_name}' no encontrado")
        logger.info("  Segmentos disponibles en la segmentacion:")
        for i in range(segment_ids.GetNumberOfValues()):
            sid = segment_ids.GetValue(i)
            segment = seg.GetSegment(sid)
            if segment:
                logger.info(f"    - {segment.GetName()}")
        return None

    # Exportar el segmento a labelmap usando API plural (compatible Slicer 5.x)
    labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode", "__temp_liver_mask__"
    )

    try:
        import vtk

        # Buscar nodo de referencia CT para geometria
        ref_node = None
        try:
            ref_node = slicer.util.getNode("3Dosim_CT_anon")
        except Exception:
            pass

        # ExportSegmentsToLabelmapNode requiere un vtkStringArray (plural)
        # incluso para un solo segmento
        segment_ids = vtk.vtkStringArray()
        segment_ids.InsertNextValue(found_id)

        if ref_node is None:
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                segmentation_node, segment_ids, labelmap_node
            )
        else:
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                segmentation_node, segment_ids, labelmap_node, ref_node
            )

        array = slicer.util.arrayFromVolume(labelmap_node)  # (K, J, I)
        if array is None:
            slicer.mrmlScene.RemoveNode(labelmap_node)
            return None

        mask = (array > 0).astype(np.uint8)

        slicer.mrmlScene.RemoveNode(labelmap_node)
        return mask

    except Exception as e:
        logger.warning(f"  Error exportando segmento: {e}")
        slicer.mrmlScene.RemoveNode(labelmap_node)
        return None


def _compute_bbox_with_padding(mask, spacing, padding_mm: float = 10.0):
    """
    Calcula bounding box de la mascara con padding en mm.

    Args:
        mask: numpy array 3D uint8
        spacing: (sx, sy, sz) espaciado en mm (de CT o PET)
        padding_mm: padding adicional en mm

    Returns:
        tuple: (rmin, rmax, cmin, cmax, zmin, zmax) en coordenadas IJK
    """
    # Encontrar voxeles positivos
    coords = np.argwhere(mask > 0)
    if coords.size == 0:
        return (0, 0, 0, 0, 0, 0)

    zmin, rmin, cmin = coords.min(axis=0)
    zmax, rmax, cmax = coords.max(axis=0)

    # Padding en voxeles (redondeado). OJO: spacing[0]=col, spacing[1]=row, spacing[2]=slice
    # numpy: (z, y, x) = (slice, row, col)
    pad_z = int(padding_mm / spacing[2]) if spacing[2] > 0 else 1
    pad_r = int(padding_mm / spacing[1]) if spacing[1] > 0 else 1
    pad_c = int(padding_mm / spacing[0]) if spacing[0] > 0 else 1

    # Aplicar padding con clamps a bordes
    zmax_s, rmax_s, cmax_s = mask.shape
    zmin = max(0, zmin - pad_z)
    rmin = max(0, rmin - pad_r)
    cmin = max(0, cmin - pad_c)
    zmax = min(zmax_s - 1, zmax + pad_z)
    rmax = min(rmax_s - 1, rmax + pad_r)
    cmax = min(cmax_s - 1, cmax + pad_c)

    return (rmin, rmax, cmin, cmax, zmin, zmax)


def _create_empty_tumor_node_fallback(ref_node):
    """
    Crea un vtkMRMLSegmentationNode VACIO como fallback
    si la configuracion del widget MONAI Label falla.

    Args:
        ref_node: nodo de referencia para geometria (ej: CT)

    Returns:
        vtkMRMLSegmentationNode con un segmento vacio llamado "Tumor"
    """
    import slicer

    seg_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    seg_node.SetName("Tumor_MONAI")
    seg_node.CreateDefaultDisplayNodes()

    if ref_node is not None:
        try:
            seg_node.SetReferenceImageGeometryParameterFromVolumeNode(ref_node)
            logger.info(f"  Geometria de referencia asignada desde: '{ref_node.GetName()}'")
        except Exception as e:
            logger.warning(f"  No se pudo asignar geometria de referencia: {e}")

    seg_node.GetSegmentation().AddEmptySegment(
        "Tumor",
        "Tumor hepatico (segmentar con MONAI Label)",
        [1.0, 0.0, 0.0]
    )

    logger.info(f"  Nodo de tumor vacio creado (fallback): '{seg_node.GetName()}'")
    return seg_node
