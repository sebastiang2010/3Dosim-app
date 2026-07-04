# Creación de Tumor (4 modos)

> **Para calcular la dosis en el tumor hepático, es necesario definir su contorno. El pipeline soporta 4 modos de creación de tumor, desde una esfera sintética hasta segmentación automática con IA.** Cada modo está diseñado para un escenario clínico diferente y se configura desde `pipeline_config.jsonc`. Opcionalmente, se crea un segmento de "hígado sano" como diferencia entre el hígado completo y el tumor.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| IA | Inteligencia Artificial |
| MCNP | Monte Carlo N-Particle |
| NIfTI | Neuroimaging Informatics Technology Initiative |
| PET | Positron Emission Tomography |
| ROI | Region of Interest |
| TS | TotalSegmentator |

---

## 1. Configuración

Todos los parámetros se definen en la sección `"tumor"` de `pipeline_config.jsonc`:

```jsonc
"tumor": {
    "mode": "synthetic",                    // synthetic | load_file | manual | ts_liver_lesions
    "synthetic_radius_mm": 10.0,            // radio de la esfera (synthetic)
    "liver_segment_name": "liver",          // nombre del segmento hepático en TS
    "create_healthy_liver": true,           // crear hígado_sano = hígado - tumor
    "load_file_path": "",                   // ruta NIfTI (load_file)
    "load_segment_name": "Tumor_Cargado",   // nombre (load_file)
    "manual_segment_name": "Tumor_Manual",  // nombre (manual)
    "ts_liver_lesions_segment_name": "Tumor_TS",  // nombre (ts_liver_lesions)
    "ts_liver_lesions_min_volume_cc": 1.0,  // volumen mínimo de lesión (ts_liver_lesions)
    "timeout_minutes": 0                    // timeout (0 = sin límite)
}
```

---

## 2. Modo 1: Synthetic (esfera sintética)

Crea una esfera de radio $R$ mm dentro del parénquima hepático. Útil para simulaciones y tests donde no se dispone de una segmentación tumoral real.

### Algoritmo

#### Paso 1: Extraer máscara hepática

Se extrae la máscara binaria del hígado desde la segmentación de TS.

$$M_{\text{hígado}}(x,y,z) = \begin{cases} 1 & \text{si TS}(x,y,z) = 5 \\ 0 & \text{en caso contrario} \end{cases}$$

#### Paso 2: Calcular centroide

$$c_i = \frac{1}{N} \sum_{n=1}^{N} i_n, \quad i \in \{x, y, z\}$$

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $c_x, c_y, c_z$ | Coordenadas del centroide del hígado | vox |
| $N$ | Número total de voxels hepáticos | — |
| $x_n, y_n, z_n$ | Coordenadas del $n$-ésimo voxel hepático | vox |

Si el centroide cae fuera del hígado (p.ej., hígado en forma de "C"), se busca el voxel hepático más cercano con distancia Euclídea.

#### Paso 3: Crear máscara esférica

$$d_{\text{mm}}(\mathbf{r}, \mathbf{c}) = \sqrt{(x-c_x)^2 s_x^2 + (y-c_y)^2 s_y^2 + (z-c_z)^2 s_z^2}$$

$$M_{\text{esfera}}(x,y,z) = \mathbb{1}\big[d_{\text{mm}}((x,y,z), (c_x,c_y,c_z)) \leq R\big]$$

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $d_{\text{mm}}$ | Distancia Euclídea en mm entre el voxel $(x,y,z)$ y el centroide | mm |
| $s_x, s_y, s_z$ | Espaciado del CT | mm |
| $R$ | Radio de la esfera (configurable) | mm |
| $\mathbb{1}[\cdot]$ | Función indicadora: $1$ si la condición es verdadera | — |

#### Paso 4: Intersectar con el hígado

$$M_{\text{tumor}} = M_{\text{esfera}} \cap M_{\text{hígado}}$$

Se asegura que el tumor quede completamente dentro del parénquima hepático.

#### Paso 5: Agregar como segmento

Se añade como segmento "Tumor_Sintético" con color rojo (RGB: $1.0, 0.0, 0.0$).

---

## 3. Modo 2: Load File (cargar NIfTI externo)

Carga un tumor pre-segmentado desde un archivo NIfTI. Util cuando se dispone de una segmentación realizada en otro software.

### Algoritmo

1. Cargar NIfTI con `slicer.util.loadNodeFromFile(path)`
2. Convertir a máscara binaria
3. Si las dimensiones no coinciden con el CT, re-muestrear con BRAINSResample usando interpolación **NearestNeighbor** (para preservar valores discretos)
4. Enmascarar dentro del hígado: $M_{\text{tumor}} = M_{\text{NIfTI}} \cap M_{\text{hígado}}$
5. Agregar como segmento con nombre configurable

### Parámetros

| Clave | Descripción |
|-------|-------------|
| `load_file_path` | Ruta absoluta al archivo NIfTI |
| `load_segment_name` | Nombre del segmento resultante |

---

## 4. Modo 3: Manual (Segment Editor)

