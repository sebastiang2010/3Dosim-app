# Dose-Volume Histogram (DVH)

> **Resumiendo la distribución espacial de dosis en una curva clínica.** El DVH acumulativo es la herramienta estándar en radioterapia y medicina nuclear para evaluar la calidad de un plan de tratamiento. Este documento describe el cálculo del DVH para el módulo de dosimetría de 3Dosim, los percentiles clínicos y los criterios de evaluación.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| DVH | Dose-Volume Histogram |
| ROI | Region of Interest |
| D98 | Dosis que cubre el 98% del volumen |
| D95 | Dosis que cubre el 95% del volumen |
| D70 | Dosis que cubre el 70% del volumen |
| D50 | Dosis que cubre el 50% del volumen (dosis mediana) |
| D5 | Dosis que cubre el 5% del volumen (~dosis máxima) |
| D2 | Dosis que cubre el 2% del volumen (~dosis máxima) |
| V30 | Porcentaje de volumen que recibe ≥ 30 Gy |
| V70 | Porcentaje de volumen que recibe ≥ 70 Gy |
| OAR | Organ at Risk (órgano en riesgo) |

---

## 1. Definición del DVH Acumulativo

El DVH acumulativo muestra, para cada dosis umbral $$D$$, el porcentaje del volumen de la ROI que recibe **al menos** esa dosis:

$$V(D) = \frac{1}{N}\sum_{i=1}^{N} [D_i \geq D] \times 100\%$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$V(D)$$ | Porcentaje de volumen con dosis ≥ $$D$$ | % |
| $$D$$ | Dosis umbral | Gy |
| $$D_i$$ | Dosis en el voxel $$i$$ | Gy |
| $$N$$ | Número total de voxeles en la ROI | — |
| $$[D_i \geq D]$$ | Indicador: 1 si cumple, 0 si no | — |

La función $$[ \cdot ]$$ es la función indicadora:

$$[D_i \geq D] = \begin{cases} 1 & \text{si } D_i \geq D \\ 0 & \text{si } D_i < D \end{cases}$$

### 1.1 Propiedades

- **Monótona decreciente**: $$V(D_1) \geq V(D_2)$$ si $$D_1 < D_2$$
- **$$V(0) = 100\%$$**: todo el volumen recibe al menos 0 Gy
- **$$V(D_{\max}) > 0\%$$**: el voxel de máxima dosis está incluido
- **$$V(D > D_{\max}) = 0\%$$**: ningún voxel supera la dosis máxima

---

## 2. Algoritmo de Cálculo

### 2.1 Parámetros

- **Número de puntos**: 200 (99 intervalos)
- **Rango**: de 0 a $$D_{\max} \times 1.05$$
- **Incluye voxeles con dosis = 0**: sí (percentiles sobre **todos** los voxeles)

### 2.2 Pasos

```
1. Obtener máscara binaria de la ROI desde la labelmap
2. Extraer dosis de todos los voxeles dentro de la máscara
3. Crear vector dosis_threshold = linspace(0, Dmax*1.05, 200)
4. Para cada umbral D:
     V(D) = 100 * sum(dosis_vox >= D) / len(dosis_vox)
5. Almacenar curva (D, V)
6. Extraer métricas: D98, D95, D70, D50, D5, D2, V30, V70
```

### 2.3 Implementación

```python
import numpy as np
from scipy import interpolate

def compute_dvh(dose_gy: np.ndarray,
                mask: np.ndarray,
                n_points: int = 200) -> dict:
    """
    Calcular DVH acumulativo para una ROI.

    Parameters
    ----------
    dose_gy : np.ndarray
        Mapa de dosis 3D en Gy.
    mask : np.ndarray (bool)
        Máscara binaria de la ROI.
    n_points : int
        Número de puntos del DVH (default: 200).

    Returns
    -------
    dict con:
        - 'dose_threshold': np.ndarray — dosis umbral (Gy)
        - 'volume_pct': np.ndarray — % volumen ≥ umbral
        - 'D98', 'D95', 'D70', 'D50', 'D5', 'D2': float (Gy)
        - 'V30', 'V70': float (% volumen)
        - 'mean_dose': float (Gy)
        - 'max_dose': float (Gy)
        - 'min_dose': float (Gy)
        - 'volume_cc': float (cm³)
    """

    # Extraer dosis de la ROI
    doses = dose_gy[mask > 0].ravel()

    # Volumen en cm³
    voxel_vol_cm3 = np.prod(spacing) / 1000.0  # si spacing está en mm
    volume_cc = len(doses) * voxel_vol_cm3

    if len(doses) == 0:
        return {'volume_cc': 0.0}

    dmax = np.max(doses)
    thresholds = np.linspace(0, dmax * 1.05, n_points)

    # DVH acumulativo (vectorizado)
    volume_pct = np.array([
        100.0 * np.sum(doses >= d) / len(doses)
        for d in thresholds
    ])

    # Métricas
    # Percentiles sobre TODOS los voxeles (incluyendo dosis = 0)
    # D98 = percentil 2 → el 98% del volumen recibe al menos esta dosis
    metrics = {
        'D98': float(np.percentile(doses, 2)),
        'D95': float(np.percentile(doses, 5)),
        'D70': float(np.percentile(doses, 30)),
        'D50': float(np.percentile(doses, 50)),
        'D5': float(np.percentile(doses, 95)),
        'D2': float(np.percentile(doses, 98)),
        'V30': float(100.0 * np.sum(doses >= 30) / len(doses)),
        'V70': float(100.0 * np.sum(doses >= 70) / len(doses)),
        'mean_dose': float(np.mean(doses)),
        'max_dose': float(dmax),
        'min_dose': float(np.min(doses)),
        'volume_cc': float(volume_cc),
    }

    return {
        'dose_threshold': thresholds,
        'volume_pct': volume_pct,
        **metrics,
    }
```

