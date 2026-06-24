"""
Modulo de segmentacion hepatica y tumoral para SlicerDosim.

Provee metodos de segmentacion usando modulos nativos de 3D Slicer:
  - TotalSegmentator (deep learning, recomendado via PhantomSegmenter)
  - Segment Editor manual (guiado)
  - Threshold en PET para tumores hepaticos (guiado)
  - Carga de NIfTI externo para higado/tumor
  - Threshold clasico + region growing (fallback sin GPU)

NOTA: El pipeline completo recomienda usar PhantomSegmenter.
      Esta clase queda como respaldo para segmentacion individual.
"""

from __future__ import annotations

import logging
from typing import Optional


class LiverSegmenter:
    """Segmentador hepatico y tumoral (metodos individuales de respaldo)."""

    METHOD_TOTALSEGMENTATOR = "totalsegmentator"
    METHOD_SEGMENT_EDITOR = "segment_editor"
    METHOD_MONAI_UNET = "monai_unet"
    METHOD_THRESHOLD_REGION = "threshold_region"

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._available_methods = self._detect_available_methods()

    def _detect_available_methods(self) -> list[str]:
        """Detecta que metodos estan disponibles en el entorno."""
        methods = [self.METHOD_SEGMENT_EDITOR]

        try:
            import totalsegmentator  # noqa: F401
            methods.append(self.METHOD_TOTALSEGMENTATOR)
        except ImportError:
            self.logger.info("TotalSegmentator no disponible")
            pass

        try:
            import monai  # noqa: F401
            methods.append(self.METHOD_MONAI_UNET)
        except ImportError:
            pass

        methods.append(self.METHOD_THRESHOLD_REGION)
        return methods

    @property
    def available_methods(self) -> list[str]:
        return list(self._available_methods)

    # ======================================================================
    # SEGMENTACION HIGADO
    # ======================================================================

    def segment_liver(
        self,
        ct_volume_node,
        method: str = METHOD_TOTALSEGMENTATOR,
        output_segmentation_node=None,
    ) -> Optional[object]:
        """
        Segmenta el higado a partir de un volumen CT.

        Args:
            ct_volume_node: vtkMRMLScalarVolumeNode del CT
            method: metodo a usar
            output_segmentation_node: nodo destino (opcional)

        Returns:
            vtkMRMLSegmentationNode con el higado, o None si falla
        """
        method_map = {
            self.METHOD_TOTALSEGMENTATOR: self._segment_liver_totalsegmentator,
            self.METHOD_SEGMENT_EDITOR: self._segment_editor_manual,
            self.METHOD_MONAI_UNET: self._segment_monai_unet,
            self.METHOD_THRESHOLD_REGION: self._segment_liver_threshold,
        }
        segmenter = method_map.get(method)
        if segmenter is None:
            raise ValueError(f"Metodo no reconocido: {method}")

        self.logger.info(f"Segmentando higado con metodo: {method}")
        result = segmenter(ct_volume_node, output_segmentation_node)
        if result:
            self.logger.info("Segmentacion hepatica completada")
        else:
            self.logger.error("Fallo la segmentacion hepatica")
        return result

    # ======================================================================
    # SEGMENTACION TUMORES
    # ======================================================================

    def segment_tumors(
        self,
        ct_volume_node,
        liver_segmentation_node=None,
        pet_volume_node=None,
        method: str = "manual",
        suv_threshold: float = 2.5,
    ) -> Optional[object]:
        """
        Segmenta tumores hepaticos.

        Args:
            ct_volume_node: volumen CT
            liver_segmentation_node: segmentacion del higado (opcional)
            pet_volume_node: volumen PET registrado
            method: 'pet_suv', 'manual_nifti', 'segment_editor'
            suv_threshold: umbral SUV (solo para method='pet_suv')

        Returns:
            vtkMRMLSegmentationNode con tumores, o None
        """
        if method == "pet_suv":
            return self._segment_tumors_by_pet_suv(
                pet_volume_node, liver_segmentation_node, suv_threshold
            )
        elif method == "manual_nifti":
            return self.load_nifti_as_segmentation("tumor")
        elif method == "segment_editor":
            return self._segment_editor_manual(ct_volume_node)
        else:
            self.logger.error(f"Metodo tumoral no reconocido: {method}")
            return None

    # ======================================================================
    # TOTALSEGMENTATOR (higado)
    # ======================================================================

    def _segment_liver_totalsegmentator(self, ct_volume_node, output_node=None) -> Optional[object]:
        """
        Segmenta usando TotalSegmentator y extrae el higado.
        Usa la extension nativa de Slicer si esta disponible.
        """
        import slicer

        # Verificar si el modulo TotalSegmentator de Slicer esta disponible
        try:
            ts_module = slicer.modules.totalsegmentator
        except AttributeError:
            self.logger.info("Modulo TotalSegmentator de Slicer no disponible, usando Python API...")
            return self._segment_liver_ts_python_api(ct_volume_node)

        # Usar modulo nativo de Slicer
        try:
            parameters = {
                "inputVolume": ct_volume_node.GetID(),
                "segmentation": output_node.GetID() if output_node else "",
                "task": "total",
                "fast": True,
            }
            if output_node is None:
                seg_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLSegmentationNode", "Liver_TS"
                )
                seg_node.CreateDefaultDisplayNodes()
                parameters["segmentation"] = seg_node.GetID()

            self.logger.info("Ejecutando TotalSegmentator (modulo Slicer)...")
            ts_module.cliModuleRun(parameters)

            return seg_node

        except Exception as e:
            self.logger.error(f"Error en modulo TS de Slicer: {e}")
            return None

    def _segment_liver_ts_python_api(self, ct_volume_node) -> Optional[object]:
        """
        Fallback: usar TotalSegmentator via Python API.
        """
        import slicer
        import tempfile
        import os

        try:
            from totalsegmentator.python_api import totalsegmentator
        except ImportError:
            self.logger.error(
                "TotalSegmentator no instalado. "
                "Extension Manager -> TotalSegmentator -> Install"
            )
            return None

        try:
            with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as tmp:
                ct_path = tmp.name
            slicer.util.saveNode(ct_volume_node, ct_path)

            output_dir = tempfile.mkdtemp()
            self.logger.info("Ejecutando TotalSegmentator (Python API)...")
            totalsegmentator(
                input=ct_path,
                output=output_dir,
                ml=True,
                task="total",
                roi_subset=["liver"],
            )

            liver_path = os.path.join(output_dir, "liver.nii.gz")
            if not os.path.exists(liver_path):
                self.logger.error("TS no produjo segmentacion de higado")
                return None

            # Cargar NIfTI
            liver_node = slicer.util.loadNodeFromFile(liver_path, "NiftiFile")
            if liver_node is None:
                return None

            # Convertir a segmentation node
            seg_node = self._labelmap_node_to_segmentation_node(liver_node, "liver")
            if seg_node:
                seg_node.SetName("Liver_Segmentation_AI")

            # Limpiar
            try:
                os.remove(ct_path)
                import shutil
                shutil.rmtree(output_dir)
            except Exception:
                pass

            return seg_node

        except Exception as e:
            self.logger.error(f"Error en TS Python API: {e}")
            return None

    # ======================================================================
    # TUMOR POR THRESHOLD SUV EN PET
    # ======================================================================

    def _segment_tumors_by_pet_suv(
        self, pet_volume_node, liver_segmentation_node, suv_threshold: float = 2.5
    ) -> Optional[object]:
        """
        Segmenta tumores hepaticos aplicando threshold SUV en PET
        dentro de la mascara del higado.

        NOTA: Este metodo es SEMI-AUTOMATICO. El usuario debe
        ajustar el umbral SUV segun su criterio clinico.
        """
        import slicer
        import numpy as np

        if pet_volume_node is None:
            self.logger.error("Se necesita un volumen PET")
            return None
        if liver_segmentation_node is None:
            self.logger.error("Se necesita segmentacion hepatica")
            return None

        try:
            # 1. Obtener mascara del higado
            liver_mask = self._segmentation_node_to_mask(liver_segmentation_node)
            if liver_mask is None:
                return None

            # 2. Obtener array PET
            pet_array = self._volume_node_to_array(pet_volume_node)
            if pet_array is None:
                return None

            # 3. Verificar dimensiones
            if pet_array.shape != liver_mask.shape:
                self.logger.error(
                    f"Dimensiones PET {pet_array.shape} != mascara {liver_mask.shape}. "
                    "Ejecute registro primero."
                )
                return None

            # 4. Threshold SUV dentro del higado
            tumor_mask = np.zeros_like(liver_mask, dtype=np.uint8)
            tumor_region = (pet_array > suv_threshold) & (liver_mask > 0)
            tumor_mask[tumor_region] = 1

            if np.sum(tumor_mask) == 0:
                self.logger.warning(
                    f"No se encontraron voxeles con SUV > {suv_threshold}"
                )
                return None

            # 5. Post-procesamiento: remover objetos < 1 cm^3
            from scipy import ndimage as ndi

            labeled, num_features = ndi.label(tumor_mask)
            if num_features > 0:
                sizes = ndi.sum(tumor_mask, labeled, range(1, num_features + 1))
                spacing = pet_volume_node.GetSpacing()
                voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
                min_voxels = int(1.0 / voxel_vol_cc)

                for i, size in enumerate(sizes, 1):
                    if size < min_voxels:
                        tumor_mask[labeled == i] = 0
                tumor_mask[tumor_mask > 0] = 1

            # 6. Crear nodo de segmentacion
            tumor_node = self._numpy_array_to_segmentation_node(
                tumor_mask, pet_volume_node, "Tumor"
            )
            if tumor_node:
                voxel_vol = spacing[0] * spacing[1] * spacing[2] / 1000.0
                vol_cc = float(np.sum(tumor_mask)) * voxel_vol
                self.logger.info(
                    f"Tumor SUV: {vol_cc:.1f} cm^3 con SUV > {suv_threshold}"
                )
                tumor_node.SetName(f"Tumor_SUV_{suv_threshold}")

            return tumor_node

        except Exception as e:
            self.logger.error(f"Error en segmentacion tumoral SUV: {e}")
            return None

    # ======================================================================
    # THRESHOLD CLASICO (higado, fallback sin GPU)
    # ======================================================================

    def _segment_liver_threshold(self, ct_volume_node, output_node=None) -> Optional[object]:
        """
        Segmenta higado por rango de HU + region growing.
        Pipeline clasico similar al MATLAB original,
        usando efectos del Segment Editor de Slicer.

        Rango tipico del higado: 40-150 HU
        """
        import slicer

        try:
            if output_node is None:
                seg_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLSegmentationNode", "Liver_Threshold"
                )
                seg_node.CreateDefaultDisplayNodes()
            else:
                seg_node = output_node

            segment_id = seg_node.GetSegmentation().AddEmptySegment("liver")

            # Configurar el Segment Editor
            selection_node = slicer.app.applicationLogic().GetSelectionNode()
            selection_node.SetReferenceActiveVolumeID(ct_volume_node.GetID())
            slicer.app.applicationLogic().PropagateVolumeSelection(0)

            # Crear editor node
            editor_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentEditorNode"
            )
            editor_node.SetSelectedSegmentID(segment_id)

            # Obtener widget del Segment Editor
            seg_widget = slicer.modules.segmenteditor.widgetRepresentation()

            # Aplicar Threshold (rango tipico del higado)
            seg_widget.setActiveEffectByName("Threshold")
            effect = seg_widget.activeEffect()
            effect.setParameter("MinimumThreshold", "40")
            effect.setParameter("MaximumThreshold", "150")
            effect.self().onApply()

            # Keep Largest Island
            seg_widget.setActiveEffectByName("Islands")
            effect2 = seg_widget.activeEffect()
            effect2.setParameter("Operation", "KEEP_LARGEST_ISLAND")
            effect2.self().onApply()

            # Smoothing (median)
            seg_widget.setActiveEffectByName("Smoothing")
            effect3 = seg_widget.activeEffect()
            effect3.setParameter("SmoothingMethod", "MEDIAN")
            effect3.setParameter("KernelSizeMm", 3)
            effect3.self().onApply()

            return seg_node

        except Exception as e:
            self.logger.error(f"Error en threshold hepatico: {e}")
            return None

    # ======================================================================
    # SEGMENT EDITOR MANUAL
    # ======================================================================

    def _segment_editor_manual(self, ct_volume_node, output_node=None) -> Optional[object]:
        """
        Abre el Segment Editor de 3D Slicer para segmentacion manual.
        El usuario segmenta con las herramientas que prefiera.
        """
        import slicer

        try:
            slicer.util.showStatusMessage(
                "Segment Editor abierto para segmentation manual.", 10000
            )
            slicer.util.selectModule("SegmentEditor")
            selection_node = slicer.app.applicationLogic().GetSelectionNode()
            selection_node.SetReferenceActiveVolumeID(ct_volume_node.GetID())
            slicer.app.applicationLogic().PropagateVolumeSelection(0)
        except Exception as e:
            self.logger.error(f"Error al abrir Segment Editor: {e}")
        return None

    # ======================================================================
    # MONAI U-Net (placeholder)
    # ======================================================================

    def _segment_monai_unet(self, ct_volume_node, output_node=None) -> Optional[object]:
        """Placeholder para MONAI U-Net. Usar TotalSegmentator en su lugar."""
        self.logger.warning("MONAI U-Net no implementado. Use TotalSegmentator.")
        return None

    # ======================================================================
    # CARGA DE NIFTI EXTERNO
    # ======================================================================

    def load_nifti_as_segmentation(self, structure_name: str) -> Optional[object]:
        """
        Carga un archivo NIfTI seleccionado por el usuario y lo
        convierte en un nodo de segmentacion.
        """
        import slicer

        file_path = slicer.util.getOpenFileName(
            None, f"Seleccionar NIfTI de {structure_name}",
            "", "NIfTI (*.nii *.nii.gz)"
        )
        if not file_path:
            return None

        try:
            node = slicer.util.loadNodeFromFile(file_path, "NiftiFile")
            if node is None:
                self.logger.error(f"No se pudo cargar: {file_path}")
                return None

            seg_node = self._labelmap_node_to_segmentation_node(node, structure_name)
            return seg_node

        except Exception as e:
            self.logger.error(f"Error cargando NIfTI: {e}")
            return None

    # ======================================================================
    # CONVERSIONES: LABELMAP -> SEGMENTATION NODE  (API CORREGIDA)
    # ======================================================================

    def _labelmap_node_to_segmentation_node(
        self, labelmap_node, segment_name: str
    ) -> Optional[object]:
        """
        Convierte un vtkMRMLLabelMapVolumeNode a vtkMRMLSegmentationNode.

        Usa la API oficial de Slicer:
          slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode()

        Args:
            labelmap_node: vtkMRMLLabelMapVolumeNode con la segmentacion
            segment_name: nombre del segmento

        Returns:
            vtkMRMLSegmentationNode, o None si falla
        """
        import slicer

        try:
            # Asegurar que es un labelmap node (no scalar)
            if not labelmap_node.IsA("vtkMRMLLabelMapVolumeNode"):
                # Convertir a labelmap
                labelmap = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLLabelMapVolumeNode", f"__{segment_name}_labelmap__"
                )
                labelmap.CopyOrientation(labelmap_node)
                labelmap.SetSpacing(labelmap_node.GetSpacing())
                labelmap.SetImageData(labelmap_node.GetImageData())
                labelmap_node = labelmap
            else:
                labelmap = labelmap_node

            # Crear segmentation node
            seg_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", f"{segment_name}_Segmentation"
            )
            seg_node.CreateDefaultDisplayNodes()

            # API CORRECTA: ImportLabelmapToSegmentationNode
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmap, seg_node
            )

            # Renombrar el primer segmento
            seg = seg_node.GetSegmentation()
            if seg.GetNumberOfSegments() > 0:
                segment_id = seg.GetNthSegmentID(0)
                seg.SetSegmentName(segment_id, segment_name)

            return seg_node

        except Exception as e:
            self.logger.error(f"Error convirtiendo labelmap a segmentacion: {e}")
            return None

    # ======================================================================
    # ARRAY NUMPY -> SEGMENTATION NODE
    # ======================================================================

    def _numpy_array_to_segmentation_node(
        self, mask_array, reference_volume, name: str
    ) -> Optional[object]:
        """
        Convierte un array numpy binario a vtkMRMLSegmentationNode.
        """
        import numpy as np
        import slicer
        import vtk
        from vtk.util import numpy_support

        try:
            # Crear labelmap node temporal
            labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", f"__temp_{name}__"
            )
            labelmap_node.CopyOrientation(reference_volume)
            labelmap_node.SetSpacing(reference_volume.GetSpacing())
            labelmap_node.SetOrigin(reference_volume.GetOrigin())

            # Dimensiones de referencia
            ref_image = reference_volume.GetImageData()
            dims = ref_image.GetDimensions()

            # Asegurar orientacion correcta: (z,y,x) -> (x,y,z) para VTK
            if len(mask_array.shape) == 3:
                arr_vtk = np.transpose(mask_array, (2, 1, 0)).astype(np.uint8)
            else:
                arr_vtk = mask_array.astype(np.uint8)

            vtk_array = numpy_support.numpy_to_vtk(
                arr_vtk.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR
            )
            vtk_image = vtk.vtkImageData()
            vtk_image.SetDimensions(dims)
            vtk_image.SetSpacing(reference_volume.GetSpacing())
            vtk_image.SetOrigin(reference_volume.GetOrigin())
            vtk_image.GetPointData().SetScalars(vtk_array)
            labelmap_node.SetImageData(vtk_image)

            # Convertir a segmentation node
            seg_node = self._labelmap_node_to_segmentation_node(labelmap_node, name)

            # Limpiar
            slicer.mrmlScene.RemoveNode(labelmap_node)

            return seg_node

        except Exception as e:
            self.logger.error(f"Error creando segmentation node: {e}")
            return None

    # ======================================================================
    # ESTADISTICAS
    # ======================================================================

    def compute_volume_stats(self, segmentation_node) -> dict:
        """
        Calcula estadisticas volumetricas usando SegmentStatistics de Slicer.
        """
        import slicer

        try:
            stats_logic = slicer.modules.segmentstatistics.logic()
            params = slicer.vtkMRMLSegmentStatisticsNode()
            params.SetScene(slicer.mrmlScene)
            params.GetVolumeCalculation().SetEnabled(True)
            params.SetSegmentationNode(segmentation_node)
            stats_logic.ComputeStatistics(params)

            result = {"volume_ml": 0.0, "surface_mm2": 0.0}
            seg = segmentation_node.GetSegmentation()
            for idx in range(seg.GetNumberOfSegments()):
                seg_name = seg.GetNthSegmentName(idx)
                try:
                    seg_stats = stats_logic.GetStatistics(params, seg_name)
                except Exception:
                    continue
                if seg_stats:
                    vol = seg_stats.Get("Volume", "cm3")
                    if vol:
                        result["volume_ml"] += float(vol) * 1000
                    surf = seg_stats.Get("SurfaceArea", "mm2")
                    if surf:
                        result["surface_mm2"] += float(surf)

            return result

        except Exception as e:
            self.logger.error(f"Error calculando estadisticas: {e}")
            return {"volume_ml": 0.0, "surface_mm2": 0.0}

    # ======================================================================
    # HELPERS
    # ======================================================================

    def _volume_node_to_array(self, volume_node) -> Optional[object]:
        """Extrae un array numpy de un vtkMRMLScalarVolumeNode."""
        import numpy as np
        from vtk.util import numpy_support
        import slicer

        try:
            image_data = volume_node.GetImageData()
            if image_data is None:
                return None
            array = numpy_support.vtk_to_array(image_data)
            # Transponer de (z, y, x) a (x, y, z)
            array = np.transpose(array, (2, 1, 0))
            return array
        except Exception as e:
            self.logger.error(f"Error leyendo volumen: {e}")
            return None

    def _segmentation_node_to_mask(self, seg_node) -> Optional[object]:
        """
        Convierte vtkMRMLSegmentationNode a array numpy binario.
        Fusiona todos los segmentos en una sola mascara.
        """
        import numpy as np
        import slicer
        from vtk.util import numpy_support

        try:
            labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", "__temp_mask__"
            )
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                seg_node, labelmap_node
            )

            image_data = labelmap_node.GetImageData()
            array = numpy_support.vtk_to_array(image_data)
            array = np.transpose(array, (2, 1, 0))
            mask = (array > 0).astype(np.uint8)

            slicer.mrmlScene.RemoveNode(labelmap_node)
            return mask

        except Exception as e:
            self.logger.error(f"Error extrayendo mascara: {e}")
            return None

    def _get_volume_spacing(self, volume_node) -> tuple:
        """Obtiene espaciado de un volumen en mm."""
        spacing = volume_node.GetSpacing()
        return (spacing[0], spacing[1], spacing[2])
