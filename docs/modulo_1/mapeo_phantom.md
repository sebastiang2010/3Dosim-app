# Mapeo TotalSegmentator → Phantom 3Dosim

> **TotalSegmentator produce 104 clases anatómicas con etiquetas numéricas (labels 1-126). El phantom 3Dosim usa un sistema de índices diferente (30=tejido blando, 50=pulmón, 80=hueso, 90=hígado, 100=tumor, 101-153=materiales ICRP-110).** Este paso convierte la segmentación TS a la representación interna del pipeline mediante una tabla de lookup (`ts_label_to_phantom` en `tissue_config.json`), asignando a cada voxel el índice correcto para la generación de entrada MCNP (Módulo 2).

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| ICRP-110 | Publicación 110: phantoms computacionales de referencia |
| ICRU-44 | Reporte 44: composiciones de tejidos para dosimetría |
| MCNP | Monte Carlo N-Particle |
| TS | TotalSegmentator |

---

## 1. El Problema de la Correspondencia

TotalSegmentator asigna a cada estructura anatómica un número entero (label) entre 1 y 126. Por ejemplo:

| Label TS | Estructura |
|:--------:|------------|
| 1 | Bazo (spleen) |
| 2 | Pulmón izquierdo lóbulo superior |
| 5 | Hígado (liver) |
| 8 | Corazón (heart) |

Pero el phantom 3Dosim necesita un sistema de índices diferente, donde cada número identifica un **material MCNP** con densidad y composición elemental conocidas:

| Índice phantom | Tejido | Densidad [g/cm³] | Material MCNP |
|:--------------:|--------|:----------------:|:-------------:|
| 1 | Aire | 0.001205 | M1 |
| 30 | Tejido blando | 1.06 | M2 |
| 50 | Pulmón | 0.382 | M3 |
| 80 | Hueso | 1.92 | M4 |
| 90 | Hígado | 1.05 | M5 |
| 100 | Tumor | — | M6 |

El mapeo se define en el archivo `tissue_config.json`, sección `ts_label_to_phantom`.

---

## 2. Estructura de `tissue_config.json`

El archivo tiene tres secciones principales:

### 2.1 `ts_label_to_phantom`

Diccionario que mapea cada label de TS (1-126) al índice phantom correspondiente:

```json
"ts_label_to_phantom": {
    "1":  {"index": 30, "segment": "spleen", "material_es": "Tejido_blando"},
    "2":  {"index": 50, "segment": "lung_upper_lobe_left", "material_es": "Pulmon"},
    "3":  {"index": 50, "segment": "lung_upper_lobe_right", "material_es": "Pulmon"},
    "5":  {"index": 90, "segment": "liver", "material_es": "Higado"},
    "8":  {"index": 80, "segment": "heart", "material_es": "Hueso"},
    ...
}
```

### 2.2 `ts_body_labels`

Lista de labels TS que corresponden a tejido corporal genérico (músculos, piel, tejido conectivo). Se asignan al índice 30 (Tejido blando):

```json
"ts_body_labels": [63, 64, 65, 66, 67, 68, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]
```

### 2.3 `tissues`

Lista completa de 53+ tejidos con:

| Campo | Descripción | Ejemplo (hígado) |
|-------|-------------|:----------------:|
| `index` | Índice numérico único | 90 |
| `name` | Nombre en español | "Higado" |
| `name_en` | Nombre en inglés | "Liver" |
| `density_gcm3` | Densidad [g/cm³] | 1.05 |
| `hu_range` | Rango de HU característico | [40, 150] |
| `color` | Color RGBA para visualización | [0.8, 0.4, 0.1, 1.0] |
| `mcnp_material` | Composición elemental para MCNP | (ver §4) |

---

## 3. Algoritmo de Mapeo

```python
def _map_ts_to_phantom(arr, tissue_config):
    """
    Convierte un array de labels TS a índices del phantom 3Dosim.
    
    Parámetros:
        arr: np.ndarray — array 3D con labels TS (1-126)
        tissue_config: TissueConfig — singleton con la configuración
    
    Retorna:
        np.ndarray — array 3D con índices phantom
    """
    # Paso 1: Inicializar todo como aire (índice 1)
    phantom = np.ones(arr.shape, dtype=np.uint8)
    
    # Paso 2: Asignar tejido blando (30) a labels corporales
    body_labels = tissue_config.get_body_labels()
    body_mask = np.isin(arr, list(body_labels))
    phantom[body_mask] = 30
    
    # Paso 3: Asignar órganos específicos según mapping
    ts_mapping = tissue_config.get_ts_mapping()
    for ts_label, phantom_idx in ts_mapping.items():
        mask = (arr == ts_label)
        phantom[mask] = phantom_idx
    
    return phantom
```

**Orden de asignación**:
1. Todo es aire (1) por defecto
2. Labels corporales → tejido blando (30)
3. Órganos específicos → su índice phantom

Este orden garantiza que los órganos específicos sobrescriban el tejido blando genérico.

---

## 4. Composición MCNP por Tejido

Cada tejido en `tissue_config.json` incluye su composición elemental para la tarjeta `M` de MCNP:

