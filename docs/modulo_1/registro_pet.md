# Registro y Re-muestreo PET/CT

> **El PET y el CT se adquieren en equipos diferentes con geometrías distintas. Sin este paso, no existe correspondencia voxel a voxel entre la actividad metabólica (PET) y la anatomía (CT).** El PET (típicamente $200 \times 200 \times N$ con espaciado $\sim 4.07$ mm) se re-muestrea a la grilla del CT ($512 \times 512 \times N$ con $\sim 0.97$ mm), conservando la actividad total. El pipeline implementa tres métodos complementarios, con el primero como default.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| ASGD | Adaptive Stochastic Gradient Descent — optimizador de Elastix |
| BSpline | Basis Spline — función de interpolación polinómica por tramos |
| CLI | Command-Line Interface — interfaz de línea de comandos de Slicer |
| DOF | Degrees of Freedom — grados de libertad de una transformación |
| MI | Mutual Information — métrica de similitud entre imágenes |
| MSE | Mean Squared Error — error cuadrático medio |
| MAE | Mean Absolute Error — error absoluto medio |
| NCC | Normalized Cross-Correlation — correlación cruzada normalizada |
| RMSE | Root Mean Squared Error — raíz del error cuadrático medio |

---

## 1. El Problema Geométrico

El PET DICOM y el CT tienen geometrías fundamentalmente distintas:

| Parámetro | PET | CT |
|-----------|:---:|:--:|
| Dimensiones ($N_x \times N_y$) | $200 \times 200$ | $512 \times 512$ |
| Espaciado ($s_x, s_y$) [mm] | $4.07 \times 4.07$ | $0.976 \times 0.976$ |
| Espaciado axial ($s_z$) [mm] | $2.0$ | $3.0$ |
| Voxels por slice | $40,000$ | $262,144$ |
| Densidad de muestreo | $0.06$ vox/mm² | $1.05$ vox/mm² |

Para poder asignar la actividad PET a cada tejido identificado en el CT, es necesario re-muestrear el PET para que sus voxels coincidan exactamente con los del CT. La interpolación inevitablemente altera la suma total de actividad, por lo que se aplica un factor de conservación.

---

## 2. Notación General

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $V_{\text{PET}}$ | Volumen PET en coordenadas voxel IJK | — |
| $V_{\text{CT}}$ | Volumen CT en coordenadas voxel IJK | — |
| $T_{\text{PET}}$ | Transformación IJK→RAS del PET (matriz $4 \times 4$) | — |
| $T_{\text{CT}}$ | Transformación IJK→RAS del CT (matriz $4 \times 4$) | — |
| $\mathbf{r}_{\text{CT}}$ | Coordenada RAS de un voxel CT | mm |
| $s_x^{\text{CT}}$ | Espaciado del CT en X | mm |
| $s_y^{\text{CT}}$ | Espaciado del CT en Y | mm |
| $s_z^{\text{CT}}$ | Espaciado del CT en Z | mm |
| $o_x^{\text{PET}}$ | Origen RAS del PET en X | mm |
| $o_y^{\text{PET}}$ | Origen RAS del PET en Y | mm |
| $o_z^{\text{PET}}$ | Origen RAS del PET en Z | mm |

---

## 3. Método A — BRAINSResample (Default del Pipeline)

Es el método principal, usando el módulo CLI `BRAINSResample` de Slicer.

### 3.1 Parámetros

```python
slicer.cli.run(slicer.modules.brainsresample, None, {
    "inputVolume": pet_node,
    "referenceVolume": ct_node,
    "outputVolume": pet_registrado,
    "interpolationMode": "Linear",
    "pixelType": "float"
})
```

### 3.2 Opciones de Interpolación

| Método | Vecinos | Orden | Descripción | Uso típico |
|--------|:-------:|:-----:|-------------|------------|
| **NearestNeighbor** | 1 | 0 | Asigna el valor del voxel más cercano. No promedia, conserva valores discretos. | Labelmaps (segmentaciones) |
| **Linear** | 8 | 1 | Promedio ponderado trilineal de los 8 vecinos inmediatos. Suave, rápido. | PET, CT (default) |
| **BSpline** | 64 | 3 | Spline cúbico de 3er orden sobre un soporte de $4^3$ puntos. Curvas suaves, mayor carga computacional. | PET cuando se requiere suavizado |
| **Cubic** | 16 | 3 | Convolución cúbica (algoritmo de Keys) con 16 vecinos. Balance entre velocidad y suavidad. | Aplicaciones científicas |

