"""
Exporta la segmentacion a mascara labelmap con IDs del tissue_config.

Flujo:
  1. Cargar tissue_config.json → mapeo nombre_segmento → indice_phantom
  2. Fusionar segmentos (body + organos) en una sola labelmap 3D
  3. Verificar que NO haya solapamiento entre segmentos
  4. Asignar a cada voxel el indice del tissue_config
  5. Exportar como .nii (NIfTI) y .nrrd (NRRD)

Cada organo debe tener un numero UNICO que corresponde a su material MCNP.
Esto es ESENCIAL para el modulo 2 (generacion de input MCNP).
"""

import json
import logging
import os
import re

import numpy as np
from typing import Optional

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


# Mapeo por defecto de nombres de segmentos TS a indices de tissue_config
# Se complementa con ts_label_to_phantom del JSON cuando hay labels TS
DEFAULT_NAME_TO_PHANTOM = {
    # Higado (index 90)
    "liver": 90,
    "higado": 90,
    "higado_sano": 90,
    # Pulmon (index 50)
    "lung": 50,
    "superior lobe of left lung": 50,
    "inferior lobe of left lung": 50,
    "superior lobe of right lung": 50,
    "middle lobe of right lung": 50,
    "inferior lobe of right lung": 50,
    # Hueso (index 80)
    "bone": 80,
    "rib": 80,
    "vertebra": 80,
    "scapula": 80,
    "sternum": 80,
    "costal cartilage": 80,
    # Tumor (index 100)
    "tumor": 100,
    "Tumor_Sintetico": 100,
    # Pretumor (index 200)
    "pretumor": 200,
    "Pretumor": 200,
    # Body (Tejido_blando index 30)
    "body": 30,
    "trunk": 30,
}

# Palabras clave para identificar hueso en nombres de segmentos
BONE_KEYWORDS = ["rib", "vertebra", "scapula", "sternum", "bone", "costal"]


def _load_tissue_config(config_path: Optional[str] = None) -> dict:
    """Carga tissue_config.json y retorna el mapeo ts_label_to_phantom."""
    if config_path is None:
        # Buscar en recursos de SlicerDosim
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            # Desde Testing/PipelineOrchestrator/ -> SlicerDosim/Modules/Scripted/SlicerDosim/Resources/Config/
            os.path.join(script_dir, "..", "..",
                         "Modules", "Scripted", "SlicerDosim",
                         "Resources", "Config", "tissue_config.json"),
            # Full deployment path
            os.path.join(script_dir, "..", "..", "..",
                         "SlicerDosim", "Modules", "Scripted", "SlicerDosim",
                         "Resources", "Config", "tissue_config.json"),
        ]
        for p in candidates:
            norm = os.path.normpath(p)
            if os.path.exists(norm):
                config_path = norm
                break

    if not config_path or not os.path.exists(config_path):
        logger.warning(f"  tissue_config.json no encontrado. Usando defaults.")
        return {"ts_label_to_phantom": {}, "ts_body_labels": []}

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    logger.info(f"  tissue_config cargado desde: {config_path}")
    # Construir mapeo nombre → indice desde la lista de tissues
    tissues = config.get("tissues", [])
    name_to_idx = {}
    for t in tissues:
        name = t.get("name_en", "").lower().replace(" ", "_")
        name_to_idx[name] = t["index"]
        name_to_idx[t.get("name", "").lower().replace(" ", "_")] = t["index"]
    config["_name_to_idx"] = name_to_idx

    return config


def _build_segment_name_to_phantom(segmentation_node, tissue_config: dict) -> dict:
    """Construye mapeo: nombre_segmento → indice_phantom.

    Usa ts_label_to_phantom si el ID del segmento es un label TS numerico.
    Sino, usa DEFAULT_NAME_TO_PHANTOM por nombre.
    Segmentos no mapeados reciben indices 2-256 (reservando 1 para aire).
    """
    import vtk

    seg = segmentation_node.GetSegmentation()
    segment_ids = vtk.vtkStringArray()
    seg.GetSegmentIDs(segment_ids)

    ts_label_map = tissue_config.get("ts_label_to_phantom", {})
    name_to_idx = tissue_config.get("_name_to_idx", {})

    mapping = {}
    next_free_idx = 2  # Indices 2-256 para segmentos no tissue
    for i in range(segment_ids.GetNumberOfValues()):
        sid = segment_ids.GetValue(i)
        segment = seg.GetSegment(sid)
        if not segment:
            continue
        seg_name = segment.GetName()

        # Intentar por ID numerico (TS label)
        idx = None
        if sid.isdigit() and sid in ts_label_map:
            entry = ts_label_map[sid]
            idx = entry["index"] if isinstance(entry, dict) else entry

        if idx is None:
            idx = DEFAULT_NAME_TO_PHANTOM.get(seg_name, None)

        if idx is None:
            # Busqueda por coincidencia parcial en DEFAULT_NAME_TO_PHANTOM
            for key, val in DEFAULT_NAME_TO_PHANTOM.items():
                if key.lower() in seg_name.lower():
                    idx = val
                    break

        if idx is None:
            # Detectar hueso por palabras clave
            if any(kw in seg_name.lower() for kw in BONE_KEYWORDS):
                idx = 80

        if idx is None:
            # Asignar indice libre 2-256
            idx = next_free_idx
            next_free_idx += 1
            if next_free_idx > 256:
                logger.warning(f" Segmento '{seg_name}' asignado a indice {idx-1}, se agotaron indices 2-256")

        mapping[seg_name] = idx

    return mapping


