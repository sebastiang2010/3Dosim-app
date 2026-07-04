# Fusión CT+PET y Diálogo de Actividad

> **Después del registro, el PET está en la misma geometría que el CT. La fusión visual permite al médico verificar la alineación y examinar la distribución de actividad, mientras que el diálogo informativo proporciona los datos cuantitativos de actividad total que se usarán en el cálculo dosimétrico.** Este paso configura las vistas médicas de Slicer en layout 4-up y muestra un diálogo NO modal con información del paciente, metadatos de imagen y actividad calculada desde DICOM raw.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| FOV | Field of View |
| GBq | Gigabecquerel ($10^9$ Bq) |
| HU | Hounsfield Unit |
| mCi | Milicurie ($3.7 \times 10^7$ Bq) |
| MRB | Medical Reality Bundle (escena Slicer) |
| NCC | Normalized Cross-Correlation |
| PET | Positron Emission Tomography |

---

## 1. El Propósito de la Fusión

Tras el registro PET→CT (Paso 4), el PET está en la misma grilla que el CT. La fusión persigue tres objetivos:

1. **Verificación visual**: el médico comprueba que el PET esté correctamente alineado con el CT.
2. **Inspección de actividad**: se examina la distribución de $^{90}$Y en el hígado y posibles fugas (shunt pulmonar).
3. **Registro cuantitativo**: se muestran y guardan los valores de actividad total para su uso en los módulos 2 y 3.

---

## 2. Layout de Visualización 4-up

```
┌───────────────────────────┬───────────────────────────┐
│         AXIAL             │         SAGITAL           │
│   (corte transversal)     │   (corte sagital)         │
│                           │                           │
│   Background: CT          │   Background: CT          │
│   Foreground: PET         │   Foreground: PET         │
│   (opacidad 0.35)         │   (opacidad 0.35)         │
│   W/L: 400/40 HU          │   W/L: 400/40 HU          │
├───────────────────────────┼───────────────────────────┤
│         CORONAL           │          3D               │
│   (corte coronal)         │   (volumen rendering)     │
│                           │                           │
│   Background: CT          │   CT + PET + segmentos    │
│   Foreground: PET         │   (cuando estén           │
│   (opacidad 0.35)         │    disponibles)           │
│   W/L: 400/40 HU          │   RayCast rendering       │
└───────────────────────────┴───────────────────────────┘
```

---

## 3. Parámetros de Visualización

| Parámetro | Valor | Descripción |
|-----------|:-----:|-------------|
| Layout | `SlicerLayoutFourUpView` | 4 vistas simultáneas |
| Background (fondo) | CT o `CT_sin_camilla` | Imagen anatómica de referencia |
| Foreground (primer plano) | PET en Bq/mL | Actividad metabólica superpuesta |
| Opacidad del foreground | 0.35 (35%) | Permite ver el CT a través del PET |
| Window/Level CT | Level $L=40$ HU, Width $W=400$ HU | Ventana para abdomen |
| Window/Level PET | Percentiles $P_2$ a $P_{98}$ de valores $>0$ | Autoajuste dinámico |
| Colormap PET | Rainbow invertido | Azul (bajo) → cian → verde → amarillo → rojo (alto) |
| Volume Rendering 3D | RayCast | Para CT y PET simultáneamente |
| Slice Linking | Activado | Navegación sincronizada entre las 3 vistas |
| Focal point | Centro del paciente | Reset automático en vista 3D |

## 4. Fórmula del Window/Level

La transformación de valores HU a escala de grises en pantalla:

$$I_{\text{display}}(x) = \begin{cases}
0 & \text{si } x < L - W/2 \\
255 \cdot \frac{x - L + W/2}{W} & \text{si } L - W/2 \leq x \leq L + W/2 \\
255 & \text{si } x > L + W/2
\end{cases}$$

| Símbolo | Descripción | Valor típico abdomen | Unidades |
|:-------:|-------------|:--------------------:|:--------:|
| $I_{\text{display}}(x)$ | Valor de pixel en pantalla (escala de grises) | — | $0$ a $255$ |
| $x$ | Valor HU del voxel | $-1024$ a $+3000$ | HU |
| $L$ | Level (centro de la ventana) | $40$ | HU |
| $W$ | Width (ancho de la ventana) | $400$ | HU |
| $L - W/2$ | Límite inferior: todo lo menor se satura a negro | $-160$ | HU |
| $L + W/2$ | Límite superior: todo lo mayor se satura a blanco | $240$ | HU |

Para abdomen, la ventana $400/40$ HU resalta el contraste entre hígado ($\sim 40-60$ HU) y tejidos circundantes.

---