---

## 3. Métricas Clínicas

### 3.1 Percentiles de Dosis

| Métrica | Percentil | Significado clínico | ROI típica | Valor típico |
|---------|:---------:|---------------------|:-----------:|:------------:|
| D98 | 2% | Dosis mínima casi absoluta (hígado sano) | Hígado | > 30 Gy |
| D95 | 5% | Dosis mínima representativa | Tumor | > 100 Gy |
| D70 | 30% | Dosis de cobertura intermedia | Peritumoral | > 50 Gy |
| D50 | 50% | Dosis mediana | Todas | 30–200 Gy |
| D5 | 95% | Cuasi-máxima (punto caliente) | Tumor | < 300 Gy |
| D2 | 98% | Dosis máxima representativa | OAR | < 70 Gy (hígado sano) |

### 3.2 Volúmenes de Dosis

| Métrica | Significado | ROI | Valor típico |
|---------|-------------|:---:|:------------:|
| V30 (Liver) | % hígado sano que recibe ≥ 30 Gy | Hígado sano | < 50% |
| V70 (Liver) | % hígado sano que recibe ≥ 70 Gy | Hígado sano | < 20% |
| V100 (Tumor) | % tumor que recibe ≥ 100% dosis prescrita | Tumor | > 90% |

### 3.3 Tabla de Reporte

```
┌─────────────────────────────────────────────────────────────┐
│              RESUMEN DVH — 3Dosim v3.14                      │
├──────────────┬──────────┬──────────┬───────────┬────────────┤
│ Métrica      │ Hígado   │ Tumor    │ Peritumoral │ Body      │
├──────────────┼──────────┼──────────┼───────────┼────────────┤
│ D98 [Gy]     │   32.5   │  112.3   │   45.2    │    8.1     │
│ D95 [Gy]     │   45.1   │  145.6   │   58.7    │   12.3     │
│ D70 [Gy]     │   68.2   │  185.4   │   72.1    │   25.6     │
│ D50 [Gy]     │   42.3   │  165.2   │   55.8    │   15.4     │
│ D5 [Gy]      │   95.6   │  235.1   │   98.3    │   85.2     │
│ D2 [Gy]      │  102.1   │  248.7   │  102.5    │   92.1     │
│ V30 [%]      │   42.5   │  100.0   │   78.3    │   22.1     │
│ V70 [%]      │   15.3   │   95.2   │   35.6    │    5.2     │
│ Vol [cm³]    │  1234.5  │   45.2   │   89.1    │  25678.0   │
│ Media [Gy]   │   45.8   │  168.5   │   58.9    │   18.2     │
│ Máx [Gy]     │  108.9   │  255.3   │  108.9    │   98.5     │
└──────────────┴──────────┴──────────┴───────────┴────────────┘
```

---

## 4. Visualización del DVH

### 4.1 Colores por ROI

| ROI | Color | Código hex | Uso |
|-----|-------|:----------:|-----|
| Hígado | Azul | `#0000FF` | ROI principal de dosis hepática |
| Tumor | Rojo | `#FF0000` | ROI de respuesta tumoral |
| Peritumoral | Amarillo | `#FFFF00` | Borde de seguridad |
| Body | Verde | `#00AA00` | Cuerpo completo |

### 4.2 Escala Logarítmica

El eje Y (% volumen) se representa en **escala logarítmica** para visualizar mejor las dosis altas en volúmenes pequeños:

```
Y: % Volumen (log)     X: Dosis (Gy, lineal)
   100 ─
     │ \
     │  \
   10 ─   \_____
     │          \
     │           \
    1 ─           ────
     │
    0.1 ─
        └──────────────
        0  50  100  150
```

### 4.3 Integración en Slicer

1. Seleccionar módulo **Plots**
2. Crear `vtkMRMLPlotChartNode`
3. Agregar `vtkMRMLPlotSeriesNode` por cada ROI con:
   - `SetPlotType(vtkMRMLPlotSeriesNode::PlotTypeLine)
   - `SetXAxisName("Dosis [Gy]")
   - `SetYAxisName("Volumen [%]")
4. Forzar rango X con `SetXAxisRange(0, Dmax * 1.05)`

---

## 5. Validación contra MATLAB

| Métrica | MATLAB | Python | Tolerancia |
|---------|:------:|:------:|:----------:|
| Número de puntos | 200 | 200 | Idéntico |
| Percentiles | `prctile` | `np.percentile` | < 0.01% |
| V30, V70 | count ≥ / total | count ≥ / total | Idéntico |
| Incluye dosis = 0 | Sí | Sí | Idéntico |
| Escala Y | log | log | Idéntico |

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| DVH monótono decreciente | Pendiente positiva en algún punto |
| V(0) = 100% | V(0) ≠ 100% (error de máscara) |
| D98 < D95 < ... < D2 | Violación de orden de percentiles |
| V30 + V70 ≤ 110% | Suma inconsistente |
| Volumen ROI > 0 | Volumen = 0 (máscara vacía) |
| Dosis media dentro de rango | Media fuera de [min, max] |
| Puntos DVH continuos | Saltos > 10% en la curva |

---

## 7. Referencias

- Drzymala RE et al., "Dose-Volume Histograms", Int J Radiat Oncol Biol Phys (1991)
- ICRU Report 83: Prescribing, Recording, and Reporting Photon-Beam IMRT (2010)
- Dezarn et al., "Recommendations for Radioembolization Dosimetry", J Vasc Interv Radiol (2021)
- MATLAB `f_DVH.m` de 3Dosim v3.14 (`modulo_3/`)
- `dvh_analysis.py` en `SlicerDosimLib/`
