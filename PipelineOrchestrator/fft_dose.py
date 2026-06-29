"""
fft_dose.py — Convolucion FFT optimizada para calculo de dosis 3D.

Reemplaza scipy.signal.fftconvolve (lento, float64) con rfftn manual
con workers=-1, float32 y cache del kernel FFT.

Uso tipico (desde run_dosimetry_from_scene.py):
  from PipelineOrchestrator.fft_dose import convolve_imfilter_symmetric
  dose_gy = convolve_imfilter_symmetric(activity, kernel_normalized)
  dose_gy = dose_gy * liver_tumor_mask  # MATLAB: .* IND_liver_tumor

NOTA: el kernel DEBE estar normalizado (sum=1) antes de llamar.
NO multiplicar por T_mean despues — identico al flujo MATLAB.
"""

import numpy as np
import time
import logging
from typing import Optional, Tuple

logger = logging.getLogger("FFTDose")

# Cache para kernel FFT (el kernel es siempre el mismo 51x51x51)
_KERNEL_FFT_CACHE: dict = {}

# -------------------------------------------------------------------
# Constantes clinicas
# -------------------------------------------------------------------
PERITUMORAL_MM = 10.0  # 1 cm alrededor del tumor (fijo, requerimiento medico)
Y90_T_MEAN_S = 64.1 * 3600 / np.log(2)  # 332916 s — vida media Y-90


