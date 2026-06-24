"""
Orquestador de segmentacion completa del phantom dosimetrico.

Pipeline:
  1. TotalSegmentator task="total" → cuerpo, higado, pulmones, huesos
  2. Mapeo de labels TS -> indices 3Dosim (1,30,50,80,90)
  3. TotalSegmentator task="liver_lesions" → tumores en CT (opcional)
  4. Fusion tumor en phantom -> indice 100
  5. Post-proceso: smoothing, filtro volumen minimo
  6. Estadisticas volumetricas
  7. Export NIfTI multicapa

Labels del phantom 3Dosim:
  - 1   = Aire (exterior)
  - 30  = Tejido blando
  - 50  = Pulmon
  - 80  = Hueso
  - 90  = Higado
  - 100 = Tumor
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from .config import TissueConfig


class PhantomSegmenter:
    """
    Orquestador del pipeline completo de segmentacion del phantom.

    Coordina:
      - TotalSegmentator task="total" (cuerpo completo)
      - TotalSegmentator task="liver_lesions" (tumores en CT)
      - Mapeo de labels a indices 3Dosim
      - Post-procesamiento
      - Export NIfTI
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = TissueConfig()

    # ======================================================================
    # PIPELINE COMPLETO
    # ======================================================================

    def segment_full_phantom(
        self,
        ct_volume_node,
        pet_volume_node=None,
        suv_threshold: float = 2.5,
        output_dir: Optional[str] = None,
        detect_tumors_auto: bool = True,
    ) -> dict:
        """
        Ejecuta el pipeline completo de segmentacion.

        Pasos:
          1. TotalSegmentator task="total" (cuerpo completo, 104 clases)
          2. Mapeo de labels TS -> phantom (1,30,50,80,90)
          3. TotalSegmentator task="liver_lesions" (tumores, opcional)
          4. Post-proceso: suavizado, filtrado
          5. Estadisticas volumetricas
          6. Export NIfTI (opcional)

        Args:
            ct_volume_node: vtkMRMLScalarVolumeNode del CT
            pet_volume_node: (opcional, reservado para futuro)
            suv_threshold: (reservado para futuro)
            output_dir: directorio para guardar resultados (opcional)
            detect_tumors_auto: si True, ejecuta liver_lesions de TS

        Returns:
            dict con:
              - 'segmentation_node': SegmentationNode del phantom
              - 'phantom_path': ruta al NIfTI exportado (si output_dir)
              - 'stats': dict con volumenes por tejido
              - 'liver_vol_ml', 'tumor_vol_ml': volumenes en ml
              - 'error': mensaje de error si falla
        """
        import slicer

        result = {
            "segmentation_node": None,
            "phantom_path": None,
            "stats": {},
            "liver_vol_ml": 0.0,
            "tumor_vol_ml": 0.0,
        }

        # --- Paso 1: TotalSegmentator task="total" ---
        self.logger.info("[1/4] TotalSegmentator task='total'...")
        ts_labelmap = self._run_totalsegmentator(ct_volume_node, task="total")
        if ts_labelmap is None:
            return {"error": "TotalSegmentator task='total' fallo. Verifique instalacion."}

        # --- Paso 2: Mapear TS -> phantom ---
        self.logger.info("[2/4] Mapeando labels TS a indices 3Dosim...")
        phantom_arr = self._map_ts_to_phantom(ts_labelmap)
        if phantom_arr is None:
            slicer.mrmlScene.RemoveNode(ts_labelmap)
            return {"error": "Fallo mapeo a phantom."}

        # Limpiar labelmap temporal
        slicer.mrmlScene.RemoveNode(ts_labelmap)

        # --- Paso 3: Detectar tumores (opcional) ---
        tumor_arr = None
        if detect_tumors_auto:
            self.logger.info("[3/4] TotalSegmentator task='liver_lesions'...")
            tumor_arr = self._detect_liver_lesions(ct_volume_node, phantom_arr)
            if tumor_arr is not None:
                n_tumor_voxels = int(tumor_arr.sum())
                self.logger.info(f"  Lesiones detectadas: {n_tumor_voxels} voxeles")
            else:
                self.logger.info("  No se detectaron lesiones o no hay soporte.")
        else:
            self.logger.info("[3/4] Deteccion automatica de tumores omitida.")

        # --- Paso 4: Post-procesar y crear segmentation node ---
        self.logger.info("[4/4] Ensamblando phantom...")
        seg_node = self._create_phantom_segmentation(
            phantom_arr, ct_volume_node, tumor_arr
        )
        if seg_node is None:
            return {"error": "Fallo al crear nodo de segmentacion."}

        result["segmentation_node"] = seg_node

        # Estadisticas
        result["stats"] = self._compute_phantom_stats(seg_node)
        result["liver_vol_ml"] = result["stats"].get("liver_vol_ml", 0.0)
        result["tumor_vol_ml"] = result["stats"].get("tumor_vol_ml", 0.0)

        # Export NIfTI
        if output_dir:
            phantom_path = self._export_phantom_to_nifti(
                seg_node, ct_volume_node, output_dir
            )
            result["phantom_path"] = phantom_path

        self.logger.info("Pipeline de segmentacion completado.")
        return result

    # ======================================================================
    # TOTALSEGMENTATOR
    # ======================================================================

    def _run_totalsegmentator(
        self, ct_volume_node, task: str = "total"
    ) -> Optional[object]:
        """
        Ejecuta TotalSegmentator y devuelve un labelmap node.

        Args:
            ct_volume_node: volumen CT de entrada
            task: tarea de TS ("total", "liver_lesions", etc.)

        Returns:
            vtkMRMLLabelMapVolumeNode con la segmentacion, o None si falla
        """
        import slicer

        try:
            from totalsegmentator.python_api import totalsegmentator
        except ImportError:
            self.logger.error(
                "TotalSegmentator no instalado. "
                "Menu: Extension Manager -> TotalSegmentator -> Install"
            )
            return None

        try:
            # 1. Guardar CT como NIfTI temporal
            tmp_dir = tempfile.mkdtemp()
            ct_path = os.path.join(tmp_dir, "input_ct.nii.gz")
            slicer.util.saveNode(ct_volume_node, ct_path)

            # 2. Directorio de salida
            output_dir = os.path.join(tmp_dir, f"ts_{task}")

            # 3. Ejecutar TotalSegmentator
            self.logger.info(f"  Ejecutando TS task='{task}'...")
            slicer.util.showStatusMessage(
                f"TotalSegmentator: {task}...", 30000
            )

            # Determinar roi_subset segun tarea
            roi_subset = None
            if task == "liver_lesions":
                roi_subset = ["liver"]

            totalsegmentator(
                input=ct_path,
                output=output_dir,
                ml=True,
                task=task,
                fast=True,
                roi_subset=roi_subset,
            )

            # 4. Cargar resultado
            result_node = self._load_ts_output(output_dir, task)

            # 5. Limpiar temporales
            try:
                import shutil
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

            return result_node

        except Exception as e:
            self.logger.error(f"Error en TotalSegmentator ({task}): {e}")
            return None

    def _load_ts_output(self, output_dir: str, task: str) -> Optional[object]:
        """
        Carga el output de TotalSegmentator.

        TS v2 produce un unico NIfTI multi-label (task="total")
        o NIfTI individual por estructura (tareas especializadas).

        Returns:
            vtkMRMLLabelMapVolumeNode, o None si falla
        """
        import slicer
        import glob

        # Buscar archivos NIfTI
        nifti_files = glob.glob(os.path.join(output_dir, "*.nii.gz"))
        if not nifti_files:
            nifti_files = glob.glob(os.path.join(output_dir, "*.nii"))

        if not nifti_files:
            self.logger.error("TotalSegmentator no produjo archivos de salida.")
            return None

        if len(nifti_files) == 1:
            # TS v2: un solo archivo multi-label
            node = slicer.util.loadNodeFromFile(nifti_files[0], "NiftiFile")
            if node is None:
                return None
            # Convertir a labelmap (forzar tipo entero)
            labelmap = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", f"TS_{task}_labelmap"
            )
            labelmap.CopyOrientation(node)
            labelmap.SetSpacing(node.GetSpacing())
            labelmap.SetOrigin(node.GetOrigin())
            # Copiar datos de imagen
            labelmap.SetImageData(node.GetImageData())
            slicer.mrmlScene.RemoveNode(node)
            return labelmap

        else:
            # TS v1: multiples archivos individuales
            # Combinar en un solo labelmap multi-label
            return self._merge_ts_individual_files(nifti_files, task)

    def _merge_ts_individual_files(
        self, nifti_files: list, task: str
    ) -> Optional[object]:
        """
        Combina multiples NIfTI individuales de TS v1 en un labelmap.
        (Caso legacy para compatibilidad)
        """
        import slicer
        import numpy as np
        from vtk.util import numpy_support
        import vtk

        # Cargar el primer archivo para obtener geometria de referencia
        ref_node = slicer.util.loadNodeFromFile(nifti_files[0], "NiftiFile")
        if ref_node is None:
            return None

        dims = ref_node.GetImageData().GetDimensions()
        spacing = ref_node.GetSpacing()
        combined = np.zeros((dims[2], dims[1], dims[0]), dtype=np.uint8)

        label_value = 1
        for nifti_path in nifti_files:
            try:
                node = slicer.util.loadNodeFromFile(nifti_path, "NiftiFile")
                if node is None:
                    continue
                arr = numpy_support.vtk_to_array(node.GetImageData())
                # Binarizar y asignar label correlativo
                mask = (arr > 0)
                combined[mask] = label_value
                label_value += 1
                slicer.mrmlScene.RemoveNode(node)
            except Exception as e:
                self.logger.warning(f"Error cargando {nifti_path}: {e}")
                continue

        slicer.mrmlScene.RemoveNode(ref_node)

        # Crear labelmap
        labelmap = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode", f"TS_{task}_merged"
        )
        arr_vtk = combined.astype(np.uint8).ravel()
        vtk_array = numpy_support.numpy_to_vtk(
            arr_vtk, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR
        )
        vtk_image = vtk.vtkImageData()
        vtk_image.SetDimensions(dims)
        vtk_image.SetSpacing(spacing)
        vtk_image.GetPointData().SetScalars(vtk_array)
        labelmap.SetImageData(vtk_image)

        return labelmap

    # ======================================================================
    # MAPEO TS -> PHANTOM
    # ======================================================================

    def _map_ts_to_phantom(self, ts_labelmap) -> Optional[object]:
        """
        Convierte labelmap de TotalSegmentator a phantom con indices 3Dosim.

        Mapeo:
          - Labels en TS_LABEL_TO_PHANTOM → segun mapping
          - Labels en TS_BODY_LABELS → tejido blando (30)
          - Todo lo demas → aire (1)

        Returns:
            numpy array uint8 con indices phantom, o None si falla
        """
        import numpy as np
        from vtk.util import numpy_support

        try:
            img_data = ts_labelmap.GetImageData()
            arr = numpy_support.vtk_to_array(img_data).astype(np.int32)

            self.logger.info(f"  Dimensiones TS: {arr.shape}")
            self.logger.info(f"  Labels unicos en TS: {sorted(set(arr.flatten()))}")

            # Inicializar todo como aire (1)
            phantom = np.ones(arr.shape, dtype=np.uint8)

            # Asignar tejido blando (30) a labels corporales
            body_labels = self.config.get_body_labels()
            body_mask = np.isin(arr, list(body_labels))
            phantom[body_mask] = 30

            # Asignar organos especificos segun mapping
            ts_mapping = self.config.get_ts_mapping()
            for ts_label, phantom_idx in ts_mapping.items():
                mask = (arr == ts_label)
                phantom[mask] = phantom_idx

            # Aire exterior = 1 (ya inicializado como 1)

            self.logger.info(f"  Phantom indices: {sorted(set(phantom.flatten()))}")
            return phantom

        except Exception as e:
            self.logger.error(f"Error mapeando TS a phantom: {e}")
            return None

    # ======================================================================
    # DETECCION DE TUMORES
    # ======================================================================

    def _detect_liver_lesions(
        self, ct_volume_node, phantom_arr
    ) -> Optional[object]:
        """
        Detecta tumores hepaticos usando TotalSegmentator task="liver_lesions".

        El modelo liver_lesions de TS (entrenado en 842 sujetos) segmenta
        lesiones hepaticas en CT. Filtra por mascara de higado del phantom.

        Returns:
            numpy array uint8 con tumores (1=lesion), o None si no hay
        """
        import numpy as np
        import slicer

        ts_tumors = self._run_totalsegmentator(ct_volume_node, task="liver_lesions")
        if ts_tumors is None:
            return None

        try:
            from vtk.util import numpy_support
            arr = numpy_support.vtk_to_array(ts_tumors.GetImageData()).astype(np.uint8)

            # Enmascarar solo dentro del higado (phantom idx 90)
            liver_mask = (phantom_arr == 90)
            tumor_mask = (arr > 0) & liver_mask

            if not tumor_mask.any():
                self.logger.info("  liver_lesions: sin lesiones dentro del higado.")
                slicer.mrmlScene.RemoveNode(ts_tumors)
                return None

            # Post-proceso: remover grupos < 1 cm³ (opcional)
            from scipy import ndimage as ndi

            labeled, num_features = ndi.label(tumor_mask)
            if num_features > 0:
                sizes = ndi.sum(tumor_mask, labeled, range(1, num_features + 1))
                spacing = ct_volume_node.GetSpacing()
                voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
                min_voxels = max(1, int(1.0 / voxel_vol_cc))

                result = np.zeros_like(tumor_mask, dtype=np.uint8)
                for i, size in enumerate(sizes, 1):
                    if size >= min_voxels:
                        result[labeled == i] = 1

                n_lesions = len(np.unique(result[result > 0]))
                self.logger.info(
                    f"  Lesiones detectadas: {n_lesions}, "
                    f"vol total: {int(result.sum()) * voxel_vol_cc:.1f} cc"
                )
            else:
                result = tumor_mask.astype(np.uint8)

            slicer.mrmlScene.RemoveNode(ts_tumors)
            return result

        except Exception as e:
            self.logger.error(f"Error procesando liver_lesions: {e}")
            slicer.mrmlScene.RemoveNode(ts_tumors)
            return None

    # ======================================================================
    # CREACION DEL SEGMENTATION NODE
    # ======================================================================

    def _create_phantom_segmentation(
        self, phantom_arr, reference_volume, tumor_arr=None
    ) -> Optional[object]:
        """
        Convierte array phantom (indices 3Dosim) a vtkMRMLSegmentationNode.

        Si tumor_arr no es None, fusiona tumores (indice 100)
        dentro del higado (indice 90).

        Returns:
            vtkMRMLSegmentationNode, o None si falla
        """
        import slicer
        import numpy as np
        from vtk.util import numpy_support
        import vtk

        try:
            # Fusionar tumor si existe
            if tumor_arr is not None:
                phantom_arr = phantom_arr.copy()
                tumor_mask = (tumor_arr > 0)
                phantom_arr[tumor_mask] = 100

            # Dimensiones
            dims = reference_volume.GetImageData().GetDimensions()
            # phantom_arr shape es (z, y, x) o (x, y, z) segun como se genero
            # Asegurar que coincida con dims de VTK
            shape = phantom_arr.shape
            if len(shape) == 3:
                # VTK orden (x, y, z) = (dims[0], dims[1], dims[2])
                # Si phantom_arr es (z, y, x), transpone
                if shape[0] == dims[2] and shape[2] == dims[0]:
                    arr_vtk = phantom_arr.transpose(2, 1, 0).astype(np.uint8)
                else:
                    arr_vtk = phantom_arr.astype(np.uint8)
            else:
                arr_vtk = phantom_arr.astype(np.uint8)

            # Crear labelmap node temporal
            labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", "__phantom_labelmap__"
            )
            labelmap_node.CopyOrientation(reference_volume)
            labelmap_node.SetSpacing(reference_volume.GetSpacing())
            labelmap_node.SetOrigin(reference_volume.GetOrigin())

            # Crear vtkImageData
            vtk_array = numpy_support.numpy_to_vtk(
                arr_vtk.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR
            )
            vtk_image = vtk.vtkImageData()
            vtk_image.SetDimensions(dims)
            vtk_image.SetSpacing(reference_volume.GetSpacing())
            vtk_image.SetOrigin(reference_volume.GetOrigin())
            vtk_image.GetPointData().SetScalars(vtk_array)
            labelmap_node.SetImageData(vtk_image)

            # Crear SegmentationNode e importar labelmap
            seg_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", "Phantom_3Dosim"
            )
            seg_node.CreateDefaultDisplayNodes()

            # API CORRECTA de Slicer para importar labelmap a segmentation
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmap_node, seg_node
            )

            # Renombrar segmentos y asignar colores
            self._rename_phantom_segments(seg_node)

            # Limpiar temporal
            slicer.mrmlScene.RemoveNode(labelmap_node)

            return seg_node

        except Exception as e:
            self.logger.error(f"Error creando segmentation node: {e}")
            return None

    def _rename_phantom_segments(self, seg_node):
        """
        Renombra los segmentos del phantom y asigna colores.
        Los segmentos se nombran segun el indice 3Dosim.
        """
        seg = seg_node.GetSegmentation()

        # Mapeo: indice phantom -> (nombre, color RGB) desde config
        phantom_segments = {}
        for t in self.config.get_all_tissues():
            idx = t["index"]
            name = t["name"]
            c = t["color"]
            phantom_segments[idx] = (name, (float(c[0]), float(c[1]), float(c[2])))

        n_segments = seg.GetNumberOfSegments()
        for idx in range(n_segments):
            old_name = seg.GetNthSegmentName(idx)
            segment_id = seg.GetNthSegmentID(idx)
            try:
                old_label = int(old_name)
                if old_label in phantom_segments:
                    new_name, color = phantom_segments[old_label]
                    seg.SetSegmentName(segment_id, new_name)
                    display_node = seg_node.GetDisplayNode()
                    if display_node:
                        display_node.SetSegmentColor(
                            segment_id, color[0], color[1], color[2]
                        )
            except (ValueError, TypeError):
                pass

    # ======================================================================
    # ESTADISTICAS
    # ======================================================================

    def _compute_phantom_stats(self, seg_node) -> dict:
        """
        Calcula volumen de cada tejido en el phantom
        usando SegmentStatistics built-in de Slicer.
        """
        import slicer

        try:
            stats_logic = slicer.modules.segmentstatistics.logic()
            params = slicer.vtkMRMLSegmentStatisticsNode()
            params.SetScene(slicer.mrmlScene)
            params.GetVolumeCalculation().SetEnabled(True)
            params.SetSegmentationNode(seg_node)
            stats_logic.ComputeStatistics(params)

            seg = seg_node.GetSegmentation()
            result = {}
            for idx in range(seg.GetNumberOfSegments()):
                seg_name = seg.GetNthSegmentName(idx)
                try:
                    seg_stats = stats_logic.GetStatistics(params, seg_name)
                except Exception:
                    continue
                vol_cm3 = seg_stats.Get("Volume", "cm3") if seg_stats else 0
                vol_ml = (vol_cm3 * 1000) if vol_cm3 else 0

                key = self.config.get_stats_key(seg_name)
                result[key] = float(vol_ml)

            return result

        except Exception as e:
            self.logger.error(f"Error calculando estadisticas: {e}")
            return {}

    # ======================================================================
    # EXPORTACION
    # ======================================================================

    def _export_phantom_to_nifti(
        self, seg_node, reference_volume, output_dir: str
    ) -> Optional[str]:
        """
        Exporta el phantom como NIfTI multicapa (compatible con MCNP).

        El NIfTI contiene los indices 3Dosim (1,30,50,80,90,100)
        en un solo archivo, listo para el Modulo 2 (MCNP).
        """
        import slicer

        try:
            # Exportar segmentation a labelmap
            labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", "__export_phantom__"
            )
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                seg_node, labelmap_node
            )

            # Guardar como NIfTI
            output_path = os.path.join(output_dir, "phantom_3dosim.nii.gz")
            slicer.util.saveNode(labelmap_node, output_path)

            # Guardar tambien como TIFF multicapa para compatibilidad
            # con el pipeline MATLAB original (opcional)
            try:
                tiff_path = os.path.join(output_dir, "phantom_3dosim.tiff")
                slicer.util.saveNode(labelmap_node, tiff_path)
            except Exception:
                pass

            slicer.mrmlScene.RemoveNode(labelmap_node)

            if os.path.exists(output_path):
                self.logger.info(f"Phantom exportado: {output_path}")
                return output_path
            return None

        except Exception as e:
            self.logger.error(f"Error exportando phantom: {e}")
            return None

    # ======================================================================
    # SEGMENTACION DE TUMOR GUIADA (Segment Editor)
    # ======================================================================

    def open_tumor_segmentation_guide(self, ct_volume_node, seg_node):
        """
        Abre el Segment Editor y guia al usuario para segmentar
        el tumor manualmente.

        El usuario puede usar cualquier herramienta del Segment Editor:
          - Paint
          - GrowCut (Grow from seeds)
          - Level Tracing
          - Threshold
          - PETTumorSegmentation (si la extension esta instalada)

        Args:
            ct_volume_node: volumen CT de referencia
            seg_node: SegmentationNode del phantom (debe contener Higado)
        """
        import slicer

        try:
            # 1. Crear segmento vacio para tumor
            segment_id = seg_node.GetSegmentation().AddEmptySegment("Tumor")
            seg_node.GetSegmentation().SetSegmentColor(segment_id, 1.0, 0.0, 0.0)

            # 2. Seleccionar CT como volumen activo
            selection_node = slicer.app.applicationLogic().GetSelectionNode()
            selection_node.SetReferenceActiveVolumeID(ct_volume_node.GetID())
            slicer.app.applicationLogic().PropagateVolumeSelection(0)

            # 3. Abrir Segment Editor
            slicer.util.selectModule("SegmentEditor")

            # 4. Seleccionar el segmento Tumor en el editor
            editor_node = slicer.mrmlScene.GetFirstNodeByClass(
                "vtkMRMLSegmentEditorNode"
            )
            if editor_node:
                editor_node.SetSelectedSegmentID(segment_id)

            # 5. Mostrar overlay del PET si esta disponible
            pet_node = self._find_pet_node()
            if pet_node:
                slicer.util.setSliceViewerLayers(
                    background=ct_volume_node,
                    foreground=pet_node,
                    foregroundOpacity=0.3,
                )

            # 6. Mensaje guia al usuario
            msg = (
                "SEGMENTE EL TUMOR MANUALMENTE\n\n"
                "Herramientas recomendadas:\n"
                "  - Paint: pinte el tumor a mano\n"
                "  - Grow from seeds: pinte semillas dentro y fuera\n"
                "  - Level Tracing: haga clic en el borde\n"
                "  - Threshold: ajuste umbral si el tumor se ve\n\n"
                "Si la extension PETTumorSegmentation esta instalada:\n"
                "  - Active el efecto 'PETTumorSegmentation'\n"
                "  - Haga clic en el centro del tumor en PET\n"
            )
            slicer.util.showStatusMessage(
                "Segment Editor abierto para tumor. Consulte la solapa de Ayuda.",
                20000,
            )
            self.logger.info(msg)

        except Exception as e:
            self.logger.error(f"Error abriendo Segment Editor: {e}")

    def _find_pet_node(self):
        """Busca un nodo PET en la escena."""
        import slicer

        collection = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeNode")
        collection.UnRegister(None)
        for i in range(collection.GetNumberOfItems()):
            node = collection.GetItemAsObject(i)
            name = node.GetName().upper()
            if "PET" in name or "PT_" in name:
                return node
        return None
