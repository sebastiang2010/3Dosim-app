# TotalSegmentator — Segmentación Anatómica Automática

> **Segmentar manualmente 104 estructuras anatómicas en un CT abdominal tomaría horas a un radiólogo. TotalSegmentator (TS) automatiza completamente esta tarea usando una red neuronal nnU-Net entrenada en miles de tomografías.** Este paso ejecuta TS sobre el CT anonimizado, produciendo segmentaciones individuales para cada órgano, hueso, músculo y vaso, que luego serán mapeadas a materiales MCNP (Paso 9).

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| GPU | Graphics Processing Unit |
| IA | Inteligencia Artificial |
| nnU-Net | Arquitectura de red neuronal convolucional para segmentación 3D |
| TS | TotalSegmentator |

---

## 1. ¿Qué es TotalSegmentator?

TotalSegmentator (TS) es un segmentador anatómico basado en deep learning, desarrollado por Wasserthal et al. (2023). Utiliza una arquitectura **nnU-Net** que segmenta automáticamente 104 clases anatómicas a partir de un CT de tórax/abdomen. Está entrenado en una base de datos de miles de CTs con segmentaciones anotadas manualmente.

---

## 2. Tareas (Tasks) Disponibles

| Task | Descripción | Clases | Tiempo típico | Soporta --fast |
|------|-------------|:-----:|:-------------:|:--------------:|
| `total` | Todos los órganos y estructuras | 104 | 2-60 min | ✅ |
| `body` | Contorno externo del cuerpo | 1 | 1-3 min | ✅ |
| `body_lowdose` | Body para CT de baja dosis | 1 | 1-3 min | ✅ |
| `liver_lesions` | Lesiones hepáticas (tumores) | 1 | 10-30 min | ❌ |
| `lung_vessels` | Vasos pulmonares | 1 | 5-15 min | ❌ |

El pipeline usa:
- `task="total"` para la segmentación principal (Paso 7)
- `task="body"` para el contorno corporal (Paso 12)
- `task="liver_lesions"` como uno de los modos de creación de tumor

---

## 3. Configuración

```jsonc
{
    "task": "total",        // "total" | "body" | "liver_lesions"
    "fast": true,           // modo rápido (menos resolución, más rápido)
    "force_cpu": true,      // forzar CPU (false = usar GPU si disponible)
    "subset": null,         // subset de órganos (null = todos)
    "interactive": false    // modo interactivo
}
```

| Clave | Descripción | Valores |
|-------|-------------|---------|
| `task` | Tipo de segmentación | `"total"`, `"body"`, `"liver_lesions"` |
| `fast` | Modo rápido (usa menos resolución) | `true`, `false` |
| `force_cpu` | Forzar ejecución en CPU | `true`, `false` |
| `subset` | Subconjunto de órganos | `null` (todos) o array de nombres |

---

## 4. Ejecución

**Importante**: TS es un `ScriptedLoadableModule`, no un CLI module. NO debe ejecutarse con `slicer.cli.run()`. La API correcta es:

```python
from TotalSegmentator import TotalSegmentatorLogic

logic = TotalSegmentatorLogic()
logic.setupPythonRequirements()
logic.process(
    inputVolume=ct_node,        # CT anonimizado
    outputSegmentation=seg_node, # nodo de segmentación de salida
    fast=True,                   # modo rápido
    cpu=True,                    # forzar CPU
    task="total",                # segmentación completa
    interactive=False
)
```

### Progreso en Slicer

1. El pipeline cambia automáticamente al módulo "TotalSegmentator" para visibilidad
2. Muestra una barra QProgressDialog con mensajes de estado
3. Logs en tiempo real vía `logic.logCallback`

---

## 5. Clases Anatómicas Producidas (104 clases)

### Órganos
Hígado, pulmones (5 lóbulos: superior izquierdo, inferior izquierdo, superior derecho, medio derecho, inferior derecho), corazón, riñones, bazo, páncreas, vesícula biliar, estómago, duodeno, intestino delgado, colon, vejiga, próstata, tiroides, glándulas adrenales, tráquea, esófago.