def export_labelmap(
    segmentation_node,
    ct_node,
    body_segmentation_node=None,
    output_dir: str = None,
    tissue_config_path: str = None,
) -> dict:
    """
    Exporta la segmentacion completa a labelmap con indices de tissue_config.

    PASO CRITICO para modulo 2 (MCNP):
    - Cada organo tiene un numero UNICO = indice del tissue_config
    - Verifica que NO haya solapamiento entre organos
    - Exporta .nii (NIfTI) y .nrrd (NRRD)

    Args:
        segmentation_node: vtkMRMLSegmentationNode con organos (TS task='total')
        ct_node: vtkMRMLScalarVolumeNode del CT (referencia geometria)
        body_segmentation_node: opcional, vtkMRMLSegmentationNode con body (TS task='body')
        output_dir: directorio de salida para los archivos
        tissue_config_path: ruta al tissue_config.json

    Returns:
        dict con:
            "nifti_path": ruta al .nii
            "nrrd_path": ruta al .nrrd
            "num_segments": cantidad de segmentos procesados
            "overlap_voxels": cantidad de voxeles con solapamiento (0 = OK)
            "phantom_indices_used": lista de indices usados
    """
    import slicer
    import vtk

    logger.info("")
    logger.info("  ========================================================")
    logger.info("  Exportando labelmap con IDs de tissue_config")
    logger.info("  ========================================================")
    logger.info("")

    show_progress("Exportando labelmap dosimetrica...")

    if segmentation_node is None:
        raise RuntimeError("Nodo de segmentacion no disponible")

    if ct_node is None:
        raise RuntimeError("Nodo CT no disponible")

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "labelmaps")

    os.makedirs(output_dir, exist_ok=True)

    # --- 1. Cargar tissue_config ---
    tissue_config = _load_tissue_config(tissue_config_path)
    logger.info(f"  Directorio salida: {output_dir}")

    # --- 2. Construir mapeo nombre_segmento → indice_phantom ---
    mapping = _build_segment_name_to_phantom(segmentation_node, tissue_config)

    logger.info("  Mapeo segmento → indice phantom:")
    unique_indices = set()
    for seg_name, idx in sorted(mapping.items(), key=lambda x: x[1]):
        unique_indices.add(idx)
        logger.info(f"    {idx:3d} <- {seg_name}")

    logger.info(f"  Total segmentos: {len(mapping)}")
    logger.info(f"  Indices phantom unicos: {len(unique_indices)}: {sorted(unique_indices)}")

    # --- 3. Exportar cada segmento a labelmap individual ---
    logger.info("  Exportando segmentos a labelmap...")

    # Segmentos contenedor (baja prioridad, se restan de los organos)
    CONTAINER_NAMES = {"trunk", "body", "skin"}

    # Separar mapping en organos (alta prioridad) y contenedores (se restan)
    organ_mapping = {}
    container_mapping = {}
    for seg_name, idx in mapping.items():
        if seg_name in CONTAINER_NAMES:
            container_mapping[seg_name] = idx
        else:
            organ_mapping[seg_name] = idx

    if container_mapping:
        logger.info(f"  Segmentos contenedor (se restaran de organos): {list(container_mapping.keys())}")

    # Obtener dimensiones del CT para la labelmap final
    ct_dims = ct_node.GetImageData().GetDimensions()
    ct_spacing = ct_node.GetSpacing()

    # Crear labelmap acumuladora (inicialmente 0 = Aire, index 1)
    final_labelmap = np.zeros((ct_dims[2], ct_dims[1], ct_dims[0]), dtype=np.int16)

    # Acumulador binario: 1 = voxel ocupado por algun organo
    any_organ = np.zeros((ct_dims[2], ct_dims[1], ct_dims[0]), dtype=bool)

    errors = []
    export_count = 0
    overlap_voxels = 0

    # --- Fase A: Extraer mascaras de organos y validar que sean disjuntas ---
    organ_masks = {}
    for seg_name, phantom_idx in organ_mapping.items():
        try:
            mask = _extract_single_segment_mask(segmentation_node, seg_name, ct_node)
            if mask is not None:
                organ_masks[seg_name] = mask
        except Exception as e:
            errors.append(f"  Error extrayendo '{seg_name}': {e}")
            logger.warning(f"  Error en segmento '{seg_name}': {e}")

    if organ_masks:
        accumulated = np.zeros_like(next(iter(organ_masks.values())), dtype=np.uint8)
        for seg_name, mask in organ_masks.items():
            already_set = accumulated[mask > 0]
            n = int((already_set > 0).sum())
            if n > 0:
                logger.warning(f"  OVERLAP: '{seg_name}' solapa con otros organos: {n} voxeles")
                overlap_voxels += n
            accumulated[mask > 0] += 1

        n_total = int((accumulated > 1).sum())
        if n_total:
            logger.warning(f"  Total overlap entre organos: {n_total} voxeles")
        else:
            logger.info("  Organos disjuntos — sin overlap entre ellos")

    # --- Fase B: Asignar organos a la labelmap ---
    for seg_name, mask in organ_masks.items():
        phantom_idx = organ_mapping[seg_name]
        final_labelmap[mask > 0] = phantom_idx
        any_organ[mask > 0] = True
        export_count += 1

    # --- Fase C: Procesar contenedores con resta explicita (AND-NOT) ---
    for seg_name, phantom_idx in container_mapping.items():
        try:
            mask = _extract_single_segment_mask(segmentation_node, seg_name, ct_node)
            if mask is None:
                logger.warning(f"  Contenedor '{seg_name}' no se pudo extraer")
                continue
            container_only = (mask > 0) & ~any_organ
            n = int(container_only.sum())
            if n > 0:
                final_labelmap[container_only] = phantom_idx
                logger.info(f"  '{seg_name}' asignado: {n} voxeles (restados {int(mask.sum()) - n} de organos)")
            else:
                logger.warning(f"  '{seg_name}' completamente contenido en organos — 0 voxeles nuevos")
        except Exception as e:
            errors.append(f"  Error procesando contenedor '{seg_name}': {e}")
            logger.warning(f"  Error en contenedor '{seg_name}': {e}")

    # --- 4. Incorporar body segmentation si existe ---
    body_mask = None
    if body_segmentation_node is not None:
        logger.info("  Incorporando body segmentation...")
        try:
            body_mask = _extract_single_segment_mask(
                body_segmentation_node, None, ct_node,
                first_segment=True
            )
            if body_mask is not None:
                body_idx = 30  # Tejido_blando
                # Body = contorno corporal MENOS organos (resta EXPLICITA)
                # Usa any_organ, no final_labelmap == 0
                body_region = (body_mask > 0) & ~any_organ
                final_labelmap[body_region] = body_idx
                logger.info(f"  Body incorporado: {int(body_region.sum())} voxeles nuevos")
        except Exception as e:
            logger.warning(f"  Error incorporando body: {e}")

    # --- 5. Verificar solapamiento final ---
    logger.info("")
    logger.info("  Verificando integridad de la labelmap...")

    unique_values = set(np.unique(final_labelmap))
    logger.info(f"  Valores unicos en labelmap: {sorted(unique_values)}")

    if overlap_voxels > 0:
        logger.warning(f"  OVERLAP DETECTADO entre organos: {overlap_voxels} voxeles en conflicto")
        logger.warning("  Los contenedores (trunk/body/skin) se restaron correctamente via AND-NOT")
    else:
        logger.info("  [OK] Sin solapamiento entre segmentos")

    # Verificar que no haya voxeles sin asignar dentro del body
    if body_mask is not None:
        unassigned_inside_body = (body_mask > 0) & ~any_organ & (final_labelmap == 0)
        if unassigned_inside_body.sum() > 0:
            logger.warning(f"  {int(unassigned_inside_body.sum())} voxeles dentro del body sin asignar, asignando como Tejido_blando")
            final_labelmap[unassigned_inside_body] = 30  # Default Tejido_blando — NO sobrescribir organos

    # --- 6. Crear nodo labelmap en Slicer ---
    logger.info("  Creando nodo labelmap en Slicer...")
    labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode", "3Dosim_Labelmap"
    )
    labelmap_node.SetOrigin(ct_node.GetOrigin())
    labelmap_node.SetSpacing(ct_node.GetSpacing())
    ijk_to_ras = vtk.vtkMatrix4x4()
    ct_node.GetIJKToRASMatrix(ijk_to_ras)
    labelmap_node.SetIJKToRASMatrix(ijk_to_ras)

    slicer.util.updateVolumeFromArray(labelmap_node, final_labelmap)

    # --- 7. Exportar NIfTI ---
    nifti_path = os.path.join(output_dir, "3Dosim_labelmap.nii")
    logger.info(f"  Exportando NIfTI: {nifti_path}")
    try:
        success = slicer.util.saveNode(labelmap_node, nifti_path)
        if success:
            logger.info(f"  NIfTI guardado OK")
        else:
            logger.warning(f"  saveNode NIfTI devolvio False")
    except Exception as e:
        logger.warning(f"  Error exportando NIfTI: {e}")
        # Fallback: exportar con numpy
        try:
            _export_nifti_fallback(final_labelmap, ct_node, nifti_path)
        except Exception as e2:
            logger.warning(f"  Fallback NIfTI tambien fallo: {e2}")
            nifti_path = None

    # --- 8. Exportar NRRD ---
    nrrd_path = os.path.join(output_dir, "3Dosim_labelmap.nrrd")
    logger.info(f"  Exportando NRRD: {nrrd_path}")
    try:
        success = slicer.util.saveNode(labelmap_node, nrrd_path)
        if success:
            logger.info(f"  NRRD guardado OK")
        else:
            logger.warning(f"  saveNode NRRD devolvio False")
    except Exception as e:
        logger.warning(f"  Error exportando NRRD: {e}")
        nrrd_path = None

    # El nodo permanece en la escena para que el usuario pueda verlo en Data
    labelmap_node.SetName("3Dosim_Labelmap")

    # --- 9. Resumen ---
    logger.info("")
    logger.info("  ========================================================")
    logger.info("  LABELMAP EXPORTADA — visible en Data module como '3Dosim_Labelmap'")
    logger.info(f"    Segmentos procesados: {export_count}")
    logger.info(f"    Overlap voxels:       {overlap_voxels}")
    logger.info(f"    Indices usados:       {sorted(unique_values)}")
    logger.info(f"    NIfTI:               {nifti_path or 'FALLO'}")
    logger.info(f"    NRRD:                {nrrd_path or 'FALLO'}")
    logger.info("  ========================================================")

    show_progress("Labelmap dosimetrica exportada OK")

    for err in errors:
        logger.warning(err)

    return {
        "nifti_path": nifti_path,
        "nrrd_path": nrrd_path,
        "num_segments": export_count,
        "overlap_voxels": int(overlap_voxels),
        "phantom_indices_used": sorted(int(v) for v in unique_values if v > 0),
        "errors": errors,
    }


