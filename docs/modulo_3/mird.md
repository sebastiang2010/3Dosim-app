# Modelo MIRD de Partición

> **Estimación analítica de dosis media en hígado y tumor.** El modelo MIRD (Medical Internal Radiation Dose) de partición es un método simplificado para estimar la dosis media absorbida en el hígado sano y el tumor a partir de la actividad administrada y la relación de captación T/N (Tumor-to-Normal). Proporciona una verificación cruzada rápida contra los resultados del mapa de dosis 3D.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MIRD | Medical Internal Radiation Dose |
| T/N | Tumor-to-Normal uptake ratio |
| FU | Fractional Uptake (fracción de actividad captada) |
| SF | Shunt Fraction (fracción de derivación pulmonar) |
| ROI | Region of Interest |
| VOI | Volume of Interest |
| $$\rho$$ | Densidad tisular (g/cm³) |
| k | Constante MIRD del isótopo (J/s) |

---

## 1. Contexto Clínico

El modelo MIRD de partición fue propuesto originalmente para radioembolización hepática con $$^{90}$$Y-microesferas. Asume que:

1. La actividad se distribuye en **dos compartimentos**: hígado sano y tumor
2. La **captación relativa** T/N se mide por PET pre-tratamiento
3. La **derivación pulmonar** (SF) se mide por gammagrafía o PET
4. La dosis en cada compartimento es **uniforme** (aproximación)

### 1.1 Limitaciones

- No captura heterogeneidades espaciales de dosis (para eso está el mapa 3D)
- No considera actividad en otros órganos
- Asumes dosis uniforme dentro de cada compartimento

### 1.2 Uso en 3Dosim

El modelo MIRD se usa como:
- **Verificación rápida**: comparar dosis media MIRD vs. dosis media del mapa 3D
- **Planificación pre-tratamiento**: estimar actividad necesaria para alcanzar dosis objetivo
- **Reporte complementario**: incluir en el reporte PDF como referencia

---

## 2. Ecuaciones del Modelo

### 2.1 Relación T/N

$$T/N = \frac{\text{actividad\_PET\_tumor}}{\text{actividad\_PET\_higado}}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$T/N$$ | Relación de captación tumor / hígado sano | adimensional |
| $$\text{actividad\_PET\_tumor}$$ | Concentración media de actividad en tumor | Bq/cm³ |
| $$\text{actividad\_PET\_higado}$$ | Concentración media de actividad en hígado sano | Bq/cm³ |

### 2.2 Fracción de Captación (FU)

La actividad total administrada $$A$$ se distribuye entre hígado sano y tumor según:

$$\text{FU}_{\text{normal}} = (1 - \text{SF}) \frac{V_{\text{higado}}}{\frac{T}{N} \cdot V_{\text{tumor}} + V_{\text{higado}}}$$

$$\text{FU}_{\text{tumor}} = (1 - \text{SF}) \frac{\frac{T}{N} \cdot V_{\text{tumor}}}{\frac{T}{N} \cdot V_{\text{tumor}} + V_{\text{higado}}}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$\text{FU}_{\text{normal}}$$ | Fracción de actividad captada por hígado sano | adimensional |
| $$\text{FU}_{\text{tumor}}$$ | Fracción de actividad captada por tumor | adimensional |
| $$V_{\text{higado}}$$ | Volumen de hígado sano | cm³ |
| $$V_{\text{tumor}}$$ | Volumen de tumor | cm³ |
| $$\text{SF}$$ | Fracción de derivación pulmonar (0.0 – 0.2 típica) | adimensional |

**Verificación**: $$\text{FU}_{\text{normal}} + \text{FU}_{\text{tumor}} + \text{SF} = 1$$

### 2.3 Dosis Absorbida

$$D_{\text{higado}} = \frac{A \cdot k \cdot \text{FU}_{\text{normal}}}{m_{\text{higado}}}$$

$$D_{\text{tumor}} = \frac{A \cdot k \cdot \text{FU}_{\text{tumor}}}{m_{\text{tumor}}}$$

| Variable | Descripción | Unidad | Valor |
|----------|-------------|:------:|:-----:|
| $$A$$ | Actividad total administrada | GBq | 0.5 – 5.0 |
| $$k$$ | Constante MIRD del $$^{90}$$Y | J/s | 48.98 |
| $$m_{\text{higado}}$$ | Masa de hígado sano | kg | 1.0 – 2.0 |
| $$m_{\text{tumor}}$$ | Masa de tumor | kg | 0.01 – 0.5 |

