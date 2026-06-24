"""
Generador de archivos de entrada MCNP para SlicerDosim.

Formato MATLAB de referencia: 3Dosim_MCNP_Y90_universos.i
- Universos con LIKE n BUT, sphere 650 como boundary
- Lattice fill con RLE
- Fuente desde archivo .src externo (Y90cel3D.src)
- Talles TMESH
- Materiales: aire (m1) + tejido blando (m2) para todos los organos
"""

from __future__ import annotations

import logging
import os
import numpy as np
from typing import Optional

from .config import TissueConfig


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MAPPING: TotalSegmentator segment names -> phantom indices
# ---------------------------------------------------------------------------
# 1 = Aire
# 2-25 = Organos individuales de TS -> Tejido_blando (mat=30)
# 30 = Soft Tissue general (mat=30)
# 50 = Pulmon (mat=50)
# 80 = Hueso (mat=80)
# 90 = Higado (mat=90)
# 100 = Tumor (mat=100)
#
# Materiales definidos en tissue_config.json con composiciones especificas.
# Cada indice phantom mapea a un material MCNP distinto con densidad propia.
# ---------------------------------------------------------------------------

TS_SEGMENT_MAP = {
    # -------------------------------------------------------------------
    # Mapeo de nombres TotalSegmentator a indices phantom (universos).
    # Los indices 2-25 son LEGACY (se mantienen para compatibilidad de
    # universos MCNP). El material que usa cada universo se define en
    # PHANTOM_IDX_TO_MATERIAL abajo.
    #
    # Los indices 50, 80, 90, 100 son del tissue_config original.
    # -------------------------------------------------------------------
    "spleen": 2,
    "right kidney": 3,
    "left kidney": 4,
    "gallbladder": 5,
    "liver": 90,
    "stomach": 6,
    "pancreas": 7,
    "right adrenal gland": 8,
    "left adrenal gland": 9,
    "superior lobe of left lung": 50,
    "inferior lobe of left lung": 50,
    "superior lobe of right lung": 50,
    "middle lobe of right lung": 50,
    "inferior lobe of right lung": 50,
    "esophagus": 10,
    "small bowel": 11,
    "duodenum": 12,
    "colon": 13,
    "heart": 14,
    "aorta": 15,
    "pulmonary venous system": 16,
    "left atrial appendage": 17,
    "superior vena cava": 18,
    "inferior vena cava": 19,
    "portal vein and splenic vein": 20,
    "spinal cord": 21,
    "left deep back muscle": 22,
    "right deep back muscle": 23,
    "left iliopsoas muscle": 24,
    "right iliopsoas muscle": 25,
    # Vertebrae -> bone group (index 80)
    "l3 vertebra": 80,
    "l2 vertebra": 80,
    "l1 vertebra": 80,
    "t12 vertebra": 80,
    "t11 vertebra": 80,
    "t10 vertebra": 80,
    "t9 vertebra": 80,
    "t8 vertebra": 80,
    "t7 vertebra": 80,
    "t6 vertebra": 80,
    # Scapulae -> bone group (index 80)
    "left scapula": 80,
    "right scapula": 80,
    # Ribs -> bone group (index 80)
    "left rib 3": 80,
    "left rib 4": 80,
    "left rib 5": 80,
    "left rib 6": 80,
    "left rib 7": 80,
    "left rib 8": 80,
    "left rib 9": 80,
    "left rib 10": 80,
    "left rib 11": 80,
    "left rib 12": 80,
    "right rib 3": 80,
    "right rib 4": 80,
    "right rib 5": 80,
    "right rib 6": 80,
    "right rib 7": 80,
    "right rib 8": 80,
    "right rib 9": 80,
    "right rib 10": 80,
    "right rib 11": 80,
    "right rib 12": 80,
    "sternum": 80,
    "costal cartilage": 80,
    # Tumor (synthetic)
    "tumor": 100,
    "tumor_sintetico": 100,
}

# ---------------------------------------------------------------------------
# MAPEO: indices phantom legacy (2-25) -> materiales ICRP-110
# ---------------------------------------------------------------------------
# Los indices 2-25 se usan en TS_SEGMENT_MAP como numeros de universo.
# Cada uno mapea al material ICRP-110 correcto definido en tissue_config.json.
# El mid y la composicion se cargan desde tissue_config (indices 101-153).
# ---------------------------------------------------------------------------
PHANTOM_IDX_TO_MATERIAL: dict[int, dict] = {
    2:  {"mid": 45, "name": "Bazo", "rho": 1.04},           # spleen
    3:  {"mid": 41, "name": "Rinones", "rho": 1.05},        # right kidney
    4:  {"mid": 41, "name": "Rinones", "rho": 1.05},        # left kidney
    5:  {"mid": 51, "name": "Tejido_mixto", "rho": 1.03},   # gallbladder
    6:  {"mid": 42, "name": "Estomago", "rho": 1.04},       # stomach
    7:  {"mid": 37, "name": "Pancreas", "rho": 1.05},       # pancreas
    8:  {"mid": 49, "name": "Suprarrenales", "rho": 1.03},  # right adrenal
    9:  {"mid": 49, "name": "Suprarrenales", "rho": 1.03},  # left adrenal
    10: {"mid": 50, "name": "Esofago", "rho": 1.03},        # esophagus
    11: {"mid": 43, "name": "Intestino_delgado", "rho": 1.04}, # small bowel
    12: {"mid": 43, "name": "Intestino_delgado", "rho": 1.04}, # duodenum
    13: {"mid": 44, "name": "Intestino_grueso", "rho": 1.04}, # colon
    14: {"mid": 39, "name": "Corazon", "rho": 1.05},        # heart
    15: {"mid": 34, "name": "Sangre", "rho": 1.06},         # aorta
    16: {"mid": 34, "name": "Sangre", "rho": 1.06},         # pulmonary venous system
    17: {"mid": 39, "name": "Corazon", "rho": 1.05},        # left atrial appendage
    18: {"mid": 34, "name": "Sangre", "rho": 1.06},         # superior vena cava
    19: {"mid": 34, "name": "Sangre", "rho": 1.06},         # inferior vena cava
    20: {"mid": 34, "name": "Sangre", "rho": 1.06},         # portal vein and splenic vein
    21: {"mid": 35, "name": "Tejido_muscular", "rho": 1.05}, # spinal cord
    22: {"mid": 35, "name": "Tejido_muscular", "rho": 1.05}, # left deep back muscle
    23: {"mid": 35, "name": "Tejido_muscular", "rho": 1.05}, # right deep back muscle
    24: {"mid": 35, "name": "Tejido_muscular", "rho": 1.05}, # left iliopsoas muscle
    25: {"mid": 35, "name": "Tejido_muscular", "rho": 1.05}, # right iliopsoas muscle
}

