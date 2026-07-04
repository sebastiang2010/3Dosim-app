# Conversión de MeV/cm³ a Gray

> **De la energía depositada por partícula a la dosis absorbida clínica.** Este documento detalla la fórmula exacta de conversión de los valores crudos del archivo MCTAL (MeV/cm³ por partícula fuente) a dosis absorbida en Gray (Gy), incluyendo las constantes físicas del $$^{90}$$Y, las densidades tisulares, y la diferencia crítica entre las rutas MCTAL y Kernel.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MCTAL | Archivo de resultados MCNP |
| Gy | Gray (J/kg) — unidad de dosis absorbida |
| MeV | Mega-electrón-voltio ($$1.6\times10^{-13}$$ J) |
| Bq | Becquerel (desintegraciones por segundo) |
| T½ | Período de semidesintegración |
| λ | Constante de desintegración |
| τ | Vida media (mean lifetime) |
| FFT | Fast Fourier Transform |
| ROI | Region of Interest |

---

## 1. Contexto Físico

MCNP simula el transporte de $$N$$ partículas (historias) y reporta la **energía depositada por partícula fuente** en MeV/cm³. Para obtener la dosis real en el paciente, se necesita:

1. **Dividir por densidad** ($$\rho$$) para convertir MeV/cm³ a MeV/g
2. **Convertir MeV a Joules** ($$1\ \text{MeV} = 1.6\times10^{-13}\ \text{J}$$)
3. **Escalar por la actividad real** del paciente (Bq)
4. **Multiplicar por el tiempo de integración** (vida media del isótopo)

---

## 2. Ruta MCTAL (Monte Carlo)

### 2.1 Fórmula Completa

$$D_{\text{Gy}} = \frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} \times \tau \times A \times 1000$$

| Variable | Descripción | Unidad | Valor típico |
|----------|-------------|--------|:------------:|
| $$D_{\text{Gy}}$$ | Dosis absorbida | Gy | 10 – 200 |
| $$D_{\text{raw}}$$ | Energía depositada por partícula fuente (MCTAL) | MeV/cm³ | $$10^{-6}$$ – $$10^{-3}$$ |
| $$\rho$$ | Densidad del tejido | g/cm³ | 0.001 – 1.92 |
| $$1.6\times10^{-13}$$ | Factor de conversión MeV → J | J/MeV | $$1.6\times10^{-13}$$ |
| $$\tau$$ | Vida media del $$^{90}$$Y | s | 332,916 |
| $$A$$ | Actividad total del paciente | Bq | $$10^9$$ – $$5\times10^9$$ |
| $$1000$$ | Factor g → kg (Gy = J/kg) | g/kg | 1000 |

### 2.2 Constantes del $$^{90}$$Y

| Parámetro | Símbolo | Fórmula | Valor | Unidad |
|-----------|:-------:|:-------:|:-----:|:------:|
| Período de semidesintegración | T½ | — | 64.1 | h |
| Constante de desintegración | $$\lambda$$ | $$\ln(2)/\text{T}_{1/2}$$ | 0.0108 | h$$^{-1}$$ |
| Vida media | $$\tau$$ | $$\text{T}_{1/2}/\ln(2)$$ | 92.48 | h |
| Vida media en segundos | $$\tau$$ | $$92.48 \times 3600$$ | 332,916 | s |
| Factor MeV → J | MEV2J | — | $$1.602\times10^{-13}$$ | J/MeV |
| Constante MIRD | k | $$E_{\beta} \times 1.602\times10^{-13} \times 3600 \times 10^6$$ | 48.98 | J/s |

### 2.3 Derivación Paso a Paso

$$D_{\text{raw}} [\text{MeV}/\text{cm}^3] \xrightarrow{\div \rho} \frac{D_{\text{raw}}}{\rho} [\text{MeV}/\text{g}]$$

$$\frac{D_{\text{raw}}}{\rho} [\text{MeV}/\text{g}] \xrightarrow{\times 1.6\times10^{-13}} \frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} [\text{J}/\text{g}]$$

$$\frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} [\text{J}/\text{g}] \xrightarrow{\times \tau A \times 1000} \frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} \times \tau \times A \times 1000\ [\text{J}/\text{kg} = \text{Gy}]$$

### 2.4 Densidades por Tejido

| Tejido | Índice phantom | $$\rho$$ [g/cm³] | Fuente |
|--------|:--------------:|:----------------:|--------|
| Aire | 1 | 0.001205 | ICRU-44 |
| Tejido blando | 30 | 1.06 | ICRP-110 |
| Pulmón | 50 | 0.382 | ICRP-110 |
| Hueso cortical | 80 | 1.92 | ICRP-110 |
| Hígado | 90 | 1.06 | ICRP-110 |
| Tumor | 100 | 1.06 | Asumido = hígado |
| Peritumoral | 200 | 1.06 | Asumido = hígado |
| Body (genérico) | — | 1.0 | ICRU-44 |

### 2.5 Implementación

