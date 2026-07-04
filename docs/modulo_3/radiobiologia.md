# Radiobiología: BED, EUD y EQD2

> **De la dosis física al efecto biológico.** La dosis absorbida en Gray no captura completamente el efecto biológico de la radiación, especialmente en terapias con radionúclidos de baja tasa de dosis como $$^{90}$$Y. Para cuantificar el efecto real sobre el tejido tumoral y sano, 3Dosim implementa tres modelos radiobiológicos estándar: BED (Biologically Effective Dose), EUD (Equivalent Uniform Dose) y EQD2 (Equivalent Dose in 2 Gy fractions).

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| BED | Biologically Effective Dose |
| EUD | Equivalent Uniform Dose |
| EQD2 | Equivalent Dose in 2 Gy fractions |
| LQ | Linear-Quadratic (modelo radiobiológico) |
| $$\alpha/\beta$$ | Relación de radiosensibilidad del tejido |
| NTCP | Normal Tissue Complication Probability |
| TCP | Tumor Control Probability |
| OAR | Organ at Risk |
| LDR | Low Dose Rate (radiación de baja tasa) |
| DRF | Dose Rate Factor (factor corrector por tasa de dosis) |

---

## 1. Biologically Effective Dose (BED)

### 1.1 Contexto

El modelo BED incorpora dos factores que la dosis física no captura:

1. **Reparación subletal** durante la irradiación prolongada (Y-90: días)
2. **Radiosensibilidad intrínseca** del tejido ($$\alpha/\beta$$)

### 1.2 Fórmula para BED en Terapia con Radionúclidos

Para radionúclidos con decaimiento exponencial (baja tasa de dosis continua):

$$\text{BED} = D + \frac{\lambda}{(\alpha/\beta)(\lambda + \mu)} \cdot D^2$$

| Variable | Descripción | Unidad | Valor |
|----------|-------------|:------:|:-----:|
| $$D$$ | Dosis física total | Gy | 10–200 |
| $$\lambda$$ | Constante de desintegración del isótopo | h$$^{-1}$$ | 0.0108 (Y-90) |
| $$\mu$$ | Tasa de reparación subletal del tejido | h$$^{-1}$$ | 0.28 |
| $$\alpha/\beta$$ | Relación de radiosensibilidad | Gy | 2.5 (hígado), 10 (tumor) |

### 1.3 Valores de $$\alpha/\beta$$

| Tejido | $$\alpha/\beta$$ [Gy] | Referencia |
|--------|:---------------------:|------------|
| Hígado (sano) | 2.5 | Dawson, 2002 |
| Tumor hepático | 10.0 | Tai, 2008 |
| Peritumoral | 2.5 | Asumido = hígado sano |
| Pulmón | 3.0 | Van Dyk, 1989 |
| Riñón | 2.5 | Emami, 1991 |
| Médula ósea | 2.0 | Fowler, 1989 |

### 1.4 Factor de Tasa de Dosis (DRF)

El término $$\frac{\lambda}{\lambda + \mu}$$ es el **factor de corrección por tasa de dosis**:

| Isótopo | $$\lambda$$ [h$$^{-1}$$] | DRF (hígado, $$\mu$$=0.28) | DRF (tumor, $$\mu$$=0.28) |
|:-------:|:------------------------:|:--------------------------:|:-------------------------:|
| $$^{90}$$Y | 0.0108 | 0.0371 | 0.0371 |
| $$^{177}$$Lu | 0.0018 | 0.0064 | 0.0064 |
| $$^{131}$$I | 0.0036 | 0.0127 | 0.0127 |
| HDR (EBRT) | ∞ | 1.0 | 1.0 |

### 1.5 Implementación

```python
import numpy as np

def compute_bed(dose_gy: np.ndarray,
                alpha_beta: float = 2.5,
                lambda_h: float = 0.0108,
                mu_h: float = 0.28) -> np.ndarray:
    """
    Calcular BED para terapia con radionúclidos.

    Parameters
    ----------
    dose_gy : np.ndarray
        Dosis física en Gy.
    alpha_beta : float
        Relación α/β del tejido (Gy).
    lambda_h : float
        Constante de desintegración (h⁻¹).
    mu_h : float
        Tasa de reparación subletal (h⁻¹).

    Returns
    -------
    bed : np.ndarray
        BED en Gy (unidades: Gy equivalentes).
    """
    drf = lambda_h / (lambda_h + mu_h)
    bed = dose_gy + drf / alpha_beta * dose_gy**2
    return bed
```

