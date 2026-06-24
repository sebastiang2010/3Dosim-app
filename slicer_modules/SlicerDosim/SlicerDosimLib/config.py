"""
Cargador de configuracion de tejidos para el phantom 3Dosim.

Lee tissue_config.json y provee acceso tipado a:
  - Indices, nombres, colores de cada tejido
  - Composiciones MCNP (material cards)
  - Mapping TotalSegmentator → phantom
  - Labels de cuerpo para tejido blando
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional


logger = logging.getLogger(__name__)


def _find_config_path() -> str:
    """
    Busca tissue_config.json relativo a la ubicacion de este modulo.
    Orden de busqueda:
      1. Junto a este archivo (./)
      2. ../../Resources/Config/ (estructura tipica Slicer)
      3. Variable de entorno 3DOSIM_TISSUE_CONFIG
    """
    # 1. Junto a config.py
    this_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(this_dir, "tissue_config.json"),
        os.path.join(this_dir, "..", "Resources", "Config", "tissue_config.json"),
        os.path.join(this_dir, "..", "..", "Resources", "Config", "tissue_config.json"),
        os.environ.get("3DOSIM_TISSUE_CONFIG", ""),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError(
        "tissue_config.json no encontrado. Buscado en: " + ", ".join(candidates)
    )


class TissueConfig:
    """Singleton que carga y provee configuracion de tejidos."""

    _instance: Optional["TissueConfig"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if self._loaded:
            return
        path = _find_config_path()
        with open(path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)

        self._by_index: dict[int, dict] = {}
        for t in self._raw.get("tissues", []):
            self._by_index[t["index"]] = t

        # TS mapping: keys como strings en JSON, convertir a int
        # Valores pueden ser int directo o dict con "index"
        ts_raw = self._raw.get("ts_label_to_phantom", {})
        self._ts_mapping: dict[int, int] = {}
        for k, v in ts_raw.items():
            if isinstance(v, dict):
                self._ts_mapping[int(k)] = v["index"]
            else:
                self._ts_mapping[int(k)] = v

        raw_body = self._raw.get("ts_body_labels", [])
        self._body_labels: set[int] = set(
            item["index"] if isinstance(item, dict) else item
            for item in raw_body
        )

        self._loaded = True
        logger.info(f"TissueConfig cargado: {len(self._by_index)} tejidos")

    # ------------------------------------------------------------------
    # ACCESO A TEJIDOS
    # ------------------------------------------------------------------

    def get_tissue(self, index: int) -> Optional[dict]:
        """Retorna dict del tejido por su indice 3Dosim, o None."""
        return self._by_index.get(index)

    def get_all_tissues(self) -> list[dict]:
        """Retorna lista de todos los tejidos."""
        return list(self._raw.get("tissues", []))

    def get_tissue_indices(self) -> list[int]:
        """Retorna indices disponibles."""
        return sorted(self._by_index.keys())

    def get_tissue_name(self, index: int) -> str:
        """Nombre en español del tejido."""
        t = self.get_tissue(index)
        return t["name"] if t else f"Desconocido_{index}"

    def get_tissue_color(self, index: int) -> tuple[float, float, float]:
        """Color RGB del tejido."""
        t = self.get_tissue(index)
        if t:
            c = t["color"]
            return (float(c[0]), float(c[1]), float(c[2]))
        return (0.5, 0.5, 0.5)

    def get_tissue_density(self, index: int) -> float:
        """Densidad en g/cm3."""
        t = self.get_tissue(index)
        return float(t["density_gcm3"]) if t else 1.0

    def get_tissue_hu_range(self, index: int) -> tuple[int, int]:
        """Rango de HU."""
        t = self.get_tissue(index)
        if t:
            r = t["hu_range"]
            return (int(r[0]), int(r[1]))
        return (-1024, 2000)

    def get_stats_key(self, name: str) -> str:
        """Convierte nombre de tejido a key para estadisticas.
        Ej: 'Higado' -> 'liver_vol_ml', 'Tejido_blando' -> 'soft_tissue_vol_ml'
        """
        name_map = {
            "Aire": "air_vol_ml",
            "Tejido_blando": "soft_tissue_vol_ml",
            "Pulmon": "lung_vol_ml",
            "Hueso": "bone_vol_ml",
            "Higado": "liver_vol_ml",
            "Tumor": "tumor_vol_ml",
        }
        return name_map.get(name, f"{name.lower()}_vol_ml")

    # ------------------------------------------------------------------
    # MATERIALES MCNP
    # ------------------------------------------------------------------

    def get_mcnp_material(self, index: int) -> Optional[dict]:
        """Retorna config de material MCNP para el tejido, o None."""
        t = self.get_tissue(index)
        return t["mcnp_material"] if t else None

    def get_mcnp_material_id(self, index: int) -> int:
        """ID numerico del material MCNP."""
        mat = self.get_mcnp_material(index)
        return int(mat["id"]) if mat else 0

    def get_mcnp_composition(self, index: int) -> dict[str, float]:
        """Composicion elemental: {ZAID: mass_fraction}."""
        mat = self.get_mcnp_material(index)
        return dict(mat["composition"]) if mat else {}

    def generate_mcnp_material_card(self, index: int) -> str:
        """
        Genera tarjeta MCNP para el material del tejido.
        Formato: M<id>  <zaid1> <frac1>  <zaid2> <frac2> ...
        """
        mat = self.get_mcnp_material(index)
        if not mat:
            return ""
        tid = mat["id"]
        comp = mat["composition"]
        parts = [f"M{tid}"]
        for zaid, frac in comp.items():
            parts.append(f"  {zaid}  {frac}")
        return "".join(parts)

    def generate_all_material_cards(self, indices: list[int]) -> list[str]:
        """Genera tarjetas M para todos los indices dados."""
        cards = []
        for idx in sorted(set(indices)):
            card = self.generate_mcnp_material_card(idx)
            if card:
                cards.append(card)
        return cards

    # ------------------------------------------------------------------
    # MAPPING TS -> PHANTOM
    # ------------------------------------------------------------------

    def get_ts_mapping(self) -> dict[int, int]:
        """Mapping: label de TotalSegmentator -> indice phantom."""
        return dict(self._ts_mapping)

    def get_body_labels(self) -> set[int]:
        """Labels TS que definen el cuerpo (tejido blando)."""
        return set(self._body_labels)

    def map_ts_to_phantom_label(self, ts_label: int) -> int:
        """Convierte un label de TS a indice phantom.
        Si no esta en el mapping explicito, verifica si es body_label -> 30,
        caso contrario -> 1 (aire).
        """
        if ts_label in self._ts_mapping:
            return self._ts_mapping[ts_label]
        if ts_label in self._body_labels:
            return 30
        return 1

    # ------------------------------------------------------------------
    # UTILIDADES
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Retorna el JSON completo como dict."""
        return dict(self._raw)