```python
import numpy as np

# Constantes Y-90
T_HALF_H = 64.1          # horas
LAMBDA = np.log(2) / T_HALF_H  # h^-1
TAU = T_HALF_H * 3600 / np.log(2)  # 332916 s
MEV2J = 1.602e-13        # J/MeV

# Densidades (g/cm³)
DENSITY_MAP = {
    1: 0.001205,    # Aire
    30: 1.06,       # Tejido blando
    50: 0.382,      # Pulmón
    80: 1.92,       # Hueso
    90: 1.06,       # Hígado
    100: 1.06,      # Tumor
    200: 1.06,      # Peritumoral
}

def convert_mctal_to_gy(dose_raw: np.ndarray,
                        labelmap: np.ndarray,
                        activity_bq: float) -> np.ndarray:
    """
    Convertir dosis MCTAL (MeV/cm³) a Gy.

    Parameters
    ----------
    dose_raw : np.ndarray
        Energía depositada por partícula fuente [MeV/cm³].
    labelmap : np.ndarray
        Mapa de tejidos con índices phantom.
    activity_bq : float
        Actividad total del paciente [Bq].

    Returns
    -------
    dose_gy : np.ndarray
        Dosis absorbida [Gy].
    """

    # Crear mapa de densidad desde labelmap
    density = np.zeros_like(dose_raw, dtype=np.float32)
    for idx, rho in DENSITY_MAP.items():
        density[labelmap == idx] = rho

    # Evitar división por cero en aire
    density = np.maximum(density, 0.001)

    # Fórmula completa
    dose_gy = (dose_raw / density) * MEV2J * TAU * activity_bq * 1000.0

    # Aire → 0
    dose_gy[labelmap == 1] = 0.0

    return dose_gy
```

---

## 3. Ruta Kernel (Convolución FFT)

### 3.1 Diferencia Crítica

La ruta Kernel **NO multiplica por $$\tau$$ ni por $$A$$** después de la convolución porque el archivo `kernel.mat` **ya incluye** el factor $$\tau \times A$$.

### 3.2 Flujo Exacto MATLAB

```matlab
% MATLAB original (modulo_3/convkernel.m)
Kernel = Kernel / sum(Kernel(:));        % normalizar
DosisK = imfilter(A, Kernel, ...);       % convolución
DosisK = DosisK .* IND_liver_tumor;      % enmascarar
% NO hay DosisK * t   (τ ya incluido en kernel.mat)
```

donde:

- $$A$$ = actividad **en GBq** por voxel (`PET .* 1e-9`)
- `kernel.mat` incluye $$\tau \times 10^9$$ (vida media × GBq)
- `IND_liver_tumor` = máscara de hígado + tumor + peritumoral

### 3.3 Fórmula

$$D_{\text{Gy}} = \text{FFT}^{-1}\big[\text{FFT}(A_{\text{GBq}}) \cdot \text{FFT}(K_{\text{norm}})\big] \times \text{mask}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$A_{\text{GBq}}$$ | Actividad por voxel | GBq |
| $$K_{\text{norm}}$$ | Kernel normalizado (suma = 1) | 1/cm³ |
| $$\text{mask}$$ | Máscara binaria hígado+tumor+peritumoral | — |

### 3.4 Implementación

```python
def convolve_kernel(activity_gbq: np.ndarray,
                    kernel: np.ndarray,
                    mask: np.ndarray) -> np.ndarray:
    """
    Convolución FFT de actividad con kernel.

    Parameters
    ----------
    activity_gbq : np.ndarray
        Actividad en GBq por voxel.
    kernel : np.ndarray
        Kernel de dosis normalizado (suma = 1).
    mask : np.ndarray
        Máscara binaria de hígado+tumor+peritumoral.

    Returns
    -------
    dose_gy : np.ndarray
        Dosis absorbida en Gy (solo dentro de la máscara).
    """

    from scipy.signal import fftconvolve

    # Normalizar kernel
    kernel_norm = kernel / np.sum(kernel)

    # Convolución FFT
    dose_fft = fftconvolve(activity_gbq, kernel_norm, mode='same')

    # Enmascarar
    dose_gy = dose_fft * mask

    return dose_gy
```

---

## 4. Comparación de Rutas

| Aspecto | Ruta MCTAL | Ruta Kernel |
|---------|:----------:|:-----------:|
| Factor $$\tau$$ | Sí (multiplica fuera) | No (incluido en kernel.mat) |
| Actividad en | Bq | GBq |
| Densidad | Por voxel (labelmap) | Promedio (implícita en kernel) |
| Mascareo | Post-conversión | Post-convolución |
| Tiempo de cómputo | ~minutos | ~segundos |
| Precisión | Alta (voxel a voxel) | Aproximada |

---

## 5. Validación contra MATLAB

```python
# Test de validación
def test_conversion():
    dose_raw = np.ones((10, 10, 10)) * 1e-6  # MeV/cm³
    labelmap = np.ones((10, 10, 10)) * 90    # Hígado
    activity = 3.5e9                          # 3.5 GBq

    dose_gy = convert_mctal_to_gy(dose_raw, labelmap, activity)

    # Valor esperado manual:
    # D = (1e-6 / 1.06) * 1.6e-13 * 332916 * 3.5e9 * 1000
    expected = (1e-6 / 1.06) * 1.602e-13 * 332916 * 3.5e9 * 1000
    assert np.isclose(dose_gy[0, 0, 0], expected, rtol=1e-3)
```

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| $$\rho > 0$$ en todo voxel no-aire | $$\rho \leq 0$$ en algún voxel |
| $$D_{\text{Gy}} \geq 0$$ | Dosis negativa (> 1% voxeles) |
| Dosis media en tumor > 0 | Tumor con dosis media = 0 |
| Dosis máxima < 1000 Gy | Dosis máxima ≥ 1000 Gy (fuera de rango) |
| Dosis en aire = 0 | Voxel de aire con dosis > 0 |
| Coherencia MCTAL vs Kernel | Diferencia > 20% entre rutas |
| Actividad total > 0 | Actividad = 0 (dosis = 0) |

---

## 7. Referencias

- MCNP6 User's Manual, LA-UR-13-22934 (2013)
- Eckerman & Sjoreen, "Radiation Dosimetry of Y-90", Health Phys (2005)
- Gulec et al., "Hepatic Radioembolization with Y-90", Semin Nucl Med (2008)
- MATLAB `f_dosis.m` de 3Dosim v3.14 (`modulo_3/`)
- `dosimetry.py` en `SlicerDosimLib/`