### 1.6 Ejemplo

Para $$D = 100$$ Gy en tumor ($$\alpha/\beta = 10$$):

$$\text{BED} = 100 + \frac{0.0108}{10 \times (0.0108 + 0.28)} \times 100^2$$

$$\text{BED} = 100 + \frac{0.0108}{10 \times 0.2908} \times 10000$$

$$\text{BED} = 100 + 0.3714 = 100.37\ \text{Gy}$$

Para $$D = 50$$ Gy en hígado ($$\alpha/\beta = 2.5$$):

$$\text{BED} = 50 + \frac{0.0108}{2.5 \times 0.2908} \times 2500$$

$$\text{BED} = 50 + 37.14 = 87.14\ \text{Gy}$$

| Dosis física | BED hígado (2.5) | BED tumor (10) |
|:------------:|:----------------:|:---------------:|
| 20 Gy | 22.97 Gy | 20.15 Gy |
| 50 Gy | 87.14 Gy | 50.37 Gy |
| 100 Gy | 248.6 Gy | 100.7 Gy |
| 150 Gy | 484.8 Gy | 151.1 Gy |
| 200 Gy | 795.5 Gy | 201.5 Gy |

---

## 2. Equivalent Uniform Dose (EUD)

### 2.1 Contexto

La EUD reduce una distribución de dosis no uniforme a una dosis uniforme equivalente que produce el mismo efecto biológico. Propuesta por Niemierko (1997):

$$\text{EUD} = \left(\sum_{i=1}^{N} v_i D_i^a\right)^{1/a}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$v_i$$ | Fracción de volumen del voxel $$i$$ | adimensional |
| $$D_i$$ | Dosis en el voxel $$i$$ | Gy |
| $$a$$ | Parámetro de volumen del tejido | adimensional |
| $$N$$ | Número total de voxeles | — |

### 2.2 Parámetro $$a$$

| Tejido | $$a$$ | Efecto |
|--------|:-----:|--------|
| Tumor | 1 | EUD = dosis media (efecto lineal) |
| Hígado (sano) | 11 | EUD ≈ dosis máxima (estructura en paralelo) |
| Peritumoral | 8 | Intermedio |
| Pulmón | 7 | Estructura en paralelo |
| Riñón | 7 | Estructura en paralelo |

### 2.3 Interpretación

- **$$a = 1$$**: EUD = dosis media aritmética
- **$$a \to +\infty$$**: EUD = dosis máxima (órgano en serie)
- **$$a \to -\infty$$**: EUD = dosis mínima (tumor con cold spots)

### 2.4 Implementación

```python
def compute_eud(dose_gy: np.ndarray,
                mask: np.ndarray,
                a: float = 1.0) -> float:
    """
    Calcular Equivalent Uniform Dose (EUD).

    Parameters
    ----------
    dose_gy : np.ndarray
        Mapa de dosis 3D en Gy.
    mask : np.ndarray (bool)
        Máscara binaria de la ROI.
    a : float
        Parámetro de volumen del tejido.

    Returns
    -------
    eud : float
        EUD en Gy.
    """
    doses = dose_gy[mask > 0].ravel()
    if len(doses) == 0:
        return 0.0

    if a == 0:
        # Límite: EUD = exp(mean(ln(D))) (media geométrica)
        return float(np.exp(np.mean(np.log(doses[doses > 0]))))

    voxel_weights = np.ones_like(doses) / len(doses)
    eud = np.sum(voxel_weights * (doses ** a)) ** (1.0 / a)
    return float(eud)
```

---

## 3. Equivalent Dose in 2 Gy fractions (EQD2)

### 3.1 Contexto

La EQD2 convierte cualquier esquema de dosis fraccionada (o en nuestro caso, dosis de radionúclido) a la dosis equivalente si se administrara en fracciones de 2 Gy, el estándar en radioterapia externa.

$$\text{EQD2} = \frac{\text{BED}}{1 + \frac{2}{\alpha/\beta}}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| BED | Dosis biológica equivalente calculada previamente | Gy |
| $$\alpha/\beta$$ | Relación de radiosensibilidad del tejido | Gy |
| 2 | Dosis por fracción en el esquema estándar | Gy |

### 3.2 Derivación

Partiendo de la fórmula general de BED para fraccionamiento:

$$\text{BED} = n \cdot d \left(1 + \frac{d}{\alpha/\beta}\right)$$

