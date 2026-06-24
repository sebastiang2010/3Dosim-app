"""
Parser de archivos MCTAL (output MCNP) — version MATLAB-compatible.

Lee archivos MCTAL ASCII generados por MCNP y extrae datos del FMESH4
(tally 1) usando algoritmo IDENTICO a f_cargo_mctall.m.

Formato FMESH4 en MCTAL:
  tally    1   -1   -1
  0 0 1 0 0 0 0 0 0 ...    ← parametros
  f <total> <type> <nx> <ny> <nz>  ← dimensiones mesh
  <x boundaries nx+1 valores>
  <y boundaries ny+1 valores>
  <z boundaries nz+1 valores>
  t        1                 ← time bin
  vals                       ← marca de datos
  v1 e1 v2 e2 v3 e3 v4 e4   ← datos en grupos de 8 columnas
  v5 e5 v6 e6 v7 e7 v8 e8
  ...

La lectura usa numpy para eficiencia, reshape column-major [ny, nx, nz],
y transpone cada slice → [nx, ny, nz] (identico a MATLAB).
"""

from __future__ import annotations

import logging
import numpy as np
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Constantes de conversion (MATLAB cargo_mctal.m)
MEV2J = 1.6e-13       # MeV → Joules
Y90_HALF_LIFE_S = 64.1 * 3600  # 64.1 horas → segundos
Y90_LAMBDA = np.log(2) / Y90_HALF_LIFE_S
Y90_MEAN_LIFE_S = 1.0 / Y90_LAMBDA  # ~92.43 h


class MCTALParseError(Exception):
    pass