### 3.3 Algoritmo

1. Para cada voxel $\mathbf{r}_{\text{CT}} = (x,y,z)$ en la grilla destino (CT), calcular su coordenada equivalente en el espacio PET:
   $$\mathbf{r}_{\text{PET}} = T_{\text{PET}}^{-1} \cdot T_{\text{CT}} \cdot \mathbf{r}_{\text{CT}}$$

2. Si $\mathbf{r}_{\text{PET}}$ cae fuera del volumen PET, asignar $0$.

3. Si cae dentro, interpolar el valor según el método elegido (Linear por defecto).

4. **Post-procesamiento**:
   - Clipear negativos: la interpolación puede producir valores ligeramente negativos → se fijan a $0$.
   - Conservar actividad (Ecuación de conservación, ver §6).

---

## 4. Método B — NumPy `map_coordinates`

Alternativa más exacta que replica el algoritmo MATLAB `register_v7.m`. No depende de Slicer.

### 4.1 Algoritmo

1. Extraer arrays numpy de PET y CT directamente.
2. Calcular grillas mundo para cada imagen:
   $$x_{\text{PET}}(i) = i \cdot s_x^{\text{PET}} + o_x^{\text{PET}}$$
   $$y_{\text{PET}}(j) = j \cdot s_y^{\text{PET}} + o_y^{\text{PET}}$$
   $$z_{\text{PET}}(k) = k \cdot s_z^{\text{PET}} + o_z^{\text{PET}}$$

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $x_{\text{PET}}(i)$ | Coordenada mundo RAS del voxel $i$ en X | mm |
| $i$ | Índice de voxel en la dimensión X (0 a $N_x-1$) | — |
| $s_x^{\text{PET}}$ | Espaciado del PET en X | mm |
| $o_x^{\text{PET}}$ | Origen del volumen PET en X | mm |

Análogamente para $y$ y $z$, y para el CT.

3. Para cada coordenada del CT, convertir a coordenada voxel PET:
   $$i_{\text{PET}} = \frac{x_{\text{CT}} - o_x^{\text{PET}}}{s_x^{\text{PET}}}$$

4. Interpolar con `scipy.ndimage.map_coordinates` con `order=1` (lineal).
5. Aplicar conservación de actividad.

---

## 5. Método C — Elastix (Registro Espacial)

El módulo `DosimetryRegistration` en `registration.py` provee **registro espacial** (no solo remuestreo) usando Elastix. Es útil cuando CT y PET no están alineados (movimiento del paciente entre adquisiciones).

| Método | Transformación | DOF | Optimizador |
|--------|---------------|:---:|-------------|
| BrainsFit | Rigid + Affine + BSpline | $6 + 6 + \text{vars}$ | 1500 iteraciones |
| Elastix rígido | Euler (3T + 3R) | $6$ | MI + ASGD |
| Elastix afín | Rígido + escala + shear | $12$ | MI + ASGD |
| Elastix BSpline | Rígido + BSpline no rígido | variables | MI + ASGD |

**Notación de DOF:**

| Símbolo | Descripción |
|:-------:|-------------|
| 3T | 3 traslaciones: $T_x, T_y, T_z$ (desplazamiento en mm) |
| 3R | 3 rotaciones: $R_x, R_y, R_z$ (ángulos en radianes) |
| 6 | Rigido (3T + 3R) |
| 12 | Afín (3T + 3R + 3 escalas + 3 shears) |
| MI | Mutual Information — métrica de similitud |
| ASGD | Adaptive Stochastic Gradient Descent — optimizador |

---

## 6. Conservación de la Actividad

La interpolación altera la suma total de actividad. Se aplica:

$$A_{\text{final}}(\mathbf{r}) = A_{\text{interp}}(\mathbf{r}) \cdot \frac{A_{\text{pre-resample}}}{A_{\text{post-resample}}}$$

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $A_{\text{final}}(\mathbf{r})$ | Actividad final corregida en el voxel $\mathbf{r}$ | Bq/mL |
| $A_{\text{interp}}(\mathbf{r})$ | Actividad del PET interpolado | Bq/mL |
| $A_{\text{pre-resample}}$ | Actividad total ANTES del remuestreo (desde DICOM raw) | Bq |
| $A_{\text{post-resample}}$ | Actividad total DESPUÉS del remuestreo | Bq |