# Nota: PHANTOM_MAT_MAP y MAT_COMPOSITIONS ahora se construyen
# dinamicamente desde TissueConfig en MCNPInputGenerator._build_material_maps()
# Ver tissue_config.json para la configuracion de cada tejido.


class MCNPInputGenerator:
    """
    Generador de entrada MCNP siguiendo el formato MATLAB de 3Dosim.

    Produce un archivo .i con:
      - Universos (LIKE n BUT) con sphere 650 como boundary
      - Lattice voxelizado con RLE
      - Fuente desde archivo .src externo
      - Talles TMESH
      - Materiales desde tissue_config.json (aire, tejido blando, pulmon,
        hueso, higado, tumor — cada uno con su composicion elemental)
    """

    def __init__(self):
        self.config = TissueConfig()
        self._build_material_maps()

    # ======================================================================
    # BUILD MATERIAL MAPS FROM TISSUE CONFIG
    # ======================================================================

    def _build_material_maps(self):
        """
        Construye mapas de materiales desde TissueConfig.

        Crea:
          self._phantom_to_mat[phantom_index] -> {"mid": int, "name": str, "rho": float}
          self._compositions[mat_id] -> [(ZAID, mass_frac), ...]

        Incluye fallback: si un indice phantom no tiene material definido,
        se asigna a Tejido_blando (30). El indice 0 (vacio) se mapea a material 1 (aire).
        """
        self._phantom_to_mat: dict[int, dict] = {}
        self._compositions: dict[int, list[tuple]] = {}

        for t in self.config.get_all_tissues():
            idx = t["index"]
            mat = t.get("mcnp_material", {})
            if not mat:
                logger.warning(f"Tejido '{t['name']}' (idx={idx}) sin material MCNP definido")
                continue

            mid = mat["id"]
            comp = mat.get("composition", {})
            density = t["density_gcm3"]
            name = t["name"]

            self._phantom_to_mat[idx] = {
                "mid": int(mid),
                "name": name,
                "rho": density,
            }

            # Convertir composicion de dict a lista (ZAID, mass_frac)
            # MCNP usa fraccion de masa negativa
            comp_list = [(str(zaid), float(frac)) for zaid, frac in comp.items()]
            self._compositions[int(mid)] = comp_list

        # Fallback: indice 0 (vacio) -> material 1 (aire)
        if 0 not in self._phantom_to_mat:
            aire_info = self._phantom_to_mat.get(1)
            if aire_info:
                self._phantom_to_mat[0] = aire_info

        # Fallback: si falta Tejido_blando (30), crearlo con composicion generica
        if 30 not in self._phantom_to_mat:
            self._phantom_to_mat[30] = {"mid": 30, "name": "Tejido_blando", "rho": 1.04}
            if 30 not in self._compositions:
                self._compositions[30] = [
                    ("1000", 0.101), ("6000", 0.111), ("7014", 0.020),
                    ("8016", 0.762), ("11000", 0.002), ("15000", 0.003),
                    ("16000", 0.003), ("17000", 0.002), ("19000", 0.003),
                ]

        # ------------------------------------------------------------------
        # Mapeo legacy: indices phantom 2-25 -> materiales ICRP-110
        # ------------------------------------------------------------------
        # Estos indices no existen en tissue_config.json pero se usan en
        # TS_SEGMENT_MAP como numeros de universo. Cada uno debe apuntar
        # al material ICRP-110 correcto (mid, composicion, densidad).
        # La composicion ya se cargo desde tissue_config (indices 101-153).
        # ------------------------------------------------------------------
        for legacy_idx, mat_info in PHANTOM_IDX_TO_MATERIAL.items():
            if legacy_idx not in self._phantom_to_mat:
                self._phantom_to_mat[legacy_idx] = mat_info
                mid = mat_info["mid"]
                if mid not in self._compositions:
                    logger.warning(
                        f"Material m{mid} ({mat_info['name']}) no encontrado "
                        f"en tissue_config. Verificar indices ICRP-110."
                    )

        logger.info(
            f"Material maps construidos: {len(self._phantom_to_mat)} indices phantom "
            f"-> {len(self._compositions)} materiales MCNP"
        )
        for idx, info in sorted(self._phantom_to_mat.items()):
            logger.debug(f"  idx={idx:>3} -> mid={info['mid']} ({info['name']}, rho={info['rho']})")

    def generate(
        self,
        ct_volume_node,
        pet_volume_node=None,
        segmentation_node=None,
        body_segmentation_node=None,
        output_dir: str = ".",
        isotope: str = "Y-90",
        n_particles: int = int(1e7),
        refine_hu: bool = False,
        flip_rows: bool = False,
        flip_z: bool = False,
        n_liver_tallies: int = 5,
        n_tumor_tallies: int = 10,
    ) -> str:
        """
        Genera archivo de entrada MCNP completo.

        Args:
            ct_volume_node: vtkMRMLScalarVolumeNode del CT
            pet_volume_node: vtkMRMLScalarVolumeNode del PET (opcional)
            segmentation_node: vtkMRMLLabelMapVolumeNode o vtkMRMLSegmentationNode
            body_segmentation_node: vtkMRMLSegmentationNode con body (task='body') para rellenar fondo con tejido blando (idx 30)
            output_dir: directorio de salida
            isotope: isotopo (Y-90, I-131, Lu-177, Tc-99m)
            n_particles: numero de historias
            refine_hu: si True, refina materiales por HU (no usado por ahora)
            flip_rows: si True, invierte eje Y antes de RLE (como MATLAB)
            flip_z: si True, invierte eje Z antes de RLE (como MATLAB)

        Returns:
            ruta al archivo .i generado
        """
        iso_data = ISOTOPE_DATA.get(isotope)
        if iso_data is None:
            raise ValueError(f"Isotopo no soportado: {isotope}")

        logger.info(f"Generando entrada MCNP para {isotope}, {n_particles} particulas")
        logger.info(f"  CT: {ct_volume_node.GetName() if ct_volume_node else 'None'}")
        logger.info(f"  PET: {pet_volume_node.GetName() if pet_volume_node else 'None'}")

        # 1. Extraer info del volumen
        dims, origin, spacing = self._get_volume_info(ct_volume_node)
        nx, ny, nz = dims

        # --- Cuantizar spacing a 0.001 mm (1 micron), como MATLAB modulo 2 ---
        # MATLAB: tvoxel=quant(tvoxel,0.001)
        # Sin esto: sx=0.9765625 -> xm=512*0.09765625=50.000000 (MAL)
        # Con esto: sx=0.977      -> xm=512*0.0977=50.0224 (BIEN, coincide con RPP)
        # El spacing cuantizado se pasa a TODOS los metodos via el parametro.
        sx, sy, sz = spacing
        sx_q = round(sx * 1000) / 1000
        sy_q = round(sy * 1000) / 1000
        sz_q = round(sz * 1000) / 1000
        spacing = (sx_q, sy_q, sz_q)  # overwrite with quantized values

        # --- Almacenar dimensiones exactas en cm como atributos compartidos ---
        # para que _write_surfaces y _write_tallies usen EXACTAMENTE el mismo float
        sx_cm, sy_cm, sz_cm = sx_q / 10.0, sy_q / 10.0, sz_q / 10.0
        self._xm = nx * sx_cm
        self._ym = ny * sy_cm
        self._zm = nz * sz_cm

        logger.info(f"  Dimensiones (voxeles): {dims}")
        logger.info(f"  Espaciado raw (mm): ({sx}, {sy}, {sz})")
        logger.info(f"  Espaciado quant (mm): ({sx_q}, {sy_q}, {sz_q})")
        logger.info(f"  Dimensiones (cm): {self._xm:.4f} x {self._ym:.4f} x {self._zm:.4f}")

        # 2. Extraer labelmap (fusiona organos + body si existe)
        self._ct_ref_node = ct_volume_node
        phantom_arr = self._get_phantom_labelmap(segmentation_node, dims, body_segmentation_node)
        if phantom_arr is None:
            raise RuntimeError("No se pudo extraer labelmap del phantom")
        unique_vals = sorted(np.unique(phantom_arr))
        logger.info(f"  Indices phantom: {unique_vals}")

        # 3. Extraer PET array
        pet_arr = self._get_pet_array(pet_volume_node, dims)

        # 3b. Aplicar flips ANTES de cualquier procesamiento (como MATLAB)
        # MATLAB f_flip: I(end:-1:1, :, :) -> invierte la primera dimensión (rows/Y)
        # En numpy con shape (NX, NY, NZ), Y está en dim 1 -> [:, ::-1, :]
        if flip_rows:
            phantom_arr = phantom_arr[:, ::-1, :].copy()
            if pet_arr is not None:
                pet_arr = pet_arr[:, ::-1, :].copy()
            logger.info("  Flip Y aplicado (inversion eje Y, dim=1)")
        if flip_z:
            phantom_arr = phantom_arr[:, :, ::-1].copy()
            if pet_arr is not None:
                pet_arr = pet_arr[:, :, ::-1].copy()
            logger.info("  Flip Z aplicado (inversion eje Z, dim=2)")

        # 3c. Extraer PatientID (para tallies)
        try:
            patient_id = ct_volume_node.GetName()
        except Exception:
            patient_id = "3Dosim_CT"

        # 4. Escribir archivo MCNP
        os.makedirs(output_dir, exist_ok=True)
        input_path = os.path.join(output_dir, "3Dosim_mcnp.i")

        with open(input_path, "w") as f:
            self._write_header(f, isotope, iso_data, flip_rows, flip_z)
            self._write_universes(f, phantom_arr, dims, spacing)
            self._write_lattice(f, phantom_arr, dims, spacing)
            self._write_surfaces(f, dims, spacing)
            self._write_mode(f, iso_data)
            self._write_source(f, pet_arr, dims, spacing, phantom_arr, iso_data)
            self._write_tallies(f, dims, spacing, iso_data)
            self._write_random_tallies(f, phantom_arr, dims, spacing, patient_id,
                                       n_liver_tallies, n_tumor_tallies, flip_rows, flip_z)
            self._write_materials(f)
            self._write_footer(f, n_particles)

        file_size_mb = os.path.getsize(input_path) / 1024 / 1024
        logger.info(f"Archivo MCNP generado: {input_path} ({file_size_mb:.1f} MB)")
        return input_path

    # ======================================================================
    # HELPERS DE EXTRACCION
    # ======================================================================

    def _get_volume_info(self, volume_node):
        """Obtiene (dimensions, origin, spacing) de un volumen VTK."""
        try:
            image_data = volume_node.GetImageData()
            dims = image_data.GetDimensions()
            origin = volume_node.GetOrigin()
            spacing = volume_node.GetSpacing()
            return dims, origin, spacing
        except Exception as e:
            logger.error(f"Error obteniendo info del volumen: {e}")
            return (64, 64, 64), (0, 0, 0), (3.0, 3.0, 3.0)

    def _get_phantom_labelmap(self, segmentation_node, dims, body_segmentation_node=None) -> Optional[np.ndarray]:
        """
        Extrae labelmap 3D numpy del phantom.

        Mapea cada segmento de TotalSegmentator a su indice phantom
        usando TS_SEGMENT_MAP. Los indices 90 (liver) y 100 (tumor)
        se mantienen del tissue_config original.

        Si se proporciona body_segmentation_node, los voxeles de fondo
        dentro del body se rellenan con indice 30 (Tejido_blando) en vez de 1 (Aire).
        """
        import slicer
        import vtk
        from vtk.util.numpy_support import vtk_to_numpy

        try:
            logger.info(f"  Extrayendo labelmap de: {segmentation_node.GetName()}")

            # --- Caso 1: ya es labelmap ---
            if segmentation_node.IsA("vtkMRMLLabelMapVolumeNode"):
                logger.info("  Nodo es labelmap, usando directo")
                img_data = segmentation_node.GetImageData()
                if img_data is None:
                    logger.error("  GetImageData() devolvio None")
                    return None

                scalars = img_data.GetPointData().GetScalars()
                if scalars is None:
                    scalars = img_data.GetCellData().GetScalars()
                if scalars is None:
                    logger.error("  No se encontraron escalares en labelmap")
                    return None

                arr_flat = vtk_to_numpy(scalars)
                vtk_dims = img_data.GetDimensions()
                arr = arr_flat.reshape((vtk_dims[2], vtk_dims[1], vtk_dims[0]))
                arr = arr.transpose(2, 1, 0)
                logger.info(f"  Array shape: {arr.shape} (X,Y,Z)")
                logger.info(f"  Valores unicos: {np.unique(arr)}")
                return arr

            # --- Caso 2: segmentation node ---
            seg_ids = vtk.vtkStringArray()
            segmentation_node.GetSegmentation().GetSegmentIDs(seg_ids)
            n_segments = seg_ids.GetNumberOfValues()
            logger.info(f"  Segmentos disponibles: {n_segments}")
            if n_segments == 0:
                logger.error("  La segmentacion no tiene segmentos")
                return None

            # Crear array acumulado con todos los segmentos
            nx, ny, nz = dims
            accumulated = np.zeros((nx, ny, nz), dtype=np.int32)

            # Referencia geometrica: CT node
            ref_node = getattr(self, '_ct_ref_node', None)
            if ref_node is None:
                ref_node = segmentation_node

            # --- Extraer mascara de body si se proporciona ---
            body_mask = None
            if body_segmentation_node is not None:
                logger.info("  Extrayendo mascara de body para relleno de tejido blando...")
                body_mask = self._extract_body_mask(body_segmentation_node, ref_node, dims)
                if body_mask is not None:
                    logger.info(f"  Body mask: {int(body_mask.sum())} voxeles")
                else:
                    logger.warning("  No se pudo extraer body mask")

            tmp_labelmap = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", "__mcnp_phantom__"
            )

            exported_count = 0
            for i in range(n_segments):
                seg_id = seg_ids.GetValue(i)
                segment = segmentation_node.GetSegmentation().GetSegment(seg_id)
                seg_name = segment.GetName() if segment else seg_id

                # Buscar indice phantom para este segmento
                # Buscar por nombre (case-insensitive)
                seg_name_lower = seg_name.lower().replace(" ", " ").strip()
                phantom_idx = None
                for ts_name, idx in TS_SEGMENT_MAP.items():
                    if ts_name.lower() == seg_name_lower:
                        phantom_idx = idx
                        break

                if phantom_idx is None:
                    logger.debug(f"  Segmento '{seg_name}' no mapeado, saltando")
                    continue

                # Exportar este segmento como mascara binaria
                single_ids = vtk.vtkStringArray()
                single_ids.InsertNextValue(seg_id)
                slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                    segmentation_node, single_ids, tmp_labelmap, ref_node
                )

                tmp_img = tmp_labelmap.GetImageData()
                if tmp_img is None or tmp_img.GetPointData().GetScalars() is None:
                    continue

                seg_scalars = vtk_to_numpy(tmp_img.GetPointData().GetScalars())
                if seg_scalars is None:
                    continue

                vtk_d = tmp_img.GetDimensions()
                seg_arr = seg_scalars.reshape((vtk_d[2], vtk_d[1], vtk_d[0])).transpose(2, 1, 0)

                # Acumular: donde la mascara es > 0, poner el phantom_idx
                # Prioridad: indice mas alto gana (tumor=100 > liver=90 > bone=80 > ...)
                mask = seg_arr > 0
                if phantom_idx > 0:
                    overwrite = mask & ((accumulated == 0) | (phantom_idx > accumulated))
                    accumulated[overwrite] = phantom_idx
                    exported_count += 1
                    logger.debug(f"  Segmento '{seg_name}': {mask.sum()} voxels -> idx {phantom_idx}")

            # Limpiar
            slicer.mrmlScene.RemoveNode(tmp_labelmap)

            # Convertir 0 (vacio) -> 1 (aire) o 30 (tejido blando) si hay body_mask
            if body_mask is not None:
                # Dentro del body: 30 (tejido blando), fuera: 1 (aire)
                accumulated[(accumulated == 0) & (body_mask > 0)] = 30
                accumulated[(accumulated == 0) & (body_mask == 0)] = 1
                logger.info(f"  Relleno body: {int((body_mask > 0).sum())} voxeles -> idx 30")
            else:
                accumulated[accumulated == 0] = 1

            unique_vals = sorted(np.unique(accumulated))
            logger.info(f"  Exportados {exported_count}/{n_segments} segmentos")
            logger.info(f"  Indices phantom: {unique_vals}")
            logger.info(f"  Array shape: {accumulated.shape} (X,Y,Z)")

            if exported_count == 0:
                logger.error("  No se pudo exportar ningun segmento")
                return None

            return accumulated

        except Exception as e:
            logger.error(f"Error extrayendo phantom labelmap: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_body_mask(self, body_segmentation_node, ref_node, dims) -> Optional[np.ndarray]:
        """Extrae mascara binaria del body (primer segmento de la segmentacion body)."""
        import slicer
        import vtk
        from vtk.util.numpy_support import vtk_to_numpy

        try:
            tmp_labelmap = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode", "__body_mask__"
            )

            # Exportar el primer segmento (body)
            seg_ids = vtk.vtkStringArray()
            body_segmentation_node.GetSegmentation().GetSegmentIDs(seg_ids)
            if seg_ids.GetNumberOfValues() == 0:
                slicer.mrmlScene.RemoveNode(tmp_labelmap)
                return None

            first_seg_id = seg_ids.GetValue(0)
            single_ids = vtk.vtkStringArray()
            single_ids.InsertNextValue(first_seg_id)

            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                body_segmentation_node, single_ids, tmp_labelmap, ref_node
            )

            tmp_img = tmp_labelmap.GetImageData()
            if tmp_img is None or tmp_img.GetPointData().GetScalars() is None:
                slicer.mrmlScene.RemoveNode(tmp_labelmap)
                return None

            seg_scalars = vtk_to_numpy(tmp_img.GetPointData().GetScalars())
            if seg_scalars is None:
                slicer.mrmlScene.RemoveNode(tmp_labelmap)
                return None

            vtk_d = tmp_img.GetDimensions()
            mask = seg_scalars.reshape((vtk_d[2], vtk_d[1], vtk_d[0])).transpose(2, 1, 0)
            mask = (mask > 0).astype(np.uint8)

            slicer.mrmlScene.RemoveNode(tmp_labelmap)
            return mask

        except Exception as e:
            logger.warning(f"  Error extrayendo body mask: {e}")
            try:
                slicer.mrmlScene.RemoveNode(tmp_labelmap)
            except:
                pass
            return None

    def _get_pet_array(self, pet_volume_node, dims) -> Optional[np.ndarray]:
        """Extrae array 3D del PET."""
        if pet_volume_node is None:
            return None
        try:
            from vtk.util.numpy_support import vtk_to_numpy
            img_data = pet_volume_node.GetImageData()
            if img_data is None:
                return None
            arr = vtk_to_numpy(img_data.GetPointData().GetScalars())
            if arr is None:
                return None
            vtk_dims = img_data.GetDimensions()
            try:
                arr = arr.reshape((vtk_dims[2], vtk_dims[1], vtk_dims[0]))
                arr = arr.transpose(2, 1, 0)
            except ValueError:
                arr = arr.reshape(dims)
            logger.info(f"  PET array shape: {arr.shape}")
            return arr.astype(np.float64)
        except Exception as e:
            logger.warning(f"No se pudo extraer PET: {e}")
            return None

    # ======================================================================
    # ESCRITURA DEL ARCHIVO MCNP (formato MATLAB)
    # ======================================================================

    def _write_header(self, f, isotope, iso_data, flip_rows=False, flip_z=False):
        """Escribe cabecera del archivo."""
        import datetime
        now = datetime.datetime.now()
        f.write("c ------------------------------------------------------ \n")
        f.write("c ------------------------------------------------------ \n")
        f.write("c ------------------------------------------------------ \n")
        f.write("c Archivo generado con 3Dosim, version 3.14 \n")
        f.write(f"c Fecha : {now.strftime('%d-%b-%Y %H:%M')} hs \n")
        f.write(f"c Isotopo : {isotope} \n")
        f.write(f"c Flip_y : {int(flip_rows)} \n")
        f.write(f"c Flip_z : {int(flip_z)} \n")
        f.write("c ------------------------------------------------------  \n")
        f.write("c ------------------------------------------------------  \n")
        f.write("c ------------------------------------------------------  \n")
        f.write("c   \n")
        f.write("c Universos \n")

    def _write_universes(self, f, phantom_arr, dims, spacing):
        """
        Escribe universos MCNP.
        Cada indice phantom tiene su propio universo con material especifico.
        Universo 1 = aire (referencia para LIKE n BUT).
        SIN closure cells.
        """
        unique_vals = sorted(set(phantom_arr.flatten()))
        unique_vals = [v for v in unique_vals if v > 0]

        logger.info(f"  Universos a generar: {unique_vals}")

        # Universo 1 = aire (referencia)
        aire_info = self._phantom_to_mat.get(1, {"mid": 1, "rho": 0.001205})
        f.write(f"1 {aire_info['mid']} -{aire_info['rho']} -650 u=1 imp:p=1 imp:e=1 $ Aire\n")

        # Demas universos: like 1 but mat=<mid> rho=-<density>
        for v in unique_vals:
            if v == 1:
                continue  # ya escrito
            # Obtener material desde el mapa, con fallback a Tejido_blando (30)
            mat_info = self._phantom_to_mat.get(v, self._phantom_to_mat.get(30, {"mid": 30, "rho": 1.04}))
            mid = mat_info["mid"]
            rho = mat_info["rho"]
            seg_name = self._get_segment_name(v)
            f.write(f"{v} like 1 but mat={mid} rho=-{rho} u={v} imp:p=1 imp:e=1 $ {seg_name}\n")

    def _get_segment_name(self, phantom_idx):
        """Retorna el nombre del segmento para un indice phantom."""
        # Primero buscar en TS_SEGMENT_MAP
        for name, idx in TS_SEGMENT_MAP.items():
            if idx == phantom_idx:
                return name
        # Nombres especiales para indices comunes
        special_names = {
            30: "Tejido_blando",
            50: "Pulmon",
            80: "Hueso",
            90: "Higado",
            100: "Tumor",
        }
        if phantom_idx in special_names:
            return special_names[phantom_idx]
        return f"idx_{phantom_idx}"

    def _write_lattice(self, f, phantom_arr, dims, spacing):
        """
        Escribe lattice wrapper + fill data con RLE.
        Cell LATTICE_WRAPPER = fill wrapper, Cell LATTICE_CELL = lattice.
        Los numeros se calculan dinamicamente para evitar colision con indices phantom.
        SIN closure cells.
        NOTA: flips (Y/Z) ya aplicados en generate() antes de llegar aqui.
        """
        nx, ny, nz = dims

        # Calcular numeros de celda lattice dinamicamente (max phantom index + 1, +2)
        max_phantom_idx = int(np.max(phantom_arr))
        lattice_wrapper = max_phantom_idx + 1
        lattice_cell = max_phantom_idx + 2
        outside_cell = max_phantom_idx + 3

        # Lattice wrapper cells
        f.write(f"{lattice_wrapper} 0 -1 fill={lattice_wrapper} imp:p=1 imp:e=1\n")
        f.write(f"{lattice_cell} 0 -2 lat=1 u={lattice_wrapper} imp:p=1 imp:e=1\n")
        f.write(f"                              fill=0:{nx-1} 0:{ny-1} 0:{nz-1} \n")

        # Guardar para uso en _write_source
        self._lattice_wrapper = lattice_wrapper
        self._lattice_cell = lattice_cell

        # Fill data con RLE (sin flip, ya aplicado en generate())
        self._write_rle_fill(f, phantom_arr, nx, ny, nz)

        # Outside world cell
        f.write(f"{outside_cell} 0 1 imp:p=0 imp:e=0\n")
        f.write("\n")

    def _write_rle_fill(self, f, phantom_arr, nx, ny, nz):
        """
        Escribe fill de voxeles con RLE estilo MATLAB.
        NOTA: flips ya aplicados en generate(), no se pasan aqui.
        """

        col = 0
        line = "      "  # 6 espacios de indentacion

        def flush_run(r_val):
            nonlocal col, line
            if r_val >= 1:
                if r_val == 1:
                    token = " r"
                else:
                    token = f" {r_val}r"
                if col + len(token) > 72:
                    f.write(line.rstrip() + "\n")
                    line = "      "
                    col = 6
                line += token
                col += len(token)

        def write_val(val):
            nonlocal col, line
            token = f" {val}"
            if col + len(token) > 72:
                f.write(line.rstrip() + "\n")
                line = "      "
                col = 6
            line += token
            col += len(token)

        # Primer elemento fuera del loop
        first_val = int(phantom_arr[0, 0, 0])
        if first_val == 0:
            first_val = 1
        write_val(first_val)

        prev_val = first_val
        r = -1

        for k in range(nz):
            for j in range(ny):
                for i in range(nx):
                    val = int(phantom_arr[i, j, k])
                    if val == 0:
                        val = 1  # fuera del cuerpo = aire
                    if val == prev_val:
                        r += 1
                    else:
                        flush_run(r)
                        write_val(val)
                        r = 0
                    prev_val = val

        flush_run(r)
        f.write(line.rstrip() + "\n")

    def _write_surfaces(self, f, dims, spacing):
        """
        Escribe superficies: RPP bounding box + RPP voxel + SO 650 sphere.
        
        IMPORTANTE: Las dimensiones del RPP 1 deben coincidir EXACTAMENTE
        con las del mesh tally. Se usa precision de 6 decimales.
        """
        nx, ny, nz = dims
        sx, sy, sz = spacing  # mm
        
        # sx_cm: usado SOLO para RPP 2 (voxel unitario) y comentario
        sx_cm = sx / 10.0
        sy_cm = sy / 10.0
        sz_cm = sz / 10.0
        
        # xm, ym, zm: leidos de atributos compartidos (self._xm, _ym, _zm)
        # calculados UNA VEZ en generate() para garantizar coincidencia
        # EXACTA con _write_tallies (mismo objeto flotante, evita diferencias
        # de precision entre recalculos independientes)
        xm = self._xm
        ym = self._ym
        zm = self._zm

        f.write("c Superficies \n")
        f.write(f"c Tamano del voxel:  dx= {sx_cm:.6f} dy= {sy_cm:.6f} dz= {sz_cm:.6f} \n")
        f.write(f"c Tamano de la imagen:  [ {nx} {ny} {nz} ] \n")
        f.write("c\n")
        f.write(f"1   rpp  0.  {xm:.6f} 0.  {ym:.6f} 0.  {zm:.6f} \n")
        f.write(f"2   rpp  0.  {sx_cm:.6f} 0. {sy_cm:.6f} 0. {sz_cm:.6f} \n")
        f.write("650 so 15 \n")
        f.write("\n")

    def _write_mode(self, f, iso_data):
        """Escribe tarjetas de modo, phys y cut."""
        e_max = iso_data.get("e_max", 2.28)
        f.write("c\n")
        f.write("c MODDE \n")
        f.write("mode e p\n")
        f.write(f"phys:p {e_max} J J J J J J\n")
        f.write(f"phys:e {e_max} J J J J J J J J J J J J 0.99\n")
        f.write("cut:p J 1e-3\n")
        f.write("cut:e J 1e-3\n")

    def _write_source(self, f, pet_arr, dims, spacing, phantom_arr, iso_data):
        """
        Escribe fuente MCNP.
        SDEF con read file Y90cel3D.src + distribucion voxel si5/sp5.
        """
        nx, ny, nz = dims
        sx, sy, sz = spacing  # mm
        sx_cm = round(sx / 10.0, 4)
        sy_cm = round(sy / 10.0, 4)
        sz_cm = round(sz / 10.0, 4)

        # Determinar mascara de fuente: todos los voxeles no-aire
        non_air_mask = phantom_arr > 0

        if pet_arr is not None and pet_arr.sum() > 0:
            source_arr = pet_arr * non_air_mask
            active_idx = np.where((source_arr > 0) & non_air_mask)
            n_active = len(active_idx[0])

            if n_active == 0:
                logger.warning("No hay actividad PET, usando fuente uniforme")
                active_idx = np.where(non_air_mask)
                n_active = len(active_idx[0])
        else:
            active_idx = np.where(non_air_mask)
            n_active = len(active_idx[0])

        logger.info(f"  Fuente: {n_active} voxeles activos")

        f.write("c FUENTE \n")
        f.write("c sdef erg d1 x d2 y d3 z d4 cell d5  par e \n")
        f.write("sdef par=d1 wgt=1.00033788800193 erg=fpar=d6 x=d2 y=d3 z=d4 cell=d5\n")
        f.write("c\n")
        f.write("read file Y90cel3D.src\n")
        f.write("c\n")

        # Distribucion en el voxel
        f.write("c Distribucion en el voxel\n")
        f.write("c\n")
        f.write(f"si2 h 0. {sx_cm}\n")
        f.write("sp2 d 0 1\n")
        f.write(f"si3 h 0. {sy_cm}\n")
        f.write("sp3 d 0 1\n")
        f.write(f"si4 h 0. {sz_cm}\n")
        f.write("sp4 d 0 1\n")

        # Voxeles fuente (si5) — 2 columnas (2 tokens por linea)
        # Formato MATLAB: (u<lat[ix iy iz]<fill) donde:
        #   u = universo del voxel (phantom_idx)
        #   lat = lattice cell (self._lattice_cell)
        #   fill = fill cell (self._lattice_wrapper)
        f.write("c Voxeles Fuente\n")
        f.write(f"c Formato: (u<{self._lattice_cell}[ix iy iz]<{self._lattice_wrapper})\n")
        tokens = []
        for n in range(n_active):
            ix = active_idx[0][n]
            iy = active_idx[1][n]
            iz = active_idx[2][n]
            # Universo donde nace la particula = phantom index en ese voxel
            phantom_idx = int(phantom_arr[ix, iy, iz])
            tokens.append(f"({phantom_idx}<{self._lattice_cell}[{ix} {iy} {iz}]<{self._lattice_wrapper})")

        f.write("si5 l")
        n_written = 0
        for i in range(0, n_active, 2):
            if n_written > 0:
                f.write(" &\n")
                f.write("      ")
            f.write(f" {tokens[i]}")
            n_written += 1
            if i + 1 < n_active:
                f.write(f" {tokens[i+1]}")
                n_written += 1
        f.write("\n")

        # Pesos uniformes — 2 columnas (2 valores por linea, formato MCNP compacto)
        f.write("sp5")
        w = 1.0 / n_active if n_active > 0 else 1.0
        fmt_val = f"{w:.12e}"
        n_written = 0
        for i in range(0, n_active, 2):
            if n_written > 0:
                f.write(" &\n")
                f.write("      ")
            f.write(f" {fmt_val}")
            n_written += 1
            if i + 1 < n_active:
                f.write(f" {fmt_val}")
                n_written += 1
        f.write("\n")

        f.write(f"c Se generaron N fuentes: {n_active}\n")

    def _write_tallies(self, f, dims, spacing, iso_data):
        """
        Escribe talles TMESH.
        
        IMPORTANTE: Las dimensiones del mesh tally deben coincidir EXACTAMENTE
        con las del RPP 1 (bounding box). Se usan las dimensiones reales calculadas
        a partir de spacing * dims, con precision de 6 decimales.
        
        NOTA: Para garantizar coincidencia exacta con RPP, se usa el mismo calculo
        que en _write_surfaces: sx_cm = sx / 10.0, luego xm = nx * sx_cm.
        """
        nx, ny, nz = dims
        
        # xm, ym, zm: leidos de atributos compartidos (self._xm, _ym, _zm)
        # calculados UNA VEZ en generate() para garantizar coincidencia
        # EXACTA con _write_surfaces (mismo valor flotante, misma referencia)
        xm = self._xm
        ym = self._ym
        zm = self._zm

        f.write("c\n")
        f.write("c TALLY \n")
        f.write("c Tally de verificacion \n")
        f.write("c\n")
        f.write("c NOTA: CORA1/CORB1/CORC1 son keywords MCNP (coarse mesh axis),\n")
        f.write("c NO son comentarios. Las mayusculas evitan confusion visual.\n")
        f.write("c Equivalen a TMESH mesh tally (pedep = energia depositada).\n")
        f.write("tmesh \n")
        f.write("rmesh1:e   pedep \n")
        # NOTA CRITICA: CORA1/CORB1/CORC1 usan {nx}i NO {nx-1}i.
        # En MCNP, "0 Ni xmax" significa N intervalos (N bins).
        # Como hay nx voxeles en la geometria (lattice 0:nx-1),
        # necesitamos nx intervalos (= nx bins) para alineacion 1:1.
        # Si usabamos nx-1, el ultimo voxel quedaba fuera de alineacion.
        f.write(f"CORA1  0  {nx}i   {xm:.6f} \n")
        f.write(f"CORB1  0  {ny}i   {ym:.6f} \n")
        f.write(f"CORC1  0  {nz}i   {zm:.6f} \n")
        f.write("c\n")
        f.write("endmd \n")

    def _write_random_tallies(self, f, phantom_arr, dims, spacing,
                               patient_id="3Dosim",
                               n_liver=5, n_tumor=10,
                               flip_y=False, flip_z=False):
        """
        Genera *f8 point detectors aleatorios en higado y tumor.

        Replica f_genero_tally.m de MATLAB:
          - n_liver tallies en voxeles aleatorios de higado (phantom_idx=90)
          - n_tumor tallies en voxeles aleatorios de tumor (phantom_idx=100)
          - Compensa flips en Y/Z para coordenadas MCNP
          - fc18 con IDPatient y fecha
          - Numeracion: *f18, *f28, ..., *f{10+n}8

        Args:
            f: file handle
            phantom_arr: array 3D con indices phantom
            dims: (nx, ny, nz)
            spacing: (sx, sy, sz) en mm
            patient_id: identificador del paciente
            n_liver: cantidad de tallies en higado
            n_tumor: cantidad de tallies en tumor
            flip_y: si se aplico flip en Y
            flip_z: si se aplico flip en Z
        """
        import datetime
        nx, ny, nz = dims
        now = datetime.datetime.now()
        tally_num = 0

        f.write("c\n")
        f.write("c Tally de verificacion \n")
        f.write(f"fc18 IDPatient:  {patient_id}  Fecha: {now.strftime('%d-%b-%Y')}\n")

        # --- Tallies en Higado (phantom_idx=90) ---
        liver_indices = np.where(phantom_arr == 90)
        n_avail_liver = len(liver_indices[0])

        if n_avail_liver > 0 and n_liver > 0:
            n_actual = min(n_liver, n_avail_liver)
            selected = np.random.choice(n_avail_liver, size=n_actual, replace=False)
            for i in selected:
                tally_num += 1
                # Coordenadas MATLAB (1-based)
                mx, my, mz = (liver_indices[0][i] + 1,
                              liver_indices[1][i] + 1,
                              liver_indices[2][i] + 1)
                # Coordenadas MCNP (0-based) con compensacion de flip
                x1 = mx - 1
                if flip_y:
                    y1 = ny - my  # compensacion flip Y
                else:
                    y1 = my - 1
                if flip_z:
                    z1 = nz - mz  # compensacion flip Z
                else:
                    z1 = mz - 1
                cell_val = int(phantom_arr[liver_indices[0][i],
                                           liver_indices[1][i],
                                           liver_indices[2][i]])
                f.write(f"c *f{tally_num}8  MeV  Higado \n")
                f.write(f"c Posicion MATLAB  [{mx} {my} {mz}] \n")
                f.write(f"*f{tally_num}8:e (90 <102 [{x1} {y1} {z1}]) \n")

        # --- Tallies en Tumor (phantom_idx=100) ---
        tumor_indices = np.where(phantom_arr == 100)
        n_avail_tumor = len(tumor_indices[0])

        if n_avail_tumor > 0 and n_tumor > 0:
            n_actual = min(n_tumor, n_avail_tumor)
            selected = np.random.choice(n_avail_tumor, size=n_actual, replace=False)
            for i in selected:
                tally_num += 1
                mx, my, mz = (tumor_indices[0][i] + 1,
                              tumor_indices[1][i] + 1,
                              tumor_indices[2][i] + 1)
                x1 = mx - 1
                if flip_y:
                    y1 = ny - my
                else:
                    y1 = my - 1
                if flip_z:
                    z1 = nz - mz
                else:
                    z1 = mz - 1
                cell_val = int(phantom_arr[tumor_indices[0][i],
                                           tumor_indices[1][i],
                                           tumor_indices[2][i]])
                f.write(f"c *f{tally_num}8  MeV  Tumor\n")
                f.write(f"c Posicion MATLAB  [{mx} {my} {mz}] \n")
                f.write(f"*f{tally_num}8:e (100 <102 [{x1} {y1} {z1}]) \n")

    def _write_materials(self, f):
        """
        Escribe tarjetas de materiales MCNP desde TissueConfig.

        Formato MATLAB de referencia:
          c MATERIALES
          c Aire Dry (near sea level)
          c densidad [g/cm^3]:  0.001205
          c suma de composicion:  1
          m1          6000            -0.000124

        NOTA: las fracciones de masa se escriben NEGATIVAS (convencion MCNP).
        """
        f.write("c \n")
        f.write("c MATERIALES\n")
        f.write("c\n")

        # Construir mapa inverso: mid -> lista de indices phantom que lo usan
        # para poder acceder al nombre_matlab y densidad
        mid_to_tissue: dict[int, dict] = {}
        for t in self.config.get_all_tissues():
            mat = t.get("mcnp_material", {})
            if not mat:
                continue
            mid = int(mat["id"])
            mid_to_tissue[mid] = t

        # IDs de material realmente presentes en el phantom
        phantom_indices = sorted(set(self._phantom_to_mat.keys()))
        mat_ids_used: set[int] = set()
        for idx in phantom_indices:
            if idx == 0:
                continue
            info = self._phantom_to_mat.get(idx)
            if info:
                mat_ids_used.add(info["mid"])

        if not mat_ids_used:
            mat_ids_used = {1, 2}  # fallback: aire + tejido

        for mid in sorted(mat_ids_used):
            comp = self._compositions.get(mid)
            if not comp:
                logger.warning(f"Material m{mid} sin composicion definida, omitiendo")
                continue

            # Obtener metadata del tejido para esta mid
            tissue = mid_to_tissue.get(mid)
            if tissue:
                mat_name = tissue.get("name_matlab", tissue["name"])
                density = tissue["density_gcm3"]
            else:
                mat_name = f"Material_{mid}"
                density = 1.0

            # Calcular suma de composicion (valores absolutos)
            sum_comp = sum(abs(frac) for _, frac in comp)

            # Escribir bloque de comentarios + tarjeta M
            f.write(f"c {mat_name}\n")
            f.write(f"c densidad [g/cm^3]:  {density:.4f} \n")
            f.write(f"c suma de composicion:  {sum_comp:.4f} \n")
            # Formato MATLAB: m{id} + 1er elemento en la misma linea
            first_zaid, first_frac = comp[0]
            f.write(f"m{mid}          {first_zaid}            {-first_frac:.6f}\n")
            for zaid, frac in comp[1:]:
                f.write(f"          {zaid}            {-frac:.6f}\n")

    def _write_footer(self, f, n_particles):
        """Escribe RAND, DBCN, PRINT, PRDMP, NPS."""
        import random
        seed = random.randint(1, 99999999999999)
        stride = 1111152917

        f.write("c\n")
        f.write("c RAND \n")
        f.write(f"rand stride={stride} gen=2 seed= {seed} \n")
        f.write("c DBCN \n")
        f.write("dbcn 48j 1 \n")
        f.write("c \n")
        f.write("c PRINT \n")
        f.write("print -85 -86 -128\n")
        f.write("c PRDMP \n")
        f.write("PRDMP J 1e4 -1 1 1e4\n")
        f.write(f"NPS {n_particles} \n")


# Isotope data for source
ISOTOPE_DATA = {
    "Y-90": {
        "name": "Yttrium-90",
        "zaid": 39090,
        "half_life_days": 2.67,
        "e_max": 2.2807,
        "particle": "e",
        "mode": "e p",
    },
    "I-131": {
        "name": "Iodine-131",
        "zaid": 53131,
        "half_life_days": 8.02,
        "e_max": 0.606,
        "particle": "e",
        "mode": "e",
    },
    "Lu-177": {
        "name": "Lutetium-177",
        "zaid": 77177,
        "half_life_days": 6.65,
        "e_max": 0.498,
        "particle": "e",
        "mode": "e",
    },
    "Tc-99m": {
        "name": "Technetium-99m",
        "zaid": 43099,
        "half_life_days": 0.25,
        "e_max": 0.140,
        "particle": "p",
        "mode": "p e",
    },
}