class MCTALParser:
    """
    Parsea archivos MCTAL de MCNP — compatible con f_cargo_mctall.m.

    Uso:
        parser = MCTALParser()
        result = parser.parse('mctal.m', nx=512, ny=512, nz=171)
        dosis_mev_cm3 = result['dose_3d']
        error = result['uncertainty']
        nps = result['nps']
    """

    def __init__(self):
        self.logger = logger

    def parse(
        self,
        path: str,
        nx: Optional[int] = None,
        ny: Optional[int] = None,
        nz: Optional[int] = None,
    ) -> dict:
        """Parsea archivo MCTAL completo."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Archivo MCTAL no encontrado: {path}")

        filesize = os.path.getsize(path)
        self.logger.info(f"Parseando MCTAL: {path} ({filesize / 1e6:.0f} MB)")

        result = {
            "dose_3d": None, "uncertainty": None,
            "dimensions": (0, 0, 0), "tally_data": {},
            "title": "", "nps": 0, "source_file": path,
        }

        # Extraer titulo y NPS
        result["title"], result["nps"] = self._parse_header(path)

        # Parsear FMESH4 (tally 1)
        dims, d_3d, e_3d = self._parse_fmesh4(path, nx, ny, nz)

        if d_3d is not None:
            result["dose_3d"] = d_3d
            result["uncertainty"] = e_3d
            result["dimensions"] = dims
            non_zero = d_3d[d_3d > 0]
            self.logger.info(
                f"  Dosis 3D: {dims}, "
                f"min={non_zero.min() if len(non_zero) else 0:.4e} "
                f"max={d_3d.max():.4e} MeV/cm3/particula"
            )

        return result

    # ----------------------------------------------------------------
    # Header
    # ----------------------------------------------------------------

    def _parse_header(self, path: str) -> tuple[str, int]:
        """Lee titulo y NPS del encabezado MCTAL."""
        title = ""
        nps = 0
        try:
            with open(path, "r", errors="ignore") as f:
                for i, line in enumerate(f):
                    if i > 15:
                        break
                    s = line.strip()
                    if i == 0:
                        nums = re.findall(r"\d+", s)
                        if len(nums) >= 2:
                            try:
                                nps = int(nums[1])
                                if nps < 1000:
                                    nps = int(nums[0])
                            except (ValueError, IndexError):
                                nps = 0
                    if not title and s:
                        if not s.startswith("c") and not s.startswith("ntal"):
                            if s[0].isdigit() and len(s) < 20:
                                continue
                            title = s[:80].strip()
        except Exception as e:
            self.logger.warning(f"Error leyendo header: {e}")
        return title, nps

    # ----------------------------------------------------------------
    # FMESH4 parser — compatible con f_cargo_mctall.m
    # ----------------------------------------------------------------

    def _parse_fmesh4(
        self, path: str,
        nx: Optional[int] = None,
        ny: Optional[int] = None,
        nz: Optional[int] = None,
    ) -> tuple[tuple, Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Parsea tally 1 (FMESH4).

        Algoritmo identico a f_cargo_mctall.m:
        1. Buscar 'tally    1  '
        2. Leer 'f <total> <type> <nx> <ny> <nz>'
        3. Saltar boundaries de mesh
        4. Buscar 'vals'
        5. Leer pares (valor, error) como floats
        6. Reconstruir 3D
        """
        try:
            with open(path, "r", errors="ignore") as f:
                # ---- 1. Buscar tally 1 ----
                in_tally1 = False
                for line in f:
                    if line.startswith("tally    1  "):
                        in_tally1 = True
                        self.logger.debug("  Tally 1 encontrado")
                        break

                if not in_tally1:
                    raise MCTALParseError("No se encontro tally 1")

                # ---- 2. Dimensiones ----
                next(f)  # saltar linea parametros (37 nums)
                f_line = next(f).strip()
                parts = f_line.split()
                if parts[0] != "f":
                    raise MCTALParseError(f"Esperaba 'f', encontre: {f_line}")

                auto_nx, auto_ny, auto_nz = int(parts[3]), int(parts[4]), int(parts[5])
                nx = nx or auto_nx
                ny = ny or auto_ny
                nz = nz or auto_nz
                total_pairs = nx * ny * nz
                self.logger.info(f"  Mesh: {nx}x{ny}x{nz} = {total_pairs} voxels")

                # ---- 3. Saltar boundaries ----
                # Leer hasta 't ' o 'vals'
                for line in f:
                    s = line.strip()
                    if s.startswith("t ") or s.startswith("t  "):
                        continue  # saltar time bin
                    if s == "vals" or s.startswith("vals"):
                        break

                # ---- 4. Leer datos ----
                n_groups = (total_pairs + 3) // 4
                n_floats = n_groups * 8
                self.logger.info(f"  Leyendo {n_floats} floats...")

                raw = self._read_floats(f, n_floats)

                if len(raw) < n_floats:
                    self.logger.warning(f"  Solo {len(raw)}/{n_floats} floats")
                    raw = np.pad(raw, (0, n_floats - len(raw)), constant_values=0.0)

                # ---- 5. Reconstruir 3D ----
                d_3d, e_3d = self._reconstruct_3d(raw, nx, ny, nz, total_pairs)
                return (nx, ny, nz), d_3d, e_3d

        except MCTALParseError:
            raise
        except Exception as e:
            self.logger.error(f"Error parseando FMESH4: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return (0, 0, 0), None, None

    # ----------------------------------------------------------------
    # Lectura eficiente de floats
    # ----------------------------------------------------------------

    def _read_floats(self, file_obj, n_expected: int) -> np.ndarray:
        """Lee floats del archivo post-vals por chunks."""
        chunks = []
        buf = []
        n_read = 0

        for line in file_obj:
            s = line.strip()
            if not s:
                continue
            buf.append(s)
            if len(buf) >= 50000:
                text = " ".join(buf)
                data = np.fromstring(text, dtype=np.float64, sep=" ")
                chunks.append(data)
                n_read += len(data)
                buf = []
                if n_read >= n_expected:
                    break

        if buf:
            text = " ".join(buf)
            data = np.fromstring(text, dtype=np.float64, sep=" ")
            chunks.append(data)

        if not chunks:
            return np.array([], dtype=np.float64)

        result = np.concatenate(chunks)
        if len(result) > n_expected:
            result = result[:n_expected]
        return result

    # ----------------------------------------------------------------
    # Reconstruccion 3D (identica a MATLAB f_cargo_mctall.m)
    # ----------------------------------------------------------------

    def _reconstruct_3d(
        self, raw: np.ndarray, nx: int, ny: int, nz: int, total_pairs: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Reconstruye arrays 3D.

        MATLAB f_cargo_mctall.m:
          1. raw = [v1,e1,v2,e2,v3,e3,v4,e4, v5,e5,...]
          2. dosis = raw[0::2]  (indices pares)
          3. error = raw[1::2]  (indices impares)
          4. dosis.reshape([ny, nx, nz], order='F')  (column-major)
          5. D(:,:,i) = Dosis(:,:,i)'  (transponer cada slice)
        """
        d_flat = raw[0::2][:total_pairs]
        e_flat = raw[1::2][:total_pairs]

        if len(d_flat) < total_pairs:
            d_flat = np.pad(d_flat, (0, total_pairs - len(d_flat)), constant_values=0.0)
            e_flat = np.pad(e_flat, (0, total_pairs - len(e_flat)), constant_values=0.0)

        # Column-major reshape a [ny, nx, nz]
        d_nyx_nz = d_flat.reshape((ny, nx, nz), order="F")
        e_nyx_nz = e_flat.reshape((ny, nx, nz), order="F")

        # Transponer cada slice
        dose = np.zeros((nx, ny, nz), dtype=np.float64)
        err = np.zeros((nx, ny, nz), dtype=np.float64)
        for i in range(nz):
            dose[:, :, i] = d_nyx_nz[:, :, i].T
            err[:, :, i] = e_nyx_nz[:, :, i].T

        return dose, err

    # ----------------------------------------------------------------
    # Conversion a Gy (MATLAB cargo_mctal.m:389-395)
    # ----------------------------------------------------------------

    @staticmethod
    def compute_dose_gy(
        dose_mev_cm3: np.ndarray,
        labelmap: np.ndarray,
        cell_densities: dict[int, float],
        activity_bq: float,
        t_meanlife_s: float = Y90_MEAN_LIFE_S,
    ) -> np.ndarray:
        """
        Convierte dosis MeV/cm3/particula → Gy.

        MATLAB cargo_mctal.m:
          1. f_div_densidad: D / rho (MeV/cm3 → MeV/g)
          2. D * MeV2J (MeV/g → J/g)
          3. D * t * Actividad (J/g total)
          4. * 1000 (J/g → J/kg = Gy)
        """
        dens_map = np.ones_like(dose_mev_cm3, dtype=np.float64)
        for idx, dens in cell_densities.items():
            mask = (labelmap == idx)
            dens_map[mask] = dens

        d_mev_g = np.divide(dose_mev_cm3, dens_map,
                            out=np.zeros_like(dose_mev_cm3),
                            where=dens_map > 0.001)
        d_j_g = d_mev_g * MEV2J
        d_total = d_j_g * t_meanlife_s * activity_bq
        d_gy = d_total * 1000.0
        return d_gy
