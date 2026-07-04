# Asignación de Materiales

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| HU | Hounsfield Units (unidades de atenuación radiológica) |
| ICRP | International Commission on Radiological Protection |
| ICRU | International Commission on Radiation Units |
| TS | TotalSegmentator |
| TOI | Tissue of Interest |
| Z | Número atómico |
| RLE | Run-Length Encoding |
| UD | Universe/Detail (tarjeta UD en MCNP lattice) |

## Contexto clínico

Cada voxel en el labelmap contiene un índice numérico que representa el
tejido biológico en esa posición. Para que MCNP pueda transportar
partículas correctamente, cada índice debe mapear a:

1. Una composición elemental (fracción en peso de cada isótopo)
2. Una densidad (en g/cm³)
3. Un rango de HU de referencia (opcional, para validación)

El sistema asigna materiales usando dos fuentes de datos en paralelo:

- **6 tejidos base** definidos localmente en `mcnp_materials.py`
- **53 materiales del ICRP-110** cargados desde `tissue_config.json`

## Mapeo de índices de segmento a material

### Índices de tejidos base (phantom, índices 1–100)

| Índice | Tejido | Densidad (g/cm³) | Rango HU | ID MCNP |
|--------|--------|:-----------------:|----------|:-------:|
| 1 | Aire (Dry near sea level) | 0.001205 | −1024 a −900 | 1 |
| 30 | Tejido blando (ICRU 44) | 1.06 | −200 a 150 | 2 |
| 50 | Pulmón (ICRP 110) | 0.50 | −900 a −200 | 4 |
| 80 | Hueso (ICRP 110) | 1.60 | 150 a 2000 | 5 |
| 90 | Hígado (ICRP 110) | 1.05 | 50 a 150 | 3 |
| 100 | Tumor | 1.05 | 50 a 150 | 6 |

### Índices ICRP-110 (completos, índices 101–153)

El archivo `tissue_config.json` contiene 53 materiales adicionales del
ICRP-110. Cada entrada tiene:

```json
{
  "index": 110,
  "name": "Hueso_vertebral",
  "name_en": "Trabecular_bone",
  "hu_range": [150, 300],
  "density_gcm3": 1.35,
  "mcnp_material": {
    "id": 10,
    "composition": {
      "1000": 0.074,
      "6000": 0.254,
      ...
    }
  }
}
```

La composición se expresa como fracción en peso de cada isótopo (Zzzzz
AAAA, por ejemplo `1000` = $^1$H, `6000` = $^{12}$C).

## Carga desde tissue_config.json

`TissueConfig.load_config()` en `config.py` parsea el JSON y construye:

```python
class TissueConfig:
    _instance = None
    tissues: list[TissueEntry]
    index_map: dict[int, TissueEntry]     # index → TissueEntry
    material_map: dict[int, TissueEntry]  # mcnp_material.id → TissueEntry

    @classmethod
    def load_config(cls, path=None):
        if cls._instance is None:
            cls._instance = cls()
            with open(path or "Resources/Config/tissue_config.json") as f:
                data = json.load(f)
            for t in data["tissues"]:
                cls._instance.index_map[t["index"]] = t
                cls._instance.material_map[t["mcnp_material"]["id"]] = t
        return cls._instance
```

## Segment Map (TotalSegmentator → índices locales)

La constante `TS_SEGMENT_MAP` en `mcnp_materials.py` mapea los nombres
de segmentos de TotalSegmentator a los índices del phantom:

```python
TS_SEGMENT_MAP = {
    "skin": 30,           # Tejido_blando
    "subcutaneous_fat": 30,
    "bone": 80,           # Hueso
    "rib": 80,
    "lung_upper_lobe_left": 50,   # Pulmón
    "lung_lower_lobe_left": 50,
    "lung_upper_lobe_right": 50,
    "lung_middle_lobe_right": 50,
    "lung_lower_lobe_right": 50,
    "liver": 90,          # Hígado
    # ...
}
```