El médico segmenta el tumor manualmente en Slicer usando las herramientas del módulo Segment Editor.

### Flujo

1. El pipeline crea un segmento vacío "Tumor_Manual" en la segmentación
2. Activa el módulo `Segment Editor` de Slicer
3. Muestra un diálogo **NO modal** con instrucciones
4. El médico dibuja el tumor con las herramientas disponibles:

| Herramienta | Uso |
|-------------|-----|
| **Paint** | Pintado manual con pincel de tamaño ajustable |
| **Scissors** | Recorte poligonal en un slice |
| **Level Tracing** | Segmentación por umbral local (basada en HU) |
| **GrowCut** | Segmentación semi-automática interactiva |

5. El médico hace clic en **APROBAR**
6. El pipeline extrae la máscara y continúa

---

## 5. Modo 4: TS Liver Lesions (automático con IA)

Usa el modelo `liver_lesions` de TotalSegmentator, entrenado en 842 sujetos con lesiones hepáticas.

### Algoritmo

1. Ejecutar TS con `task="liver_lesions"` sobre el CT
2. Cargar resultado como máscara binaria
3. Enmascarar dentro del hígado (phantom idx 90)
4. Post-procesamiento:
   - Etiquetar componentes conectadas (conectividad 26-vecina 3D)
   - Eliminar grupos con volumen $< V_{\min}$ cm³

$$V_{\text{componente}} = N_{\text{vox}} \cdot s_x \cdot s_y \cdot s_z \cdot 10^{-3} \quad [\text{cm}^3]$$

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $V_{\text{componente}}$ | Volumen de una componente conectada | cm³ |
| $N_{\text{vox}}$ | Número de voxels en la componente | — |
| $s_x, s_y, s_z$ | Espaciado del CT | mm |
| $10^{-3}$ | Conversión mm³ → cm³ | — |
| $V_{\min}$ | Volumen mínimo (default: $1.0$ cm³) | cm³ |

5. Agregar como segmento "Tumor_TS"

### Nota

El modelo `liver_lesions` **NO soporta** el modo `--fast`. Tiempo estimado: 10-30 minutos en CPU.

---

## 6. Hígado Sano

En todos los modos, si `create_healthy_liver: true`, se crea un segmento "higado_sano" como:

$$M_{\text{hígado\_sano}} = M_{\text{hígado}} \setminus M_{\text{tumor}}$$

Se agrega como segmento verde (RGB: $0.0, 1.0, 0.0$).

---

## 7. Diagrama General

```
Extraer hígado de segmentación TS (label 5)
       │
       ▼
┌──────────────────────────────────────────────────┐
│ Seleccionar modo según pipeline_config.jsonc     │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───┴──────────┐
│  │Synthetic  │  │Load File │  │ Manual   │  │TS Liver      │
│  │Esfera R mm│  │NIfTI ext │  │Segment   │  │Lesions IA    │
│  │Centroide  │  │Resample  │  │Editor    │  │842 sujetos   │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘
│        │              │             │               │
└────────┴──────────────┴─────────────┴───────────────┘
         │              │             │               │
         ▼              ▼             ▼               ▼
         ┌─────────────────────────────────────────┐
         │ Máscara binaria del tumor               │
         │ (intersección con hígado)               │
         └──────────────────┬──────────────────────┘
                            │
                            ▼
         ┌─────────────────────────────────────────┐
         │ Agregar segmento a segmentación Slicer   │
         │ Color: rojo (1.0, 0.0, 0.0)             │
         └──────────────────┬──────────────────────┘
                            │
                   ┌────────┴────────┐
                   ▼                 ▼
         ┌─────────────────┐  ┌─────────────────┐
         │ (opcional)      │  │ (continúa a     │
         │ Hígado sano     │  │ validación      │
         │ = hígado - tumor│  │ de tumor)       │
         │ Color: verde    │  │                 │
         └─────────────────┘  └─────────────────┘
```

---

## 8. Control de Calidad (AI Supervisor)

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Volumen del tumor $V_{\text{tumor}}$ | $V_{\text{tumor}} \geq 0.5$ cm³ | Warning si $< 0.5$ cm³ (tumor muy pequeño) |
| Tumor dentro del hígado | $M_{\text{tumor}} \subseteq M_{\text{hígado}}$ | Error si hay voxels fuera |
| Tumor no vacío | $N_{\text{vox,tumor}} > 0$ | Error si está vacío |
| Número de lesiones (TS) | $N_{\text{lesiones}} \geq 1$ | Warning si TS no detectó lesiones |

---

## 9. Notas Técnicas

- El centroide se calcula en coordenadas voxel (no en mm) y luego se convierte usando el espaciado del CT.
- Para el modo synthetic, la distancia Euclídea considera el espaciado real del CT para crear una esfera geométrica perfecta en mm (no una esfera distorsionada por voxels no cúbicos).
- El modo `ts_liver_lesions` requiere que el modelo esté instalado (viene con TotalSegmentator v2.13.0).
- Si `timeout_minutes > 0`, el pipeline espera ese tiempo máximo por la segmentación TS de lesiones. Si excede, continúa sin tumor.