### 2.4 Constante MIRD k

$$k = E_{\beta} \times 1.602\times10^{-13} \times 3600 \times 10^6$$

| Componente | Valor | Unidad | Descripción |
|-----------|:-----:|:------:|-------------|
| $$E_{\beta}$$ | 0.9337 | MeV | Energía media de la emisión beta del $$^{90}$$Y |
| $$1.602\times10^{-13}$$ | $$1.6\times10^{-13}$$ | J/MeV | Conversión de energía |
| $$3600$$ | 3600 | s/h | Factor de tiempo |
| $$10^6$$ | $$10^6$$ | — | Conversión GBq → Bq y kg → g |

$$k = 0.9337 \times 1.602\times10^{-13} \times 3600 \times 10^6 = 48.98\ \text{J/s}$$

---

## 3. Implementación

### 3.1 Algoritmo

```
1. Obtener volúmenes de hígado sano y tumor desde la labelmap
2. Calcular masas: m = V × ρ (ρ = 1.06 g/cm³ para ambos)
3. Obtener T/N desde PET:
   a. Actividad media en tumor (voxeles con label=100)
   b. Actividad media en hígado sano (label=90, excluyendo tumor)
   c. T/N = media_tumor / media_higado
4. Si no hay PET: T/N default = 3.0
5. Calcular FU_normal y FU_tumor
6. Calcular D_higado y D_tumor
```

### 3.2 Código Python

```python
import numpy as np

# Constantes
K_Y90 = 48.98           # J/s, constante MIRD Y-90
RHO_LIVER = 1.06        # g/cm³
RHO_TUMOR = 1.06        # g/cm³
DEFAULT_TN = 3.0        # T/N por defecto si no hay PET
DEFAULT_SF = 0.05       # Shunt fracción por defecto (5%)

def compute_mird_partition(activity_gbq: float,
                            labelmap: np.ndarray,
                            pet_activity: np.ndarray = None,
                            shunt_fraction: float = DEFAULT_SF,
                            tn_ratio: float = None,
                            voxel_volume_cm3: float = None) -> dict:
    """
    Calcular dosis media MIRD de partición para hígado y tumor.

    Parameters
    ----------
    activity_gbq : float
        Actividad total administrada en GBq.
    labelmap : np.ndarray
        Labelmap con índices phantom (90=hígado, 100=tumor).
    pet_activity : np.ndarray, optional
        Actividad PET en Bq/cm³ (para calcular T/N real).
    shunt_fraction : float
        Fracción de derivación pulmonar (0.0 – 0.2).
    tn_ratio : float, optional
        T/N ratio manual (si no se provee PET).
    voxel_volume_cm3 : float
        Volumen de un voxel en cm³.

    Returns
    -------
    dict con:
        - 'D_liver_gy': float — dosis media en hígado sano (Gy)
        - 'D_tumor_gy': float — dosis media en tumor (Gy)
        - 'FU_normal': float — fracción captada por hígado sano
        - 'FU_tumor': float — fracción captada por tumor
        - 'mass_liver_kg': float — masa de hígado sano (kg)
        - 'mass_tumor_kg': float — masa de tumor (kg)
        - 'TN_ratio': float — T/N utilizado
        - 'V_liver_cm3': float — volumen hígado sano (cm³)
        - 'V_tumor_cm3': float — volumen tumor (cm³)
    """

    # Volúmenes
    if voxel_volume_cm3 is None:
        voxel_volume_cm3 = 1.0  # placeholder

    v_liver_cm3 = np.sum(labelmap == 90) * voxel_volume_cm3
    v_tumor_cm3 = np.sum(labelmap == 100) * voxel_volume_cm3
    v_liver_healthy_cm3 = v_liver_cm3  # asumiendo hígado sano = hígado total - tumor

    if v_liver_healthy_cm3 == 0 or v_tumor_cm3 == 0:
        raise ValueError("Volumen de hígado o tumor es cero. "
                         "Verificar labelmap.")

    # Masas
    mass_liver_kg = v_liver_healthy_cm3 * RHO_LIVER / 1000.0
    mass_tumor_kg = v_tumor_cm3 * RHO_TUMOR / 1000.0

    # T/N ratio
    if tn_ratio is not None:
        tn = tn_ratio
    elif pet_activity is not None:
        act_tumor = pet_activity[labelmap == 100]
        act_liver = pet_activity[labelmap == 90]
        if len(act_tumor) > 0 and len(act_liver) > 0:
            tn = float(np.mean(act_tumor) / np.mean(act_liver))
        else:
            tn = DEFAULT_TN
    else:
        tn = DEFAULT_TN

    # Fracciones de captación
    denominator = tn * v_tumor_cm3 + v_liver_healthy_cm3
    fu_normal = (1 - shunt_fraction) * v_liver_healthy_cm3 / denominator
    fu_tumor = (1 - shunt_fraction) * tn * v_tumor_cm3 / denominator

    # Dosis (Gy = J/kg)
    d_liver = activity_gbq * K_Y90 * fu_normal / mass_liver_kg
    d_tumor = activity_gbq * K_Y90 * fu_tumor / mass_tumor_kg

    return {
        'D_liver_gy': float(d_liver),
        'D_tumor_gy': float(d_tumor),
        'FU_normal': float(fu_normal),
        'FU_tumor': float(fu_tumor),
        'mass_liver_kg': float(mass_liver_kg),
        'mass_tumor_kg': float(mass_tumor_kg),
        'TN_ratio': float(tn),
        'V_liver_cm3': float(v_liver_healthy_cm3),
        'V_tumor_cm3': float(v_tumor_cm3),
        'shunt_fraction': shunt_fraction,
    }
```

