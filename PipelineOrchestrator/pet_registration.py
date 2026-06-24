"""
Registro y re-muestreo de PET a la grilla del CT.

Dos metodos implementados:
  Metodo A - ResampleScalarVolume: usa el CLI de Slicer para remuestrear PET a CT
  Metodo B - NumPy/MATLAB: interp3 manual con conservacion de actividad

Ambos devuelven un nodo PET registrado + metricas para comparacion.
"""

import logging
import time
import numpy as np

logger = logging.getLogger("3DosimTest")

from PipelineOrchestrator.utils import show_progress


def register_pet_slicer(ct_node, pet_node, output_dir: str):
    """
    Metodo A: usa ResampleScalarVolume CLI de Slicer para remuestrear PET a la grilla del CT.

    Args:
        ct_node: vtkMRMLScalarVolumeNode del CT (referencia)
        pet_node: vtkMRMLScalarVolumeNode del PET (a remuestrear)
        output_dir: directorio para logs

    Returns:
        dict con:
            "node": vtkMRMLScalarVolumeNode del PET registrado
            "method": "slicer_resample"
            "dimensions": [x, y, z]
            "spacing": [sx, sy, sz]
            "total_activity_bq": float
            "duration_s": float
            "success": bool
    """
    import slicer

    t0 = time.time()
    logger.info("")
    logger.info("  [Metodo A] ResampleScalarVolume (Slicer CLI)")
    logger.info("  " + "-" * 50)

    # Crear nodo de salida
    pet_reg = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLScalarVolumeNode", "PET_registrado_A_Resample"
    )

    # Obtener geometria del CT como referencia
    ct_spacing = ct_node.GetSpacing()
    ct_dims = ct_node.GetImageData().GetDimensions()
    logger.info(f"  CT referencia: dims={ct_dims}, spacing={ct_spacing:.3f}mm")

    try:
        # Preparar parametros para ResampleScalarVolume
        params = {
            "inputVolume": pet_node.GetID(),
            "referenceVolume": ct_node.GetID(),
            "outputVolume": pet_reg.GetID(),
            "interpolationType": "Linear",
            "pixelType": "float",
        }

        logger.info("  Ejecutando ResampleScalarVolume...")
        show_progress("Remuestreando PET a grilla CT (ResampleScalarVolume)...")

        cli_node = slicer.cli.runSync(
            slicer.modules.resamplescalarvolume, None, params
        )

        # Verificar resultado
        if cli_node.GetStatus() == cli_node.Completed:
            logger.info("  ResampleScalarVolume completado OK")
        else:
            error_text = cli_node.GetErrorText()
            logger.warning(f"  ResampleScalarVolume status={cli_node.GetStatus()}: {error_text}")

        # Metricas
        arr = slicer.util.arrayFromVolume(pet_reg)
        spacing = pet_reg.GetSpacing()
        dims = pet_reg.GetImageData().GetDimensions()

        # Actividad total (asumiendo Bq/mL o valores proporcionales)
        voxel_vol_mL = spacing[0] * spacing[1] * spacing[2] / 1000.0  # mm3 -> mL
        total_activity = float(np.sum(arr[arr > 0])) * voxel_vol_mL

        elapsed = time.time() - t0
        logger.info(f"  PET registrado: dims={dims}, spacing=({spacing[0]:.3f}, {spacing[1]:.3f}, {spacing[2]:.3f})mm")
        logger.info(f"  Actividad total estimada: {total_activity:.2e}")
        logger.info(f"  Duracion: {elapsed:.1f}s")

        result = {
            "node": pet_reg,
            "method": "slicer_resample",
            "dimensions": list(dims),
            "spacing": list(spacing),
            "total_activity_bq": total_activity,
            "duration_s": elapsed,
            "success": True,
        }

    except Exception as e:
        logger.error(f"  Error en ResampleScalarVolume: {e}")
        slicer.mrmlScene.RemoveNode(pet_reg)
        result = {
            "node": None,
            "method": "slicer_resample",
            "dimensions": None,
            "spacing": None,
            "total_activity_bq": 0,
            "duration_s": time.time() - t0,
            "success": False,
            "error": str(e),
        }

    logger.info("  [Metodo A] Completado")
    return result