El factor se aplica solo si difiere de $1.0$ en más de $0.001$. $A_{\text{pre-resample}}$ se obtiene de `pet_dicom_reader.read_pet_dicom_activity()` (ver [Calibración PET](./calibracion_pet.md)).

---

## 7. Métricas de Similitud (para evaluar calidad del registro)

| Métrica | Fórmula | Rango | Interpretación |
|:-------:|---------|:-----:|----------------|
| NCC | $\displaystyle \frac{\sum (A-\bar{A})(B-\bar{B})}{\sqrt{\sum (A-\bar{A})^2 \sum (B-\bar{B})^2}}$ | $[-1, 1]$ | $1$ = idénticas, $0$ = sin correlación |
| MSE | $\displaystyle \frac{1}{N}\sum (A-B)^2$ | $[0, \infty)$ | $0$ = idénticas |
| MI | $\displaystyle \sum_{a,b} p(a,b)\log\frac{p(a,b)}{p(a)p(b)}$ | $[0, \infty)$ | Mayor = más alineadas |
| MAE | $\displaystyle \frac{1}{N}\sum |A-B|$ | $[0, \infty)$ | $0$ = idénticas |
| RMSE | $\displaystyle \sqrt{\text{MSE}}$ | $[0, \infty)$ | $0$ = idénticas |

| Símbolo | Descripción |
|:-------:|-------------|
| $A, B$ | Imágenes PET y CT registradas (misma geometría) |
| $\bar{A}, \bar{B}$ | Medias de las imágenes $A$ y $B$ |
| $N$ | Número total de voxels |
| $p(a,b)$ | Distribución de probabilidad conjunta de intensidades |
| $p(a), p(b)$ | Distribuciones marginales de $A$ y $B$ |

---

## 8. Diagrama de Flujo General

```
PET nativo                         CT (geometría destino)
200×200×N, 4.07 mm                 512×512×N, 0.97 mm
       │                                    │
       │                                    │
       └──────────────┬─────────────────────┘
                      │
                      ▼
       ┌─────────────────────────────┐
       │ ¿Misma geometría?           │
       │ (dimensiones + espaciado)   │
       │                             │
       │ SÍ → saltar remuestreo      │
       │ NO → continuar              │
       └──────────────┬──────────────┘
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
┌──────────────────┐   ┌──────────────────────┐
│ BRAINSResample   │   │ map_coordinates      │
│ (default)        │   │ (NumPy, exacto)      │
│ Linear interp    │   │ order=1              │
│ Clipear negativos│   │                      │
└────────┬─────────┘   └──────────┬───────────┘
         │                        │
         └────────────┬───────────┘
                      │
                      ▼
       ┌──────────────────────────────┐
       │ PET registrado               │
       │ 512×512×N, 0.97 mm           │
       │                              │
       │ Conservación de actividad:   │
       │ PET_final = PET_interp       │
       │   × (A_orig / A_interp)      │
       └──────────────┬───────────────┘
                      │
                      ▼
         PET listo para fusión (Paso 5)
```

---

## 9. Control de Calidad (AI Supervisor)

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| NCC entre PET y CT | $> 0.6$ | Error si $< 0.6$ (mala alineación) |
| Conservación actividad | $|A_{\text{final}}/A_{\text{original}} - 1| < 0.01$ | Warning si difiere $>1\%$ |
| Dimensiones PET post-registro | $= 512 \times 512 \times N_{\text{CT}}$ | Error si no coincide con CT |
| Negativos post-interpolación | $= 0$ voxels negativos | Warning si hay negativos (se clipearon) |

---

## 10. Notas Técnicas

- La actividad se mide **antes** del resample (`self.pet_activity_before_resample`) desde DICOM raw con `pet_dicom_reader`, no desde el nodo Slicer.
- El resample con BRAINSResample puede producir valores negativos → se clipean a 0.
- Si el PET ya tiene la misma geometría que el CT (mismas dimensiones y espaciado), se salta el remuestreo.
- Elastix puede producir un archivo de transformación (`.tfm`) para aplicar a otros volúmenes adicionales.
- El registro espacial (Elastix/BrainsFit) es útil cuando CT y PET no están alineados por movimiento del paciente; el remuestreo BRAINSResample solo iguala la grilla asumiendo que ya están alineados.