---

## 4. Implementación Actual en 3Dosim

La implementación actual del Módulo 3 **calcula la dosis media directamente desde el mapa 3D** y la reporta junto con los valores MIRD como verificación:

```python
# Dosis media real desde el mapa 3D
dose_liver_3d = np.mean(dose_gy[labelmap == 90])
dose_tumor_3d = np.mean(dose_gy[labelmap == 100])

# Dosis MIRD de partición (verificación)
mird = compute_mird_partition(activity_gbq, labelmap, pet_activity)

# Verificación: diferencia < 20%
diff_liver = abs(dose_liver_3d - mird['D_liver_gy']) / mird['D_liver_gy'] * 100
diff_tumor = abs(dose_tumor_3d - mird['D_tumor_gy']) / mird['D_tumor_gy'] * 100
```

---

## 5. Ejemplo Numérico

| Parámetro | Valor | Unidad |
|-----------|:-----:|:------:|
| Actividad total (A) | 3.5 | GBq |
| T/N (PET) | 4.2 | — |
| Shunt (SF) | 0.05 (5%) | — |
| Volumen hígado sano | 1234.5 | cm³ |
| Volumen tumor | 45.2 | cm³ |
| Masa hígado sano | 1.309 | kg |
| Masa tumor | 0.048 | kg |

**Cálculos:**

$$\text{FU}_{\text{normal}} = (1 - 0.05) \times \frac{1234.5}{4.2 \times 45.2 + 1234.5} = 0.95 \times 0.8667 = 0.823$$

$$\text{FU}_{\text{tumor}} = (1 - 0.05) \times \frac{4.2 \times 45.2}{4.2 \times 45.2 + 1234.5} = 0.95 \times 0.1333 = 0.127$$

$$D_{\text{higado}} = \frac{3.5 \times 48.98 \times 0.823}{1.309} = 107.8\ \text{Gy}$$

$$D_{\text{tumor}} = \frac{3.5 \times 48.98 \times 0.127}{0.048} = 453.2\ \text{Gy}$$

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| T/N > 1 | T/N ≤ 1 (tumor capta menos que hígado) |
| FU_total + SF ≈ 1 | FU_normal + FU_tumor + SF ≠ 1 (tolerancia 0.01) |
| FU dentro de [0, 1] | FU fuera de rango |
| Masa > 0 | Masa = 0 (volumen cero) |
| Dosis MIRD vs 3D < 20% | Diferencia ≥ 20% entre modelos |
| D_tumor > D_liver | D_tumor ≤ D_liver |
| SF en rango [0, 0.2] | SF > 0.2 o < 0 |
| Actividad > 0 | A = 0 (dosis cero) |

---

## 7. Referencias

- Loewinger R et al., "MIRD Primer for Absorbed Dose Calculations", Society of Nuclear Medicine (1991)
- Gulec SA et al., "Hepatic Radioembolization with Y-90 Microspheres", Semin Nucl Med (2008)
- Ho S et al., "Partition Model for Estimating Radiation Doses from Y-90 Microspheres", Eur J Nucl Med (1997)
- Dezarn et al., "Recommendations for Radioembolization Dosimetry", J Vasc Interv Radiol (2021)
- MATLAB `f_MIRD.m` de 3Dosim v3.14 (`modulo_3/`)
- `mird_partition.py` en `SlicerDosimLib/`