def _extract_single_segment_mask(
    segmentation_node,
    segment_name: Optional[str],
    ref_volume_node,
    first_segment: bool = False,
) -> Optional[np.ndarray]:
    """Extrae un segmento individual como numpy array binario."""
    import slicer
    import vtk

    if segment_name is not None:
        # Buscar segmento por nombre
        seg = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        seg.GetSegmentIDs(segment_ids)

        found_id = None
        for i in range(segment_ids.GetNumberOfValues()):
            sid = segment_ids.GetValue(i)
            segment = seg.GetSegment(sid)
            if segment and segment.GetName() == segment_name:
                found_id = sid
                break

        if found_id is None:
            return None

        ids_to_export = vtk.vtkStringArray()
        ids_to_export.InsertNextValue(found_id)
    elif first_segment:
        # Exportar el primer segmento disponible
        seg = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        seg.GetSegmentIDs(segment_ids)
        if segment_ids.GetNumberOfValues() == 0:
            return None
        ids_to_export = vtk.vtkStringArray()
        ids_to_export.InsertNextValue(segment_ids.GetValue(0))
    else:
        return None

    labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode", "__temp_seg_export__"
    )

    try:
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            segmentation_node, ids_to_export, labelmap_node, ref_volume_node
        )
        array = slicer.util.arrayFromVolume(labelmap_node)
        result = (array > 0).astype(np.uint8)
        slicer.mrmlScene.RemoveNode(labelmap_node)
        return result
    except Exception as e:
        slicer.mrmlScene.RemoveNode(labelmap_node)
        raise


def _export_nifti_fallback(array: np.ndarray, ref_node, filepath: str):
    """Fallback para exportar NIfTI usando nibabel si slicer.util.saveNode falla."""
    import nibabel as nib

    spacing = ref_node.GetSpacing()
    origin = ref_node.GetOrigin()

    affine = np.eye(4)
    affine[0, 0] = -spacing[0]
    affine[1, 1] = -spacing[1]
    affine[2, 2] = spacing[2]
    affine[0, 3] = origin[0]
    affine[1, 3] = origin[1]
    affine[2, 3] = origin[2]

    img = nib.Nifti1Image(array.astype(np.int16), affine)
    nib.save(img, filepath)
    logger.info(f"  NIfTI exportado via nibabel: {filepath}")