```json
{
    "index": 90,
    "name": "Higado",
    "density_gcm3": 1.05,
    "mcnp_material": {
        "id": 5,
        "composition": {
            "1000": 0.105,     // Hidrógeno (H)
            "6000": 0.143,     // Carbono (C)
            "7000": 0.034,     // Nitrógeno (N)
            "8000": 0.708,     // Oxígeno (O)
            "11000": 0.003,    // Sodio (Na)
            "15000": 0.003,    // Fósforo (P)
            "16000": 0.003,    // Azufre (S)
            "17000": 0.002,    // Cloro (Cl)
            "19000": 0.002     // Potasio (K)
        }
    }
}
```

**Notación MCNP**: el número antes del punto es el Z (número atómico) seguido del peso atómico (`1000` = $^{1}$H, `6000` = $^{12}$C, `8000` = $^{16}$O). Los valores son fracciones atómicas.

---

## 5. Corrección de Bugs (Julio 2026)

Se detectaron y corrigieron errores en el mapeo donde 22 estructuras de tejido blando (densidad $\sim 1.05$ g/cm³) estaban incorrectamente asignadas a Hueso (densidad $1.92$ g/cm³) o Pulmón ($0.382$ g/cm³):

| Label TS | Estructura | Antes (BUG) | Ahora (CORRECTO) | Densidad correcta |
|:--------:|------------|:-----------:|:----------------:|:-----------------:|
| 63-68 | Vasos sanguíneos | Hueso (80) | Sangre (128) | 1.06 g/cm³ |
| 79 | Médula espinal | Hueso (80) | Tejido mixto (145) | 1.04 g/cm³ |
| 80-89 | Músculos (varios) | Hueso (80) | Tejido muscular (129) | 1.05 g/cm³ |
| 90 | Cerebro | Hueso (80) | Cerebro (132) | 1.04 g/cm³ |
| 15 | Esófago | Pulmón (50) | Esófago (144) | 1.05 g/cm³ |

**Impacto dosimétrico**: El bug causaba:
- Sobre-estimación de atenuación en vasos sanguíneos, médula espinal, músculos y cerebro (asignados como hueso, que atenúa más)
- Error de atenuación en esófago (asignado como pulmón, que atenúa menos)
- Distorsión de la dosis calculada por MCNP en el Módulo 2

La corrección se aplicó tanto en v4 como en v3.14 del pipeline.

---

## 6. Diagrama Conceptual

```
TotalSegmentator (104 clases)
Labels TS: 1-126
       │
       ▼
┌────────────────────────────────────────┐
│ Array TS: labels anatómicos            │
│                                        │
│  5   5   5   5   5   5   5   5         │ ← hígado (5)
│  5   5   5   5   5   5   5   5         │
│  1   1   1   1   1   1   5   5         │ ← bazo (1)
│  42  42  42  42  42  42  42  42       │ ← pulmón (42)
│  ...                                   │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ _map_ts_to_phantom()                   │
│                                        │
│ 1. phantom[:] = 1 (aire)               │
│ 2. body_labels → phantom = 30          │
│ 3. ts_mapping → phantom = índice       │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ Array Phantom: índices 3Dosim          │
│                                        │
│ 90  90  90  90  90  90  90  90        │ ← Hígado (90)
│ 90  90  90  90  90  90  90  90        │
│ 30  30  30  30  30  30  90  90        │ ← Tejido blando (30)
│ 50  50  50  50  50  50  50  50        │ ← Pulmón (50)
│  ...                                   │
└────────────────────────────────────────┘
```

---

## 7. Clase TissueConfig

Singleton que carga y cachea `tissue_config.json`:

| Método | Descripción |
|--------|-------------|
| `get_tissue(index)` | Retorna datos completos del tejido (nombre, densidad, HU, composición) |
| `get_tissue_density(index)` | Densidad [g/cm³] |
| `get_tissue_hu_range(index)` | Rango de HU [min, max] |
| `get_mcnp_material(index)` | Composición elemental para MCNP |
| `generate_mcnp_material_card(index)` | Genera tarjeta `M` completa para MCNP |
| `get_ts_mapping()` | Dict: label TS → índice phantom |
| `get_body_labels()` | Set de labels TS que son tejido corporal |
| `map_ts_to_phantom_label(ts_label)` | Convierte un label TS individual a índice phantom |

---

## 8. Control de Calidad

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Todos los labels TS mapeados | Sin labels TS sin correspondencia en el mapping | Warning (estructuras sin mapear → tejido blando) |
| Densidades vs HU | La densidad del índice asignado corresponde al rango HU del CT | Warning (discrepancia > 10%) |
| Integridad del phantom | Todos los índices esperados están presentes en la salida | Error si faltan |

---

## 9. Notas Técnicas

- El archivo `tissue_config.json` se encuentra en `SlicerDosim/Resources/Config/tissue_config.json`.
- La clase `TissueConfig` es un singleton: se instancia una vez y se cachea para todo el pipeline.
- El corazón (label TS 8) está mapeado como Hueso (80) en el config original por razones históricas del phantom. Su densidad ($\sim 1.05$ g/cm³) es similar al tejido blando, pero la categorización como hueso afecta la atenuación en MCNP. *Esto puede requerir revisión.*
- Si un label TS no está en el mapping, se asigna como tejido blando (30) — un valor seguro pero no necesariamente correcto.