# ======================================================================
# CARGA DE CONFIGURACION UNIFICADA (config.jsonc)
# ======================================================================

_CONFIG_CACHE: Optional[dict] = None


def _find_unified_config_path() -> str:
    """
    Busca config.jsonc relativo a la ubicacion de este modulo.
    Misma logica que _find_config_path().
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(this_dir, "config.jsonc"),
        os.path.join(this_dir, "..", "Resources", "Config", "config.jsonc"),
        os.path.join(this_dir, "..", "..", "Resources", "Config", "config.jsonc"),
        os.environ.get("3DOSIM_CONFIG", ""),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    # Fallback: usar defaults
    return ""


def load_unified_config(force_reload: bool = False) -> dict:
    """
    Carga la configuracion unificada desde config.jsonc.

    Retorna dict con merge profundo de defaults + valores del archivo.
    Las funciones del pipeline pueden leer cualquier parametro via
    notacion de puntos: cfg["mcnp"]["isotope"], cfg["geometry"]["flip_z"], etc.

    Args:
        force_reload: Si True, recarga del archivo ignorando cache.

    Returns:
        dict con toda la configuracion del pipeline.
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not force_reload:
        return _CONFIG_CACHE

    import re

    # Valores por defecto completos
    defaults = {
        "paths": {
            "scene_output_dir": "C:/MAT/3Dosim/ai-pipe/scenes",
            "mcnp_output_dir": "C:/MAT/3Dosim/ai-pipe/mcnp_input",
            "labelmap_output_dir": "C:/MAT/3Dosim/ai-pipe/labelmaps",
            "results_dir_rel": "../resultados_test",
            "tissue_config_path": "",
            "source_file_path": "C:/MAT/3Dosim/ai-pipe/mcnp_input/Y90cel3D.src",
        },
        "segmentation": {
            "method": "simple",
            "totalsegmentator": {
                "task": "total",
                "fast": True,
                "force_cpu": True,
                "subset": None,
                "interactive": False,
            },
        },
        "geometry": {
            "flip_y": False,
            "flip_z": True,
        },
        "mcnp_source": {
            "isotope": "Y-90",
            "source_file": "Y90cel3D.src",
        },
        "mcnp_tallies": {
            "mesh_tally": True,
            "mesh_type": "pedep",
            "n_liver_tallies": 5,
            "n_tumor_tallies": 10,
        },
        "mcnp_materials": {
            "mapping_scheme": "sequential",
            "config_file": "tissue_config.json",
        },
        "mcnp_run": {
            "n_particles": 10000000,
            "refine_hu": False,
        },
        "views": {
            "layout": "ConventionalView",
            "pet_opacity": 0.35,
            "pet_colormap": "vtkMRMLColorTableNodeRainbow",
            "ct_window": 400.0,
            "ct_level": 40.0,
            "pet_window": 40.0,
            "pet_level": 20.0,
            "link_slices": True,
        },
        "pipeline": {
            "force_validation_on_restore": True,
            "auto_save_scene": True,
            "auto_screenshot": True,
            "git_prompt": True,
            "config_version": 2,
        },
    }

    config_path = _find_unified_config_path()
    if not config_path:
        logger.info("config.jsonc no encontrado — usando valores por defecto")
        _CONFIG_CACHE = defaults
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Remover comentarios // y /* */
        content = re.sub(r"//.*", "", content)
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        file_config = json.loads(content)

        # Merge profundo
        def deep_merge(base, override):
            result = base.copy()
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = deep_merge(defaults, file_config)
        _CONFIG_CACHE = merged
        logger.info(f"Config unificada cargada desde: {config_path}")
        return merged

    except Exception as e:
        logger.warning(f"Error cargando config.jsonc: {e} — usando defaults")
        _CONFIG_CACHE = defaults
        return defaults
