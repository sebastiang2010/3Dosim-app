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

import gc
import hashlib
import numpy as np
import time
import logging
import sys
import platform
from typing import Optional, Tuple

logger = logging.getLogger("FFTDose")

# ── Workers para FFT ──
# Windows: workers=-1 puede deadlockear con scipy/MKL.
# Linux OK con workers=-1 (OpenMP).
_IS_WINDOWS = platform.system() == "Windows"
FFT_WORKERS = 1 if _IS_WINDOWS else -1  # Windows safe, Linux optimo
logger.info(f"FFTDose: platform={platform.system()}, FFT_WORKERS={FFT_WORKERS}")
sys.stdout.flush()

# Cache para kernel FFT
# Clave: (fft_shape, md5(kernel_bytes)) para evitar usar un kernel FFT
# erroneo cuando el kernel cambia pero fft_shape es el mismo.
# El hash del kernel (51x51x51 float32 ≈ 51KB) es ~1us.
_KERNEL_FFT_CACHE: dict = {}

# -------------------------------------------------------------------
# Constantes clinicas
# -------------------------------------------------------------------
PERITUMORAL_MM = 10.0  # 1 cm alrededor del tumor (fijo, requerimiento medico)
Y90_T_MEAN_S = 64.1 * 3600 / np.log(2)  # 332916 s — vida media Y-90


def _kernel_cache_key(kernel: np.ndarray, fft_shape: tuple) -> tuple:
    """Genera clave de cache para kernel FFT.

    Incluye hash del contenido del kernel para evitar resultados
    incorrectos si se usan kernels diferentes con el mismo fft_shape.

    Args:
        kernel: array 3D float32 del kernel
        fft_shape: tupla con tamano FFT optimo

    Returns:
        tuple: (fft_shape, md5_hexdigest)
    """
    md5 = hashlib.md5(kernel.tobytes(), usedforsecurity=False)
    return (fft_shape, md5.hexdigest())


def _fft_conv_impl(
    activity_pad, kernel_f32, fft_shape, kr, activity_shape, K_fft
):
    """Ejecuta FFT + IFFT + recorte (run en thread separado para timeout)."""
    from scipy.fft import rfftn, irfftn

    t_fft = time.time()
    A_fft = rfftn(activity_pad, s=fft_shape, workers=FFT_WORKERS)
    dt_fft_a = time.time() - t_fft

    t_mul = time.time()
    conv_fft = A_fft * K_fft
    dt_mul = time.time() - t_mul

    t_ifft = time.time()
    conv_full = irfftn(conv_fft, s=fft_shape, workers=FFT_WORKERS)
    dt_ifft = time.time() - t_ifft

    # Recortar: fft_shape -> valid range -> 'same' -> original
    full_shape = tuple(activity_pad.shape[i] + kernel_f32.shape[i] - 1 for i in range(3))
    slices_valid = tuple(slice(0, fs) for fs in full_shape)
    conv_valid = conv_full[slices_valid]

    slices_same = tuple(
        slice(kr_i, kr_i + ap_i) for kr_i, ap_i in zip(kr, activity_pad.shape)
    )
    conv_padded = conv_valid[slices_same]

    slices_orig = tuple(
        slice(kr_i, kr_i + a_i) for kr_i, a_i in zip(kr, activity_shape)
    )
    result = np.asarray(conv_padded[slices_orig], dtype=np.float64)

    return result, dt_fft_a, dt_mul, dt_ifft


