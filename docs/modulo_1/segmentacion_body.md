# Segmentación Corporal (Body)

> **La labelmap dosimétrica necesita un contorno externo que defina dónde termina el cuerpo del paciente y comienza el aire.** Este paso ejecuta TotalSegmentator con `task="body"` para obtener una máscara binaria del contorno externo, que luego se usa como "contenedor" en la exportación de labelmap: todos los voxeles dentro del cuerpo que no pertenecen a ningún órgano específico se asignan como tejido blando (índice 30), garantizando que no queden voxeles sin material asignado para la simulación MCNP.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| MCNP | Monte Carlo N-Particle |
| TS | TotalSegmentator |

---

## 1. ¿Por Qué es Necesaria la Segmentación Corporal?

La segmentación de órganos (TotalSegmentator task="total") produce 104 clases, pero no cubre **todos** los voxeles dentro del cuerpo. Quedan regiones sin asignar: tejido conectivo, piel, grasa subcutánea, pequeños vasos, etc. Si estos voxeles no tienen un material asignado, la simulación MCNP los tratará como aire, lo cual es incorrecto.

La segmentación body proporciona el **contorno externo** que permite asignar tejido blando genérico (índice 30) a todas las regiones corporales no cubiertas por órganos específicos.

---

## 2. Algoritmo

### Paso 1: Ejecutar TotalSegmentator task="body"

```python
from TotalSegmentator import TotalSegmentatorLogic

logic = TotalSegmentatorLogic()
logic.process(
    inputVolume=ct_node,
    outputSegmentation=body_seg_node,
    fast=True,
    cpu=True,
    task="body"
)
```

Se usa una configuración independiente (`totalsegmentator_config_body.jsonc`):

```jsonc
{
    "task": "body",
    "fast": true,
    "force_cpu": true,
    "subset": null
}
```

### Paso 2: Cargar resultado

Se crea un nodo `Body_Segmentation` separado (no se mezcla con el nodo de órganos de TS task="total").

### Paso 3: Fallback

Si TS falla, se registra un warning y el pipeline continúa sin body. En este caso, los voxeles sin asignar quedarán como aire (índice 1), lo que es incorrecto para MCNP.

---

## 3. Integración con la Labelmap

En `labelmap_exporter.py`, el body se incorpora al final del proceso de exportación:

```python
# Paso 1: Asignar todos los órganos (hígado, pulmón, etc.)
#         con sus índices phantom específicos (90, 50, etc.)
for seg_name, phantom_idx in organ_mapping.items():
    mask = extract_mask(seg_name)
    labelmap[mask] = phantom_idx
    any_organ[mask] = True

# Paso 2: Asignar body como tejido blando donde no hay órganos
body_mask = extract_mask(body_segmentation_node)
body_region = (body_mask > 0) & ~any_organ
labelmap[body_region] = 30  # Tejido_blando
```

**Prioridad**: los órganos específicos tienen prioridad sobre el body. La máscara `any_organ` garantiza que no haya solapamiento.

---

## 4. Tiempos de Ejecución

| Modo | GPU | CPU | Tiempo |
|------|:---:|:---:|:------:|
| fast | ✅ | — | 30 seg - 1 min |
| fast | — | ✅ | 1-3 minutos |

La tarea `body` es mucho más rápida que `total` porque solo produce una máscara binaria.

---

## 5. Diagrama de Flujo

```
CT original (misma geometría que el pipeline)
       │
       ▼
TotalSegmentator task="body"
       │
       ▼
Body_Segmentation node
(Máscara binaria: 1 = cuerpo, 0 = exterior)
       │
       ▼
labelmap_exporter:
       │
       ├── 1. Asignar órganos:
       │       hígado = 90, pulmón = 50,
       │       hueso = 80, tumor = 100, ...
       │
       ├── 2. Asignar body:
       │       body_region = (body_mask > 0) & ~any_organ
       │       labelmap[body_region] = 30
       │
       └── 3. Exportar:
               labelmap.nii (NIfTI)
               labelmap.nrrd (NRRD)
```

---

## 6. Ejemplo Visual

```
Slice axial sin body:
┌──────────────────────────────────────┐
│ Aire (índice 1)                      │
│         ┌──────────────────┐         │
│         │ Hígado (90)       │         │
│         │ Pulmón (50)       │         │
│         │ ┌───┐             │         │
│         │ │???│ ← Voxels    │         │
│         │ └───┘   sin       │         │
│         │         asignar   │         │
│         └──────────────────┘         │
└──────────────────────────────────────┘

Slice axial CON body:
┌──────────────────────────────────────┐
│ Aire (índice 1)                      │
│         ┌──────────────────┐         │
│         │ Hígado (90)       │         │
│         │ Pulmón (50)       │         │
│         │ ┌───┐             │         │
│         │ │30 │ ← Tejido    │         │
│         │ └───┘   blando    │         │
│         └──────────────────┘         │
└──────────────────────────────────────┘
```

---

## 7. Control de Calidad (AI Supervisor)

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Body contiene todos los órganos | Ningún órgano fuera de `body_mask` | Error si hay órganos fuera del body |
| Voxels sin asignar dentro del body | $N_{\text{sin-asignar}} = 0$ | Warning si hay voxels sin material dentro del body |
| Body no vacío | `sum(body_mask) > 0` | Error si la máscara está vacía |

---

## 8. Notas Técnicas

- La segmentación body **NO se mezcla** con la segmentación de órganos (son nodos Slicer separados).
- Si el body no está disponible, los voxeles sin asignar quedan como aire (índice 1), lo cual es incorrecto para MCNP porque esos voxeles deberían ser tejido. AI Supervisor emite un warning en este caso.
- En la verificación post-export, si se detectan voxeles sin asignar dentro del body, se asignan automáticamente como tejido blando (30).
- El body se ejecuta con `totalsegmentator_config_body.jsonc`, independiente de la configuración principal de TS, para permitir diferentes parámetros (ej: `fast=true` incluso si el task="total" se ejecutó en modo normal).