def convolve_imfilter_symmetric(
    activity: np.ndarray,
    kernel: np.ndarray,
) -> np.ndarray:
    """
    Convolucion 3D equivalente a MATLAB:
      imfilter(activity, kernel, 'conv', 'same', 'symmetric')

    Usa scipy.fft.rfftn (real-input FFT) con workers=-1 (multi-thread)
    y next_fast_len para tamano FFT optimo.

    IMPORTANTE: el kernel DEBE estar normalizado (sum=1, hecho por el
    llamante). Esta funcion NO normaliza.

    Pasos:
      1. Padding reflectivo de activity (emula 'symmetric')
      2. FFT convolution manual con rfftn + irfftn + float32
      3. Kernel FFT cacheado por shape (evita recalcular)
      4. Recortar padding reflectivo

    Args:
        activity: array 3D (actividad en Bq/voxel)
        kernel: array 3D (kernel de dosis, YA normalizado sum=1)

    Returns:
        result: array 3D del mismo tamano que activity
    """
    from scipy.fft import rfftn, irfftn, next_fast_len

    t0 = time.time()
    kr = tuple(k // 2 for k in kernel.shape)

    # Convertir a float32 (FFT mas rapida)
    kernel_f32 = kernel.astype(np.float32)
    activity_f32 = np.asarray(activity, dtype=np.float32)

    # Padding reflectivo igual a MATLAB 'symmetric'
    activity_pad = np.pad(activity_f32, tuple((d, d) for d in kr), mode='reflect')

    # Tamano FFT optimo
    full_shape = tuple(
        activity_pad.shape[i] + kernel.shape[i] - 1
        for i in range(3)
    )
    fft_shape = tuple(next_fast_len(s) for s in full_shape)

    logger.info(f"  Activity: {activity.shape} -> pad {kr} -> "
                f"{activity_pad.shape} -> FFT {fft_shape}")

    # Kernel FFT cacheado por shape
    cache_key = fft_shape
    if cache_key not in _KERNEL_FFT_CACHE:
        _KERNEL_FFT_CACHE[cache_key] = rfftn(
            kernel_f32, s=fft_shape, workers=-1
        )
    K_fft = _KERNEL_FFT_CACHE[cache_key]

    A_fft = rfftn(activity_pad, s=fft_shape, workers=-1)
    conv_full = irfftn(A_fft * K_fft, s=fft_shape, workers=-1)

    # Recortar a 'same'
    offset = tuple((s - ap) // 2 for s, ap in zip(full_shape, activity_pad.shape))
    slices_same = tuple(slice(o, o + ap) for o, ap in zip(offset, activity_pad.shape))
    conv_padded = conv_full[slices_same]

    # Recortar padding reflectivo -> tamano original
    slices_orig = tuple(slice(d, -d) if d > 0 else slice(None) for d in kr)
    result = np.asarray(conv_padded[slices_orig], dtype=np.float64)

    t1 = time.time()
    logger.info(f"  FFT convolution: {t1 - t0:.2f}s")
    logger.info(f"  Result: min={result.min():.4e}, max={result.max():.4e}, "
                f"mean={result.mean():.4e}")

    return result


# -------------------------------------------------------------------
# Enmascarado: solo higado + tumor + peritumoral
# -------------------------------------------------------------------

def _ellipsoid_structure(radius_vox: Tuple[int, int, int]) -> np.ndarray:
    """
    Genera elemento estructurante elipsoidal 3D.
    Args:
        radius_vox: (rz, ry, rx) radio en voxeles cada eje
    Returns:
        struct: array 3D bool, True dentro del elipsoide
    """
    rz, ry, rx = radius_vox
    z = np.arange(-rz, rz + 1)
    y = np.arange(-ry, ry + 1)
    x = np.arange(-rx, rx + 1)
    zz, yy, xx = np.meshgrid(z, y, x, indexing='ij')
    d2 = (zz / rz)**2 + (yy / ry)**2 + (xx / rx)**2
    return d2 <= 1.0


def create_peritumoral_mask(
    labelmap: np.ndarray,
    tumor_label: int = 100,
    liver_label: int = 90,
    spacing: Tuple[float, float, float] = (2.73, 2.73, 2.73),
) -> np.ndarray:
    """
    Crea mascara binaria: higado ∪ tumor ∪ peritumoral (1 cm fijo).
    Peritumoral: corona de 1 cm alrededor del tumor.

    Args:
        labelmap: array 3D con etiquetas de segmentacion
        tumor_label: valor del tumor en labelmap (default 100)
        liver_label: valor del higado en labelmap (default 90)
        spacing: (sx, sy, sz) espaciado de voxel en mm

    Returns:
        mask: bool array 3D, True donde se conserva la dosis
    """
    from scipy.ndimage import binary_dilation

    tumor_mask = (labelmap == tumor_label)
    r_vox = (
        max(1, int(round(PERITUMORAL_MM / spacing[0]))),
        max(1, int(round(PERITUMORAL_MM / spacing[1]))),
        max(1, int(round(PERITUMORAL_MM / spacing[2]))),
    )

    if np.any(tumor_mask):
        struct = _ellipsoid_structure(r_vox)
        tumor_dilated = binary_dilation(tumor_mask, structure=struct)
        peritumoral_mask = tumor_dilated & ~tumor_mask
        n_pts_peri = int(np.sum(peritumoral_mask))
        logger.info(f"  Peritumoral: {PERITUMORAL_MM:.0f} mm, "
                    f"radio_vox={r_vox}, voxeles={n_pts_peri}")
    else:
        peritumoral_mask = np.zeros_like(labelmap, dtype=bool)
        logger.warning("  No se encontro tumor — peritumoral vacio")

    liver_mask = (labelmap == liver_label)
    mask = liver_mask | tumor_mask | peritumoral_mask

    logger.info(f"  Mascara final: {int(np.sum(mask))} voxeles "
                f"(higado={int(np.sum(liver_mask))}, "
                f"tumor={int(np.sum(tumor_mask))}, "
                f"peritumoral={int(np.sum(peritumoral_mask))})")
    return mask


def apply_liver_tumor_peritumoral_mask(
    dose_gy: np.ndarray,
    labelmap: np.ndarray,
    tumor_label: int = 100,
    liver_label: int = 90,
    spacing: Tuple[float, float, float] = (2.73, 2.73, 2.73),
) -> np.ndarray:
    """
    Aplica mascara de higado + tumor + peritumoral (1 cm fijo).
    Anula todo lo que no sea higado, tumor o peritumoral.
    """
    t0 = time.time()
    mask = create_peritumoral_mask(
        labelmap, tumor_label=tumor_label,
        liver_label=liver_label, spacing=spacing,
    )
    dose_masked = dose_gy.copy()
    dose_masked[~mask] = 0.0
    elapsed = time.time() - t0
    logger.info(f"  Dosis enmascarada: {elapsed:.3f}s")
    if np.any(mask):
        logger.info(f"  Dosis en higado+tumor+peritumoral: "
                    f"min={dose_masked[mask].min():.4f}, "
                    f"max={dose_masked[mask].max():.4f}, "
                    f"mean={dose_masked[mask].mean():.4f} Gy")
    return dose_masked