def convolve_imfilter_symmetric(
    activity: np.ndarray,
    kernel: np.ndarray,
    timeout_s: float = 300.0,
) -> np.ndarray:
    """
    Convolucion 3D equivalente a MATLAB:
      imfilter(activity, kernel, 'conv', 'same', 'symmetric')

    Usa scipy.fft.rfftn (real-input FFT) con workers=FFT_WORKERS
    y next_fast_len para tamano FFT optimo.

    IMPORTANTE: el kernel DEBE estar normalizado (sum=1, hecho por el
    llamante). Esta funcion NO normaliza.

    Args:
        activity: array 3D (actividad en GBq/voxel)
        kernel: array 3D (kernel de dosis, YA normalizado sum=1)
        timeout_s: timeout en segundos para la FFT (default 300s = 5 min)

    Returns:
        result: array 3D del mismo tamano que activity
    """
    from scipy.fft import rfftn, irfftn, next_fast_len
    import concurrent.futures

    t0 = time.time()
    kr = tuple(k // 2 for k in kernel.shape)

    # ── Convertir a float32 ──
    t_convert = time.time()
    kernel_f32 = np.asarray(kernel, dtype=np.float32)
    activity_f32 = np.asarray(activity, dtype=np.float32)
    dt_convert = time.time() - t_convert

    # ── Padding symmetric ──
    t_pad = time.time()
    activity_pad = np.pad(activity_f32, tuple((d, d) for d in kr), mode='symmetric')
    dt_pad = time.time() - t_pad

    # ── Tamano FFT optimo (next_fast_len reduce latencia FFT) ──
    from scipy.fft import next_fast_len
    full_shape = tuple(
        activity_pad.shape[i] + kernel.shape[i] - 1
        for i in range(3)
    )
    fft_shape = tuple(next_fast_len(s, real=True) for s in full_shape)

    logger.info(f"  Activity: {activity.shape} -> pad {kr} -> "
                f"{activity_pad.shape} -> full {full_shape} -> FFT {fft_shape}")

    # ── Liberar activity_f32 (no se necesita mas despues del pad) ──
    del activity_f32

    # ── Kernel FFT cacheado ──
    t_cache = time.time()
    cache_key = _kernel_cache_key(kernel_f32, fft_shape)
    if cache_key not in _KERNEL_FFT_CACHE:
        kernel_fft_shifted = np.fft.ifftshift(kernel_f32)
        _KERNEL_FFT_CACHE[cache_key] = rfftn(
            kernel_fft_shifted, s=fft_shape, workers=FFT_WORKERS
        )
        logger.info(f"  Kernel FFT: computado (cache miss, {len(_KERNEL_FFT_CACHE)} entradas)")
    else:
        logger.info(f"  Kernel FFT: desde cache")
    K_fft = _KERNEL_FFT_CACHE[cache_key]
    dt_cache = time.time() - t_cache

    # ── Liberar memoria residual antes de FFT ──
    gc.collect()

    # ── Ejecutar FFT + IFFT con timeout ──
    logger.info(f"  Lanzando FFT (timeout={timeout_s:.0f}s, workers={FFT_WORKERS})...")
    sys.stdout.flush()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _fft_conv_impl,
            activity_pad, kernel_f32, fft_shape, kr, activity.shape, K_fft,
        )
        try:
            result, dt_fft_a, dt_mul, dt_ifft = future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            logger.error(f"  FFT TIMEOUT despues de {timeout_s:.0f}s — "
                         f"shape={fft_shape}, fallback a convolucion lenta")
            raise RuntimeError(
                f"FFT convolution timeout ({timeout_s:.0f}s) en shape {fft_shape}. "
                f"Actividad: {activity.shape}, FFT: {fft_shape}"
            )

    t1 = time.time()
    dt_total = t1 - t0
    logger.info(f"  ⏱ FFT convolution: {dt_total:.2f}s total")
    logger.info(f"     Convertir float32:  {dt_convert:.3f}s")
    logger.info(f"     Padding symmetric:  {dt_pad:.3f}s")
    logger.info(f"     Cache lookup:       {dt_cache:.3f}s")
    logger.info(f"     FFT actividad:      {dt_fft_a:.3f}s")
    logger.info(f"     Multiplicacion:     {dt_mul:.3f}s")
    logger.info(f"     IFFT:               {dt_ifft:.3f}s")
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