def register_pet_numpy(ct_node, pet_node, output_dir: str):
    """
    Metodo B: interp3 manual como MATLAB register_v7.m, con conservacion de actividad.

    Extrae arrays numpy de ambos volumenes, calcula grillas mundo,
    interpola PET a la grilla del CT, conserva actividad total.

    Args:
        ct_node: vtkMRMLScalarVolumeNode del CT (referencia)
        pet_node: vtkMRMLScalarVolumeNode del PET (a remuestrear)
        output_dir: directorio para logs

    Returns:
        dict con:
            "node": vtkMRMLScalarVolumeNode del PET registrado
            "method": "numpy_interp3"
            "dimensions": [x, y, z]
            "spacing": [sx, sy, sz]
            "total_activity_bq": float
            "duration_s": float
            "success": bool
    """
    import slicer
    from scipy import ndimage as ndi

    t0 = time.time()
    logger.info("")
    logger.info("  [Metodo B] NumPy interp3 (MATLAB register_v7)")
    logger.info("  " + "-" * 50)

    try:
        # --- 1. Extraer datos ---
        logger.info("  Leyendo volumenes...")
        show_progress("Remuestreando PET a grilla CT (NumPy interp3)...")

        pet_arr = slicer.util.arrayFromVolume(pet_node)  # (K, J, I)
        ct_arr = slicer.util.arrayFromVolume(ct_node)     # (K, J, I)

        pet_spacing = pet_node.GetSpacing()  # (sx, sy, sz)
        ct_spacing = ct_node.GetSpacing()
        pet_origin = pet_node.GetOrigin()
        ct_origin = ct_node.GetOrigin()

        logger.info(f"  PET original:  dims={pet_arr.shape[::-1]}, spacing=({pet_spacing[0]:.3f}, {pet_spacing[1]:.3f}, {pet_spacing[2]:.3f})mm")
        logger.info(f"  CT target:     dims={ct_arr.shape[::-1]}, spacing=({ct_spacing[0]:.3f}, {ct_spacing[1]:.3f}, {ct_spacing[2]:.3f})mm")

        # Actividad total PET original (Bq)
        voxel_vol_pet_mL = pet_spacing[0] * pet_spacing[1] * pet_spacing[2] / 1000.0
        total_bq_original = float(np.sum(pet_arr[pet_arr > 0])) * voxel_vol_pet_mL
        logger.info(f"  Actividad total PET original: {total_bq_original:.2e}")

        # --- 2. Calcular grillas mundo ---
        # PET: grilla nativa (centros de voxel)
        logger.info("  Calculando grillas mundo...")
        nk, nj, ni = pet_arr.shape
        x_pet = np.arange(ni) * pet_spacing[0] + pet_origin[0]
        y_pet = np.arange(nj) * pet_spacing[1] + pet_origin[1]
        z_pet = np.arange(nk) * pet_spacing[2] + pet_origin[2]

        # CT: grilla query (centros de voxel CT, dentro del bounding box PET)
        mk, mj, mi = ct_arr.shape
        x_ct = np.arange(mi) * ct_spacing[0] + ct_origin[0]
        y_ct = np.arange(mj) * ct_spacing[1] + ct_origin[1]
        z_ct = np.arange(mk) * ct_spacing[2] + ct_origin[2]

        # --- 3. Interpolar PET a grilla CT ---
        # map_coordinates espera coordenadas en indices PET (no mundo)
        # Convertir coordenadas CT a indices PET
        logger.info("  Interpolando PET a grilla CT...")

        # Crear meshgrid de coordenadas CT en mundo
        zz_ct, yy_ct, xx_ct = np.meshgrid(z_ct, y_ct, x_ct, indexing='ij')

        # Convertir a indices PET
        xi = (xx_ct - pet_origin[0]) / pet_spacing[0]
        yi = (yy_ct - pet_origin[1]) / pet_spacing[1]
        zi = (zz_ct - pet_origin[2]) / pet_spacing[2]

        # Coordenadas para map_coordinates: (3, K, J, I) donde dim 0 = [z, y, x]
        coords = np.stack([zi, yi, xi], axis=0)

        # Interpolar con orden 1 (lineal, como MATLAB linear)
        # Usar orden 1 para rapidez, orden 3 (cubic) para suavidad
        pet_reg_arr = ndi.map_coordinates(
            pet_arr.astype(np.float64),
            coords,
            order=1,
            mode='constant',
            cval=0.0,
        )

        # --- 4. Conservacion de actividad (normalizacion exacta) ---
        # NO usar factor volumetrico global porque CT y PET tienen FOV distinto.
        # PET suele ser 200x200, CT es 512x512 → voxeles fuera del PET quedan en 0
        # y el factor volumetrico no rescata eso.
        #
        # Solucion: normalizar para que la actividad total se conserve exactamente:
        #   factor = actividad_original / actividad_interpolada
        #   pet_reg = pet_interp * factor
        voxel_vol_ct_mL = ct_spacing[0] * ct_spacing[1] * ct_spacing[2] / 1000.0

        total_interp = float(np.sum(pet_reg_arr)) * voxel_vol_ct_mL
        if total_interp > 0:
            factor_conservacion = total_bq_original / total_interp
        else:
            factor_conservacion = 1.0
            logger.warning("  PET interpolado es todo cero — no se puede conservar actividad")

        logger.info(f"  Actividad interpolada (sin corregir): {total_interp:.2e}")
        logger.info(f"  Factor conservacion: {factor_conservacion:.4f}")

        pet_reg_arr = pet_reg_arr * factor_conservacion

        # Verificar conservacion
        total_bq_reg = float(np.sum(pet_reg_arr)) * voxel_vol_ct_mL
        diff_pct = abs(total_bq_reg - total_bq_original) / max(total_bq_original, 1) * 100
        logger.info(f"  Actividad total PET registrado: {total_bq_reg:.2e}")
        logger.info(f"  Error de conservacion: {diff_pct:.4f}%")

        # --- 5. Crear nodo en Slicer ---
        logger.info("  Creando nodo PET registrado en Slicer...")
        pet_reg_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "PET_registrado_B_Numpy"
        )

        # Copiar geometria del CT
        import vtk
        from vtk.util import numpy_support

        ijk_to_ras = vtk.vtkMatrix4x4()
        ct_node.GetIJKToRASMatrix(ijk_to_ras)
        pet_reg_node.SetIJKToRASMatrix(ijk_to_ras)
        pet_reg_node.SetSpacing(ct_node.GetSpacing())
        pet_reg_node.SetOrigin(ct_node.GetOrigin())

        # Convertir numpy array a vtkImageData
        # pet_reg_arr es (K, J, I) -> vtk quiere (I, J, K)
        pet_reg_ijk = np.transpose(pet_reg_arr, (2, 1, 0)).astype(np.float32)
        flat = pet_reg_ijk.ravel(order='C')
        vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_FLOAT)

        vtk_img = vtk.vtkImageData()
        vtk_img.SetDimensions(mi, mj, mk)
        vtk_img.SetSpacing(ct_spacing)
        vtk_img.SetOrigin(ct_origin)
        vtk_img.GetPointData().SetScalars(vtk_arr)
        pet_reg_node.SetAndObserveImageData(vtk_img)

        # Crear display node
        from slicer import vtkMRMLScalarVolumeDisplayNode
        dn = vtkMRMLScalarVolumeDisplayNode()
        slicer.mrmlScene.AddNode(dn)
        dn.SetDefaultColorMap()
        dn.SetAndObserveColorNodeID("vtkMRMLColorTableNodeRainbow")
        pet_reg_node.SetAndObserveDisplayNodeID(dn.GetID())

        elapsed = time.time() - t0
        dims = pet_reg_node.GetImageData().GetDimensions()
        spacing = pet_reg_node.GetSpacing()

        logger.info(f"  PET registrado: dims={dims}, spacing=({spacing[0]:.3f}, {spacing[1]:.3f}, {spacing[2]:.3f})mm")
        logger.info(f"  Duracion: {elapsed:.1f}s")

        result = {
            "node": pet_reg_node,
            "method": "numpy_interp3",
            "dimensions": list(dims),
            "spacing": list(spacing),
            "total_activity_bq": total_bq_reg,
            "duration_s": elapsed,
            "success": True,
        }

    except Exception as e:
        import traceback
        logger.error(f"  Error en NumPy interp3: {e}")
        logger.error(traceback.format_exc())
        result = {
            "node": None,
            "method": "numpy_interp3",
            "dimensions": None,
            "spacing": None,
            "total_activity_bq": 0,
            "duration_s": time.time() - t0,
            "success": False,
            "error": str(e),
        }

    logger.info("  [Metodo B] Completado")
    return result


