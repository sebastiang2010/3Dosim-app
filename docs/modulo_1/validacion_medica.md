# Validación Médica

> **Hay decisiones que ningún algoritmo puede tomar. La validación médica es un punto de control obligatorio donde un médico especialista debe aprobar explícitamente cada etapa crítica del pipeline antes de continuar.** El pipeline tiene dos puntos de validación: uno tras la segmentación anatómica (TotalSegmentator) y otro tras la creación del tumor. Ambos usan diálogos NO modales que permiten al médico navegar las imágenes libremente mientras decide.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| PET | Positron Emission Tomography |
| TS | TotalSegmentator |

---

## 1. ¿Por Qué es Obligatoria la Validación Médica?

La segmentación automática con TotalSegmentator es excelente, pero no perfecta. Puede:
- Confundir estructuras anatómicas en CTs con artefactos
- No segmentar correctamente anatomías atípicas
- Incluir o excluir tejido patológico

El tumor creado por cualquier método (synthetic, carga, manual, IA) debe ser verificado porque:
- Un tumor mal ubicado produce una distribución de dosis incorrecta
- Un tumor demasiado grande o pequeño altera los índices dosimétricos (T/N, FU)

**Regla fundamental**: No existe "auto-approve" bajo ninguna circunstancia.

---

## 2. Validación de Segmentación (Paso 8)

Se ejecuta inmediatamente después de TotalSegmentator.

### Flujo

```
Tras TotalSegmentator (Paso 7)
       │
       ▼
setup_medical_views(segnode)  ← segmentaciones visibles en 3D
       │
       ▼
show_validation_dialog("segmentacion")
       │
       ├── APROBAR → continúa a creación de tumor
       └── RECHAZAR → pipeline detenido (RuntimeError)
```

### Qué puede hacer el médico

| Acción | Cómo |
|--------|------|
| Navegar slices axial/sagital/coronal | Scroll del mouse |
| Rotar vista 3D | Click + arrastrar en vista 3D |
| Ajustar opacidad del overlay PET | Slider (0-100%) |
| Examinar segmentaciones | Mostrar/ocultar segmentos individuales |
| Medir distancias | Herramienta de medición de Slicer |
| Cambiar window/level | Click derecho + arrastrar |

---

## 3. Validación de Tumor (Paso 10)

Se ejecuta después de crear el tumor (cualquier modo).

### Flujo

```
Tras crear tumor (Paso 9)
       │
       ▼
setup_medical_views(segnode)
       │
       ▼
show_tumor_validation_dialog(context=mode)
   (context: "sintetico" | "load_file" | "manual" | "ts_liver_lesions")
       │
       ├── APROBAR → continúa (hígado sano, body, labelmap)
       └── RECHAZAR → pipeline detenido
```

### Instrucciones contextuales

El diálogo muestra instrucciones específicas según el modo de creación:

| Modo | Instrucción |
|------|-------------|
| Synthetic | "Verifique que el tumor esférico (rojo) esté dentro del parénquima hepático" |
| Load File | "Verifique que el tumor cargado esté alineado correctamente con el CT" |
| Manual | "Use Segment Editor para dibujar el tumor. Luego apruebe." |
| TS Liver Lesions | "Revise las lesiones detectadas automáticamente por TS" |

---

## 4. Características Técnicas de los Diálogos

| Propiedad | Validación Segmentación | Validación Tumor |
|-----------|:----------------------:|:----------------:|
| Modalidad | NO modal | NO modal |
| Loop de eventos | `slicer.app.processEvents()` | `slicer.app.processEvents()` |
| Layout | 4 vistas automático | 4 vistas automático |
| Overlay PET | Slider opacidad 0-100% | Slider opacidad 0-100% |
| Botón aprobar | Verde ("APROBAR") | Verde ("APROBAR") |
| Botón rechazar | Rojo ("RECHAZAR") | Rojo ("RECHAZAR") |
| Consecuencia rechazo | `raise RuntimeError` | `raise RuntimeError` |

### Código

```python
def _do_validation(self, context="segmentacion"):
    from PipelineOrchestrator.validation import validate_segmentation
    result = validate_segmentation(
        ct_node=self.ct_node,
        pet_node=self.pet_node,
        seg_node=self.segmentation_node,
    )
    if not result:
        raise RuntimeError(f"Validación de {context} rechazada por el médico")
```

---

## 5. Diagrama General

```
┌─────────────────────────────────────────────────────────────┐
│                PUNTOS DE VALIDACIÓN MÉDICA                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Paso 7: TotalSegmentator                                   │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────┐                    │
│  │  VALIDACIÓN DE SEGMENTACIÓN         │                    │
│  │  (Paso 8 — obligatorio)            │                    │
│  │                                     │                    │
│  │  Médico revisa:                     │                    │
│  │  • 104 órganos segmentados          │                    │
│  │  • Hígado correcto                  │                    │
│  │  • Pulmones, huesos correctos       │                    │
│  │  • Sin artefactos                   │                    │
│  ├──────────────────┬──────────────────┤                    │
│  │  APROBAR → paso 9│ RECHAZAR → STOP  │                    │
│  └──────────────────┴──────────────────┘                    │
│       │                                                     │
│       ▼                                                     │
│  Paso 9: Creación de Tumor                                  │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────┐                    │
│  │  VALIDACIÓN DE TUMOR                │                    │
│  │  (Paso 10 — obligatorio)           │                    │
│  │                                     │                    │
│  │  Médico revisa:                     │                    │
│  │  • Tumor dentro del hígado          │                    │
│  │  • Tamaño adecuado                  │                    │
│  │  • Sin fuga a otros órganos         │                    │
│  ├──────────────────┬──────────────────┤                    │
│  │  APROBAR → paso 11│ RECHAZAR → STOP │                    │
│  └──────────────────┴──────────────────┘                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Respuesta del diálogo | APROBAR o RECHAZAR | Error si no hubo interacción |
| Tiempo en diálogo | $< 30$ min | Warning si excede |

---

## 7. Notas Técnicas

- La validación debe ejecutarse **incluso al restaurar checkpoints**. No se puede saltar aunque el paso esté marcado como "completed" en el checkpoint.
- El diálogo es NO modal específicamente para permitir al médico navegar las imágenes mientras decide. Si fuera modal, Slicer quedaría congelado y el médico no podría interactuar con las vistas.
- El loop `slicer.app.processEvents()` mantiene Slicer responsivo durante el diálogo NO modal.
- Si el pipeline se ejecuta en modo batch (sin interfaz gráfica), la validación médica falla porque no hay médico para aprobar. El pipeline debe ejecutarse dentro de Slicer con un usuario presente.
