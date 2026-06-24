"""
Configuracion de tallies MCNP para dosimetria.

Genera:
  - FMESH4:e (mesh tally 3D) para mapa de dosis
  - F6:e (track length estimate) para dosis promedio
  - DE4/DF4 (factor de conversion dosis)
  - CUT y NPS
"""

from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


class MCNPTallyBuilder:
    """
    Construye las tarjetas de tally para MCNP.

    Tally principal: FMESH4 con mesh 3D que cubre el volumen del phantom.
    Tally secundario: F6 para dosis promedio en el higado.
    """

    # Factores de conversion DE/DF para electrones (MeV/g -> Gy)
    # Datos de NIST para agua, Y-90
    DE_DF_ELECTRON = [
        (0.01, 0.01),
        (0.03, 0.03),
        (0.05, 0.05),
        (0.07, 0.07),
        (0.10, 0.10),
        (0.20, 0.20),
        (0.40, 0.40),
        (0.60, 0.60),
        (1.00, 1.00),
        (2.00, 2.00),
        (2.28, 2.28),
    ]

    def __init__(self):
        pass

    def build(
        self,
        iso_data: dict,
        dims: tuple[int, int, int],
        n_particles: int = int(1e7),
        origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> list[str]:
        """
        Construye todas las tarjetas de tally.

        Args:
            iso_data: dict con datos del isotopo
            dims: (nx, ny, nz) dimensiones del volumen
            n_particles: numero de historias MCNP
            origin: origen del mesh tally

        Returns:
            list[str]: tarjetas de tally + corte + NPS
        """
        nx, ny, nz = dims
        particle = iso_data.get("particle", "electron")
        particle_code = "e" if particle == "electron" else "p"
        mode = iso_data.get("mode", "e")

        cards = []
        cards.append("C")
        cards.append("C TALLIES")
        cards.append("C")

        # --- FMESH4: mesh tally 3D para dosis ---
        cards.append(f"C Mesh tally 3D: dosis por voxel ({nx}x{ny}x{nz})")
        cards.append(f"FMESH4:{particle_code}  DOSIMETRY  GEOM=XYZ")
        cards.append(f"            ORIGIN={origin[0]} {origin[1]} {origin[2]}")
        cards.append(f"            IMESH={nx}  IINTS={nx}")
        cards.append(f"            JMESH={ny}  JINTS={ny}")
        cards.append(f"            KMESH={nz}  KINTS={nz}")
        cards.append("C")
        cards.append("C Factor de conversion dosis (MeV/g -> Gy)")
        cards.append("C DE4 = energia (MeV), DF4 = factor de conversion")

        # DE4/DF4 segun particula
        if particle == "electron":
            for energy, factor in self.DE_DF_ELECTRON:
                cards.append(f"DE4  {energy}")
            cards.append("DF4  " + "  ".join(str(f) for _, f in self.DE_DF_ELECTRON))
        else:
            # Para fotones, usar factor ~1 (log-log)
            cards.append("DE4  0.01  0.03  0.05  0.07  0.10  0.20  0.40  0.60  1.00  2.00")
            cards.append("DF4  log  log")

        cards.append("C")
        cards.append("C Tally F6: dosis promedio (MeV/g) en todo el volumen")
        cards.append(f"F6:{particle_code}  1  $ dosis promedio en celda 1")

        # --- Corte de energia ---
        cards.append("C")
        cards.append("C CORTE DE ENERGIA")
        if particle == "electron":
            cards.append("CUT:e  1e-3  $ corte electrones a 1 keV")
        else:
            cards.append("CUT:p  1e-3  $ corte fotones a 1 keV")

        # --- NPS ---
        cards.append("C")
        cards.append("C NUMERO DE HISTORIAS")
        cards.append(f"NPS  {n_particles}")

        # --- Modo de transporte ---
        cards.append("C")
        cards.append("C MODO DE TRANSPORTE")
        cards.append(f"MODE  {mode}")

        return cards

    def build_validation_f6(
        self, cell_id: int = 1, particle: str = "e"
    ) -> list[str]:
        """
        Tally F6 adicional para celda especifica (validacion).
        """
        pc = "e" if particle == "electron" else "p"
        return [
            "C",
            "C Tally F6 adicional para validacion MIRD",
            f"F6:{pc}  {cell_id}",
            f"FQ6  MeV/g  $ dosis en MeV/g",
        ]