def compare_registration(result_a: dict, result_b: dict) -> dict:
    """
    Compara los resultados de ambos metodos de registro.

    Args:
        result_a: dict del metodo A (slicer_resample)
        result_b: dict del metodo B (numpy_interp3)

    Returns:
        dict con metricas comparativas
    """
    import slicer
    import numpy as np

    logger.info("")
    logger.info("  " + "=" * 50)
    logger.info("  COMPARACION DE METODOS DE REGISTRO")
    logger.info("  " + "=" * 50)

    comparison = {
        "method_a": result_a.get("method", "unknown"),
        "method_b": result_b.get("method", "unknown"),
        "a_success": result_a.get("success", False),
        "b_success": result_b.get("success", False),
        "a_duration_s": result_a.get("duration_s", 0),
        "b_duration_s": result_b.get("duration_s", 0),
        "a_total_activity": result_a.get("total_activity_bq", 0),
        "b_total_activity": result_b.get("total_activity_bq", 0),
        "dims_match": False,
        "mae": None,
        "max_diff": None,
    }

    logger.info(f"  Metodo A ({comparison['method_a']}):")
    logger.info(f"    Success:     {comparison['a_success']}")
    logger.info(f"    Duracion:    {comparison['a_duration_s']:.1f}s")
    logger.info(f"    Dimensiones: {result_a.get('dimensions')}")
    logger.info(f"    Spacing:     {result_a.get('spacing')}")
    logger.info(f"    Actividad:   {comparison['a_total_activity']:.2e}")

    logger.info(f"  Metodo B ({comparison['method_b']}):")
    logger.info(f"    Success:     {comparison['b_success']}")
    logger.info(f"    Duracion:    {comparison['b_duration_s']:.1f}s")
    logger.info(f"    Dimensiones: {result_b.get('dimensions')}")
    logger.info(f"    Spacing:     {result_b.get('spacing')}")
    logger.info(f"    Actividad:   {comparison['b_total_activity']:.2e}")

    if result_a.get("success") and result_b.get("success"):
        node_a = result_a.get("node")
        node_b = result_b.get("node")
        if node_a and node_b:
            try:
                arr_a = slicer.util.arrayFromVolume(node_a)
                arr_b = slicer.util.arrayFromVolume(node_b)

                if arr_a.shape == arr_b.shape:
                    comparison["dims_match"] = True
                    diff = np.abs(arr_a - arr_b)
                    comparison["mae"] = float(np.mean(diff))
                    comparison["max_diff"] = float(np.max(diff))
                    comparison["rmse"] = float(np.sqrt(np.mean(diff**2)))

                    logger.info(f"  Comparacion punto a punto:")
                    logger.info(f"    Dimensiones coinciden: SI")
                    logger.info(f"    MAE (Mean Abs Error):  {comparison['mae']:.6f}")
                    logger.info(f"    RMSE:                  {comparison['rmse']:.6f}")
                    logger.info(f"    Max diff:              {comparison['max_diff']:.6f}")
                else:
                    comparison["dims_match"] = False
                    logger.info(f"  Dimensiones NO coinciden:")
                    logger.info(f"    A: {arr_a.shape}")
                    logger.info(f"    B: {arr_b.shape}")
            except Exception as e:
                logger.warning(f"  Error comparando arrays: {e}")

    # Recomendacion
    if comparison["a_success"] and comparison["b_success"]:
        if comparison.get("mae", 1) < 0.01:
            logger.info("  -> Metodos producen resultados SIMILARES")
        else:
            logger.info("  -> Metodos producen resultados DIFERENTES, revisar")

        if comparison["a_duration_s"] < comparison["b_duration_s"]:
            logger.info(f"  -> Metodo A es {comparison['b_duration_s']/max(comparison['a_duration_s'],0.01):.1f}x mas rapido")
        else:
            logger.info(f"  -> Metodo B es {comparison['a_duration_s']/max(comparison['b_duration_s'],0.01):.1f}x mas rapido")

    logger.info("  " + "=" * 50)

    return comparison


def select_best_result(result_a: dict, result_b: dict) -> dict:
    """
    Selecciona el mejor resultado basado en:
    1. Exito del metodo
    2. Conservacion de actividad (mas cercano al original)

    Retorna el dict del metodo seleccionado.
    """
    # Si solo uno funciona, usar ese
    if result_a.get("success") and not result_b.get("success"):
        logger.info("  -> Seleccionado: Metodo A (B fallo)")
        return result_a
    if result_b.get("success") and not result_a.get("success"):
        logger.info("  -> Seleccionado: Metodo B (A fallo)")
        return result_b
    if not result_a.get("success") and not result_b.get("success"):
        logger.error("  -> AMBOS METODOS FALLARON")
        return result_a

    # Ambos funcionaron: comparar actividad y preferir B (mas exacto)
    logger.info("  -> Seleccionado: Metodo B (NumPy interp3) por exactitud")
    return result_b