Para el esquema estándar (n fracciones de 2 Gy):

$$\text{BED}_{2\text{Gy}} = n \cdot 2 \left(1 + \frac{2}{\alpha/\beta}\right) = \text{EQD2} \cdot \left(1 + \frac{2}{\alpha/\beta}\right)$$

Despejando EQD2:

$$\text{EQD2} = \frac{\text{BED}}{1 + \frac{2}{\alpha/\beta}}$$

### 3.3 Implementación

```python
def compute_eqd2(bed: np.ndarray, alpha_beta: float = 2.5) -> np.ndarray:
    """
    Calcular EQD2 desde BED.

    Parameters
    ----------
    bed : np.ndarray
        BED en Gy.
    alpha_beta : float
        Relación α/β del tejido (Gy).

    Returns
    -------
    eqd2 : np.ndarray
        EQD2 en Gy.
    """
    return bed / (1.0 + 2.0 / alpha_beta)
```

### 3.4 Ejemplos

| Dosis física | BED (hígado) | EQD2 (hígado, α/β=2.5) | BED (tumor) | EQD2 (tumor, α/β=10) |
|:------------:|:------------:|:---------------------:|:------------:|:-------------------:|
| 20 Gy | 22.97 Gy | 12.76 Gy | 20.15 Gy | 16.79 Gy |
| 50 Gy | 87.14 Gy | 48.41 Gy | 50.37 Gy | 41.98 Gy |
| 100 Gy | 248.6 Gy | 138.1 Gy | 100.7 Gy | 83.92 Gy |
| 150 Gy | 484.8 Gy | 269.3 Gy | 151.1 Gy | 125.9 Gy |
| 200 Gy | 795.5 Gy | 441.9 Gy | 201.5 Gy | 167.9 Gy |

---

## 4. Reporte Consolidado

```python
def compute_full_radiobiology(dose_gy: np.ndarray,
                               mask_liver: np.ndarray,
                               mask_tumor: np.ndarray,
                               mask_pretumor: np.ndarray) -> dict:
    """
    Calcular todos los índices radiobiológicos para las 3 ROIs.
    """

    rois = {
        'Hígado': (mask_liver, 2.5, 11),
        'Tumor': (mask_tumor, 10.0, 1),
        'Peritumoral': (mask_pretumor, 2.5, 8),
    }

    results = {}

    for name, (mask, alpha_beta, a_eud) in rois.items():
        doses = dose_gy[mask > 0]
        if len(doses) == 0:
            continue

        bed = compute_bed(doses, alpha_beta)
        eud = compute_eud(dose_gy, mask, a_eud)
        eqd2 = compute_eqd2(bed, alpha_beta)

        results[name] = {
            'mean_bed': float(np.mean(bed)),
            'max_bed': float(np.max(bed)),
            'min_bed': float(np.min(bed)),
            'eud': eud,
            'mean_eqd2': float(np.mean(eqd2)),
            'max_eqd2': float(np.max(eqd2)),
        }

    return results
```

---

## 5. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| BED ≥ D física | BED < D (error en fórmula LQ) |
| EUD dentro de [min(D), max(D)] | EUD fuera de rango |
| EQD2 ≤ BED (para α/β > 0) | EQD2 > BED |
| BED máximo < 1000 Gy | BED ≥ 1000 Gy (fuera de rango clínico) |
| EUD(hígado) ≤ D95(tumor) | EUD hígado > D95 tumor (biológicamente implausible) |
| Consistencia entre ROIs | BED(hígado) > BED(tumor) si D(liver) < D(tumor) |

---

## 6. Referencias

- Fowler JF, "The Linear-Quadratic Formula and Progress in Fractionated Radiotherapy", Br J Radiol (1989)
- Niemierko A, "Reporting and Analyzing Dose Distributions: A Concept of Equivalent Uniform Dose", Med Phys (1997)
- Dale RG, "The Application of the Linear-Quadratic Model to Fractionated and Continuous Radiotherapy", Br J Radiol (1985)
- Dawson LA, "Radiation-related Liver Disease", Int J Radiat Oncol Biol Phys (2002)
- Tai A et al., "α/β for Liver Tumors", Int J Radiat Oncol Biol Phys (2008)
- MATLAB `f_BED_EUD_EQD2.m` de 3Dosim v3.14 (`modulo_3/`)
- `radiobiology.py` en `SlicerDosimLib/`