## 5. Diálogo de Fusión (Fusion Dialog)

### 5.1 Características

| Propiedad | Valor |
|-----------|-------|
| Modalidad | NO modal (`setModal(True)` + `dialog.exec()`) |
| Loop de eventos | `slicer.app.processEvents()` |
| Contenido | 5 secciones informativas (ver §5.2) |
| Acción del usuario | Cerrar el diálogo (no hay aprobación/rechazo) |

### 5.2 Secciones del Diálogo

1. **Paciente**: PatientID, peso (desde `pipeline_config.jsonc`)
2. **CT**: dimensiones $(N_x \times N_y \times N_z)$, espaciado $(s_x, s_y, s_z)$, nombre del nodo
3. **PET (DICOM raw)**: `RescaleType`, `RescaleSlope`, `RescaleIntercept` por slice, número de slices, volumen del voxel $V_{\text{voxel}}$ [mL]
4. **Actividad**:
   - $A_{\text{total}}$ [Bq], $A_{\text{GBq}}$, $A_{\text{mCi}}$
   - Media y máximo [Bq/mL]
   - Voxeles activos (con actividad $> 0$)
5. **Registro PET→CT**:
   - Método usado (BRAINSResample / NumPy / Elastix)
   - Duración del registro
   - Factor de conservación de actividad

### 5.3 Actividad desde DICOM Raw (no desde el nodo Slicer)

El pipeline **no confía** en el nodo Slicer para la actividad, porque Slicer aplica factores globales y no por slice.

Proceso (ver [Calibración PET](./calibracion_pet.md) para más detalle):

```
Por cada slice DICOM PET k:
  A_Bq/mL(i,j) = pixel_array_k(i,j) × m_k + b_k   (solo si τ_k == "BQML")
  A_Bq(i,j) = A_Bq/mL(i,j) × V_voxel              [mL → Bq]

Total:
  A_total = Σ A_Bq sobre todos los voxeles         [Bq]
  A_GBq   = A_total / 1e9                          [GBq]
  A_mCi   = A_total / 3.7e7                        [mCi]
```

---

## 6. Verificaciones de Calidad

| Verificación | Criterio | Indicador |
|-------------|:--------:|:---------:|
| Unidades PET | `RescaleType == "BQML"` | ✅/⚠️ |
| Rango de actividad | $0.1 \leq A_{\text{total}} \leq 50$ GBq | ✅/⚠️ |
| Dimensiones CT/PET | Similares tras registro | ✅/⚠️ |
| Voxeles activos | $N_{\text{activos}} > 100$ | ✅/⚠️ |
| Conservación actividad | $|A_{\text{post}}/A_{\text{pre}} - 1| < 0.01$ | ✅/⚠️ |

---

## 7. Diagrama General

```
Tras registro PET→CT (Paso 4)
       │
       ▼
┌─────────────────────────────────────┐
│ setup_medical_views(CT, PET, segs?) │
│                                     │
│ 1. Layout ConventionalView (4-up)   │
│ 2. Background = CT (W/L 400/40)    │
│ 3. Foreground = PET (opacidad 0.35) │
│ 4. Volume Rendering 3D RayCast     │
│ 5. Slice Linking ON                │
│ 6. Reset focal point               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ pet_dicom_reader.read_activity()    │
│ (lee DICOM raw, NO nodo Slicer)    │
│ → A_total, A_GBq, A_mCi, stats    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ show_fusion_info_dialog()           │
│ (NO modal)                          │
│                                     │
│ ├ Paciente: ID, peso               │
│ ├ CT: 512×512×N, 0.976 mm          │
│ ├ PET: BQML, slopes, slices        │
│ ├ Actividad: Bq, GBq, mCi, Bq/mL   │
│ └ Verificaciones: ✅/⚠️            │
└──────────────┬──────────────────────┘
               │
               ▼
      (continúa a anonimización)
```

---

## 8. Notas Técnicas

- El diálogo es **modal** (bloquea el pipeline hasta que el usuario lo cierre), a diferencia de los diálogos de validación médica que son NO modales.
- El rainbow invertido (`3Dosim_InvertedRainbow`) se crea automáticamente si no existe: azul → cian → verde → amarillo → rojo (frío = bajo, caliente = alto).
- Tras el diálogo se guarda `fusion_summary.txt` en el directorio de exportación con los valores numéricos.
- Para $^{90}$Y PET: actividad administrada típica $1$ a $5$ GBq, actividad en imagen $0.5$ a $3$ GBq (depende del tiempo post-administración).
- Si `patient_weight_kg` está configurado en `pipeline_config.jsonc`, se muestra en el diálogo y puede usarse para cálculos de SUV.
