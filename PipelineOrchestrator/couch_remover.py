"""
Eliminacion de camilla (mesa de exploracion) y aire exterior del CT.

Algoritmo:
  1. Threshold CT > -200 HU para crear mascara corporal
  2. Cierre morfologico (dilate + erode) para rellenar huecos
  3. Componente conectada mas grande -> cuerpo del paciente
  4. En cada corte axial, eliminar la camilla
  5. Aplicar mascara refinada al volumen
"""

import logging
import numpy as np

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


def remove_couch_and_air(ct_node):
    """
    Elimina la camilla y el aire exterior del volumen CT.
    NO modifica el nodo CT original. Crea un NUEVO nodo 'CT_sin_camilla'
    con la mascara aplicada, dejando el CT original intacto para TotalSegmentator.

    Returns:
        vtkMRMLScalarVolumeNode: el nuevo nodo con la mascara aplicada,
        o None si no se pudo crear.
    """
    from vtk.util import numpy_support
    import vtk

    logger.info("  Eliminando camilla y aire del volumen CT...")
    show_progress("Eliminando camilla y aire...")

    ct_img = ct_node.GetImageData()
    dims = ct_img.GetDimensions()

    ct_array_vtk = ct_img.GetPointData().GetScalars()
    ct_np = numpy_support.vtk_to_numpy(ct_array_vtk).reshape(dims[2], dims[1], dims[0])

    logger.info(f"  CT array: {dims[0]}x{dims[1]}x{dims[2]}")

    # Paso 1: Threshold para mascara corporal (HU > -200)
    body_mask = (ct_np > -200).astype(np.uint8)

    # Paso 2: Cierre morfologico 3D
    show_progress("Aplicando cierre morfologico...")
    try:
        from scipy.ndimage import binary_closing
        struct = np.ones((3, 3, 3), dtype=bool)
        body_mask = binary_closing(body_mask, structure=struct, iterations=3).astype(np.uint8)
    except ImportError:
        logger.info("  scipy no disponible, omitiendo cierre morfologico")

    # Paso 3: Componente conectada mas grande por slice
    show_progress("Identificando cuerpo del paciente...")
    z_range = np.where(body_mask.sum(axis=(1, 2)) > 0)[0]
    if len(z_range) == 0:
        logger.warning("  No se detecto cuerpo del paciente, saltando")
        return None
    z_min, z_max = z_range[0], z_range[-1]

    for z in range(z_min, z_max + 1):
        slice_2d = body_mask[z, :, :]
        labeled, n_features = _label_connected_components_2d(slice_2d)
        if n_features < 1:
            continue
        sizes = np.bincount(labeled.ravel())
        if len(sizes) > 1:
            largest = np.argmax(sizes[1:]) + 1
            body_mask[z, :, :] = (labeled == largest).astype(np.uint8)

    logger.info(f"  Cuerpo detectado: slices {z_min}-{z_max}")

    # Paso 4: Eliminar camilla
    show_progress("Eliminando camilla...")
    for z in range(z_min, z_max + 1):
        slice_2d = body_mask[z, :, :].copy()
        rows_with_body = np.where(slice_2d.sum(axis=1) > 0)[0]
        if len(rows_with_body) == 0:
            continue
        bottom_row = rows_with_body[-1]
        if bottom_row < dims[1] - 3:
            body_mask[z, bottom_row + 1:, :] = 0
        cols_with_body = np.where(slice_2d.sum(axis=0) > 0)[0]
        if len(cols_with_body) > 0:
            left, right = cols_with_body[0], cols_with_body[-1]
            if left > 5:
                body_mask[z, :, :left - 2] = 0
            if right < dims[0] - 5:
                body_mask[z, :, right + 3:] = 0

    # Paso 5: Aplicar mascara al CT (sobre copia, NO modificar original)
    show_progress("Aplicando mascara al volumen...")
    ct_masked = ct_np.copy()
    ct_masked[body_mask == 0] = -1024

    ct_masked_flat = ct_masked.ravel().astype(np.int16)
    vtk_arr = numpy_support.numpy_to_vtk(ct_masked_flat, deep=True)

    # Crear nuevo vtkImageData para el nodo mascara
    new_img = vtk.vtkImageData()
    new_img.SetDimensions(dims)
    new_img.SetSpacing(ct_img.GetSpacing())
    new_img.SetOrigin(ct_img.GetOrigin())
    # Copiar direccion IJK To RAS si existe
    direction_matrix = ct_img.GetDirectionMatrix()
    if direction_matrix:
        new_img.SetDirectionMatrix(direction_matrix)
    new_img.GetPointData().SetScalars(vtk_arr)

    # Crear nuevo nodo en Slicer
    import slicer
    masked_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    masked_node.SetName("CT_sin_camilla")
    masked_node.SetAndObserveImageData(new_img)
    # Copiar transformacion espacial del CT original
    ijk_to_ras = vtk.vtkMatrix4x4()
    ct_node.GetIJKToRASMatrix(ijk_to_ras)
    masked_node.SetIJKToRASMatrix(ijk_to_ras)

    # Crear display node para que se vea en las vistas
    from slicer import vtkMRMLScalarVolumeDisplayNode
    dn = vtkMRMLScalarVolumeDisplayNode()
    slicer.mrmlScene.AddNode(dn)
    dn.SetDefaultColorMap()
    masked_node.SetAndObserveDisplayNodeID(dn.GetID())

    body_voxels = body_mask.sum()
    total_voxels = body_mask.size
    logger.info(f"  Camilla y aire eliminados")
    logger.info(f"  Voxels cuerpo: {body_voxels} / {total_voxels} "
                f"({100 * body_voxels / total_voxels:.1f}%)")
    logger.info(f"  Nodo original '{ct_node.GetName()}' intacto para TotalSegmentator")
    logger.info(f"  Nodo mascara creado: 'CT_sin_camilla'")

    return masked_node


def _label_connected_components_2d(binary_img):
    """Etiqueta componentes conectadas 2D (4-conectado)."""
    try:
        from scipy.ndimage import label
        return label(binary_img, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    except ImportError:
        labeled = np.zeros_like(binary_img, dtype=np.int32)
        label_count = 0
        for y in range(binary_img.shape[0]):
            for x in range(binary_img.shape[1]):
                if binary_img[y, x] and labeled[y, x] == 0:
                    label_count += 1
                    _flood_fill(binary_img, labeled, x, y, label_count)
        return labeled, label_count


def _flood_fill(binary, labeled, x0, y0, label_val):
    """Flood fill iterativo."""
    h, w = binary.shape
    stack = [(x0, y0)]
    while stack:
        x, y = stack.pop()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        if not binary[y, x] or labeled[y, x] != 0:
            continue
        labeled[y, x] = label_val
        stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
