"""
dose_kernel.py — Carga el kernel de dosis desde kernel.mat (MCNP precalculado).

El kernel.mat contiene la matriz D3 de MCNP ya convertida a Gy por el flujo MATLAB:
  Kernel = D3;                % MeV/cm3 (MCNP tally)
  Kernel = Kernel * V;        % MeV
  Kernel = Kernel * MeV2J;    % J
  Kernel = Kernel * t;        % t = 1/lambda (332916 s, tiempo de integracion)
  Kernel = Kernel * Actividad;% Bq (1e9 = 1 GBq)
  Kernel = Kernel / masa;     % kg -> Gy

El pipeline Python lo usa identico al MATLAB:
  Kernel = Kernel / sum(Kernel(:));        % normalizar
  DosisK = imfilter(PET, Kernel, ...);     % convolucion
  DosisK = DosisK .* IND_liver_tumor;      % mascara
  % NO multiplicar por T_mean (ya incluido en kernel.mat)
"""

import numpy as np
import logging
import os
from typing import Optional

logger = logging.getLogger("DoseKernel")

# -------------------------------------------------------------------
# Carga del kernel desde MATLAB .mat (formato v7.3 HDF5)
# -------------------------------------------------------------------

def _center_kernel_max(kernel: np.ndarray) -> np.ndarray:
    """
    Desplaza el kernel para que su maximo quede en el centro del array.

    El kernel MCNP puede tener el origen desplazado (ej: maximo en (24,24,24)
    en vez del centro (25,25,25) para 51x51x51). fftconvolve asume que el
    origen esta en floor(size/2), asi que hay que centrarlo.

    Args:
        kernel: array 3D

    Returns:
        kernel centrado (mismo shape)
    """
    max_pos = np.unravel_index(np.argmax(kernel), kernel.shape)
    center = tuple(s // 2 for s in kernel.shape)

    if max_pos == center:
        return kernel  # ya centrado

    shifts = tuple(c - m for c, m in zip(center, max_pos))
    logger.info(f"  Centrando kernel: max en {max_pos} -> centro {center}, "
                f"shift={shifts}")
    kernel_centered = np.roll(kernel, shifts, axis=(0, 1, 2))
    return kernel_centered


def load_kernel_mat(
    path: str,
    normalize: bool = False,
    recenter: bool = True,
) -> np.ndarray:
    """
    Carga kernel de dosis desde archivo .mat (v7.3 HDF5).

    El .mat contiene la variable 'Kernel' (51x51x51 float64) ya en Gy.

    Args:
        path: ruta al archivo kernel.mat
        normalize: si True, divide por sum(Kernel) (emula MATLAB:
                   Kernel = Kernel / sum(Kernel(:)))
        recenter: si True, desplaza el kernel para que el maximo quede
                  en el centro del array (necesario para fftconvolve)

    Returns:
        kernel: array 3D float64
    """
    import h5py

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Kernel .mat no encontrado: {path}\n"
            "Genere kernel.mat desde MATLAB con cargo_mctal_kernel.m"
        )

    with h5py.File(path, 'r') as f:
        kernel = f['Kernel'][()].astype(np.float64)

    logger.info(f"  Kernel cargado: {path}")
    logger.info(f"  Shape: {kernel.shape}, dtype={kernel.dtype}")

    # Centrar el maximo en el centro del array
    if recenter:
        kernel = _center_kernel_max(kernel)

    if normalize:
        s = kernel.sum()
        if s > 0:
            kernel = kernel / s
            logger.info(f"  Kernel normalizado: sum=1")
        else:
            logger.warning("  Kernel suma cero! No se normalizo")

    logger.info(f"  Kernel: min={kernel.min():.4e}, max={kernel.max():.4e}, "
                f"sum={kernel.sum():.4e}")

    return kernel


# -------------------------------------------------------------------
# Cache para no recargar el kernel multiples veces
# -------------------------------------------------------------------

_kernel_cache: dict = {}

def get_kernel(
    path: str,
    normalize: bool = False,
    force_reload: bool = False,
) -> np.ndarray:
    """Carga kernel con cache."""
    cache_key = f"{path}:norm={normalize}"
    if cache_key in _kernel_cache and not force_reload:
        return _kernel_cache[cache_key]
    kernel = load_kernel_mat(path, normalize=normalize)
    _kernel_cache[cache_key] = kernel
    return kernel


# -------------------------------------------------------------------
# Path por defecto del kernel
# -------------------------------------------------------------------

DEFAULT_KERNEL_PATH = r"C:\programas\3Dosim\3Dosim_v4\kernel\kernel.mat"