Los nombres que no aparecen en el mapa se asignan por defecto a
Tejido_blando (30). El tumor (100) se asigna manualmente desde el
contorno delineado por el médico.

## Refinamiento por HU

Cuando `refine_hu=True`, el generador analiza la TC original en cada
voxel para ajustar el material según el valor de HU:

```
                ┌──────────────┐
                │  Voxel (i,j) │
                │  HU = valor  │
                └──────┬───────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
        HU en rango        HU fuera de rango
        del segmento       del segmento
              │                 │
              ▼                 ▼
        conserva índice   recalcular por HU
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
            HU ≈ Aire              HU ≈ Tejido
            índice=1               índice=30
```

Esto corrige errores de segmentación donde un voxel de aire quedó
clasificado como tejido por TotalSegmentator.

El refinamiento manual usa 3 categorías de umbral:

| Condición | Nuevo material | Rango HU |
|-----------|---------------|----------|
| `HU < -900` | Aire (1) | −1024 a −900 |
| `HU > 150` | Hueso (80) | 150 a 2000 |
| `HU >= -900` y `HU <= 150` | Tejido blando (30) | −900 a 150 |

## Asignación en mcnp_generator.py

El generador MCNP recorre el labelmap y asigna materiales voxel a voxel:

```python
def asignar_materiales(labelmap_node, tissue_config, refine_hu):
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                idx = labelmap[i, j, k]
                if idx == 0:
                    continue  # vacío, se asigna después
                tejido = tissue_config.index_map.get(idx)
                if tejido is None:
                    idx = 30  # default: tejido blando
                if refine_hu:
                    hu = tc_data[i, j, k]
                    idx = refinar_por_hu(hu, idx)
                material_map[i, j, k] = idx
```

## Materiales en el input MCNP

Cada material único genera una tarjeta Mn en el bloque de datos:

```mcnp
M1    6000 0.000124  7000 0.755268  8000 0.231481  18000 0.012827  $ Aire
M2    1000 0.105     6000 0.143     7000 0.034     8000 0.708     $ Tejido_blando
      11000 0.002    15000 0.003    16000 0.003    17000 0.002
      19000 0.003
M3    1000 0.102     6000 0.131     7000 0.031     8000 0.724     $ Higado
...
M53   ...                                                          $ ICRP-110 (53)
```

Las densidades se aplican en la celda correspondiente:

```mcnp
100 1 -0.001205 -1 2 3 ...  $ Celda de aire (material 1, ρ=0.001205)
200 2 -1.06      -4 5 6 ...  $ Celda de tejido blando (material 2, ρ=1.06)
```

## Validación de materiales

Después de la generación se verifica:

- No hay voxels con índice 0 (sin asignar) dentro del body
- Todos los índices tienen un material M correspondiente
- Las densidades son físicamente plausibles
- Las composiciones suman 1.0 ± tolerancia

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| Mapa TS_SEGMENT_MAP completo | Segmento sin mapeo |
| Índices labelmap válidos (1 a 153) | Índice 0 o > 153 |
| Densidad física (> 0, < 20 g/cm³) | ρ ≤ 0 o ρ ≥ 20 |
| Composición suma ~1.0 | |Σ fracciones − 1| > 1e-4 |
| Refinamiento HU produce cambios plausibles | > 50% voxels recategorizados |
| Archivo tissue_config.json cargable | Parse error |

## Referencias

- ICRP Publication 110: Adult Reference Computational Phantoms, Ann.
  ICRP 39(2), 2009
- ICRU Report 44: Tissue Substitutes in Radiation Dosimetry, 1989
- Schneider et al., "Correlation between CT numbers and tissue
  parameters needed for Monte Carlo simulations", PMB 45(2), 2000
- tissue_config.json, 3Dosim_v4, 2537 líneas con 59 entradas de material