### Huesos
Vértebras (C1-C7, T1-T12, L1-L5, S1), costillas (derechas e izquierdas), esternón, clavículas, escápulas, húmeros, fémures, pelvis (ilíaco derecho e izquierdo), cráneo, mandíbula.

### Músculos
Glúteos (mayor, medio), iliopsoas, autochthon (erector de la columna).

### Vasos
Aorta, vena cava inferior, arterias ilíacas (derecha, izquierda), venas ilíacas (derecha, izquierda), vena porta.

### Cerebro
Cerebro, cerebelo, tronco encefálico.

### Otros
Médula espinal, tejido subcutáneo, glándulas salivales (parótidas, submandibulares), cristalinos.

---

## 6. Tiempos de Ejecución

| Modo | GPU | CPU | Tiempo estimado |
|------|:---:|:---:|:---------------:|
| fast | ✅ | — | 2-5 minutos |
| fast | — | ✅ | 5-15 minutos |
| full | ✅ | — | 10-20 minutos |
| full | — | ✅ | 30-60 minutos |

El modo `--fast` reduce la resolución interna (remuestrea a 1.5 mm isotrópico) antes de segmentar, lo que acelera el procesamiento a costa de precisión submilimétrica.

---

## 7. Parches de Compatibilidad Python 3.9

Slicer 5.8.1 usa Python 3.9.10. TotalSegmentator v2.13.0 fue diseñado para Python 3.10+, por lo que requiere tres parches:

| # | Archivo | Parche | Razón |
|:-:|---------|--------|-------|
| 1 | `totalsegmentator/dicom_io.py` | Añadir `from __future__ import annotations` | La sintaxis `str \| None` requiere Python 3.10 |
| 2 | `nnunetv2/training/dataloading/data_loader.py` | Shim de `nnUNetDataLoader` → `nnUNetDataLoaderBase` | Cambio de nombre de clase entre versiones |
| 3 | `acvl_utils` | Forzar versión 0.2.5 | `blosc2>=3.0.0b4` no compila en Python 3.9 |

---

## 8. Diagrama de Flujo

```
CT anonimizado (512×512×N, 0.97 mm)
       │
       ▼
setupPythonRequirements()
(verifica/instala dependencias)
       │
       ▼
TotalSegmentatorLogic.process()
       │
       ├── Remuestrea CT → 1.5 mm isotrópico
       ├── Pasa por 5 modelos nnU-Net (2D + 3D)
       ├── Ensambla segmentaciones parciales
       └── Post-procesa: suavizado, eliminación de islas
       │
       ▼
TotalSegmentator_Seg node (vtkMRMLSegmentationNode)
┌─────────────────────────────────────────┐
│ liver:          ████████████████████████ │
│ lung_left:      ████████████████████████ │
│ lung_right:     ████████████████████████ │
│ kidney_left:    ████████████████████████ │
│ kidney_right:   ████████████████████████ │
│ heart:          ████████████████████████ │
│ spleen:         ████████████████████████ │
│ vertebra_L1:    ████████████████████████ │
│ ... (97 más)    ████████████████████████ │
└─────────────────────────────────────────┘
       │
       ▼
(continúa a Mapeo TS → Phantom)
```

---

## 9. Control de Calidad (AI Supervisor)

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Número de segmentos $N_{\text{seg}}$ | $N_{\text{seg}} \geq 20$ | Error si $< 20$ (indica fallo en TS) |
| Hígado presente | Segmento "liver" existe | Error si no (estructura crítica) |
| Pulmones presentes | Segmentos pulmonares existen | Warning si no |
| Tiempo de ejecución | $< 60$ min (modo normal) | Warning si excede |

---

## 10. Notas Técnicas

- La segmentación se guarda como un nodo `vtkMRMLSegmentationNode` que contiene 104 segmentos individuales, cada uno con su máscara binaria.
- Los segmentos se visualizan automáticamente con colores asignados por TS (personalizables en Slicer).
- Tras TS, se llama a `setup_medical_views()` para mostrar las segmentaciones en las vistas 3D.
- El nodo de segmentación se guarda en el checkpoint para restauración.
- Si TS falla (ej: memoria insuficiente), el pipeline se detiene con error. No hay fallback automático.
