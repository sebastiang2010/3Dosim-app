"""
Validador de archivos de entrada MCNP generados por 3Dosim.

Verifica:
  - Coincidencia RPP vs Tally (mismos valores en Xmax, Ymax, Zmax)
  - Intervalos del tally (nx-1 correcto)
  - Presencia de NPS
  - Materiales definidos
  - Estructura tmesh completa
  - Fuente SDEF definida
  - Conteo de elementos RLE

Uso:
    python validate_mcnp_input.py archivo.i [--verbose]
"""

import re
import os
import sys
import math


def validate_mcnp_input(filepath, verbose=True):
    """
    Valida un archivo de entrada MCNP.

    Args:
        filepath: ruta al archivo .i
        verbose: si True, imprime reporte en consola

    Returns:
        dict con resultados de validacion
    """
    if not os.path.isfile(filepath):
        return {
            "file": filepath,
            "valid": False,
            "checks": {},
            "errors": [f"Archivo no encontrado: {filepath}"],
            "warnings": []
        }

    with open(filepath, "r") as f:
        text = f.read()

    checks = {}
    errors = []
    warnings = []

    # ── 1. RPP vs Tally ──────────────────────────────────────────────────
    rpp_match = re.search(
        r'(\d+)\s+rpp\s+0\.\s+([\d.]+)\s+0\.\s+([\d.]+)\s+0\.\s+([\d.]+)',
        text
    )
    cora_match = re.search(r'cora1\s+0\s+(\d+)i\s+([\d.]+)', text)
    corb_match = re.search(r'corb1\s+0\s+(\d+)i\s+([\d.]+)', text)
    corc_match = re.search(r'corc1\s+0\s+(\d+)i\s+([\d.]+)', text)

    rpp_tally_ok = True
    rpp_details = []
    if rpp_match and cora_match and corb_match and corc_match:
        rpp_x = float(rpp_match.group(2))
        rpp_y = float(rpp_match.group(3))
        rpp_z = float(rpp_match.group(4))
        tally_x = float(cora_match.group(2))
        tally_y = float(corb_match.group(2))
        tally_z = float(corc_match.group(2))

        for name, rpp_val, tally_val in [
            ("Xmax", rpp_x, tally_x),
            ("Ymax", rpp_y, tally_y),
            ("Zmax", rpp_z, tally_z),
        ]:
            if abs(rpp_val - tally_val) > 1e-6:
                rpp_tally_ok = False
                rpp_details.append(
                    f"{name}: rpp={rpp_val:.6f} vs tally={tally_val:.6f} DIFIEREN"
                )
            else:
                rpp_details.append(
                    f"{name}: {rpp_val:.6f} == {tally_val:.6f}"
                )
    else:
        rpp_tally_ok = False
        rpp_details = ["No se encontraron RPP y/o cora1/corb1/corc1"]

    checks["rpp_vs_tally"] = {
        "status": "PASS" if rpp_tally_ok else "FAIL",
        "details": " | ".join(rpp_details)
    }
    if not rpp_tally_ok:
        errors.append("RPP vs Tally mismatch")

    # ── 2. Intervalos tally (nx-1) ───────────────────────────────────────
    intervals_ok = True
    intervals_details = []
    if cora_match:
        n_intervals = int(cora_match.group(1))
        # Buscar comentario con tamano de imagen
        img_size_match = re.search(r'Tamano de la imagen:\s+\[\s*(\d+)\s+(\d+)\s+(\d+)\]', text)
        if img_size_match:
            nx = int(img_size_match.group(1))
            ny = int(img_size_match.group(2))
            nz = int(img_size_match.group(3))
            expected_intervals_x = nx - 1
            expected_intervals_y = ny - 1
            expected_intervals_z = nz - 1
            intervals_details.append(f"cora1: {n_intervals}i (esperado {expected_intervals_x}i)")
            # chequear corb1 y corc1
            if corb_match:
                niv_y = int(corb_match.group(1))
                intervals_details.append(f"corb1: {niv_y}i (esperado {expected_intervals_y}i)")
                if niv_y != expected_intervals_y:
                    intervals_ok = False
            if corc_match:
                niv_z = int(corc_match.group(1))
                intervals_details.append(f"corc1: {niv_z}i (esperado {expected_intervals_z}i)")
                if niv_z != expected_intervals_z:
                    intervals_ok = False
            if n_intervals != expected_intervals_x:
                intervals_ok = False
        else:
            intervals_details.append("No se encontro comentario de tamano de imagen")
    else:
        intervals_ok = False
        intervals_details.append("No se encontro cora1")

    checks["intervals"] = {
        "status": "PASS" if intervals_ok else "FAIL",
        "details": " | ".join(intervals_details)
    }
    if not intervals_ok:
        errors.append("Intervalos de tally incorrectos")

    # ── 3. NPS ───────────────────────────────────────────────────────────
    nps_match = re.search(r'NPS\s+(\d+)', text)
    nps_ok = nps_match is not None
    checks["nps"] = {
        "status": "PASS" if nps_ok else "FAIL",
        "details": f"NPS {nps_match.group(1)}" if nps_match else "NPS no encontrado"
    }
    if not nps_ok:
        errors.append("Falta NPS")

    # ── 4. Materiales ────────────────────────────────────────────────────
    mat_matches = re.findall(r'^m(\d+)', text, re.MULTILINE)
    mat_ok = len(mat_matches) >= 1
    checks["materials"] = {
        "status": "PASS" if mat_ok else "FAIL",
        "details": f"{len(mat_matches)} materiales encontrados: {', '.join(f'm{m}' for m in mat_matches)}"
    }
    if not mat_ok:
        errors.append("No se encontraron materiales")

    # ── 5. TMESH ─────────────────────────────────────────────────────────
    tmesh_ok = bool(re.search(r'tmesh', text, re.IGNORECASE))
    endmd_ok = bool(re.search(r'endmd', text, re.IGNORECASE))
    tmesh_complete = tmesh_ok and endmd_ok
    checks["tmesh"] = {
        "status": "PASS" if tmesh_complete else "FAIL",
        "details": (
            "tmesh presente" if tmesh_ok else "tmesh ausente"
        ) + " | " + (
            "endmd presente" if endmd_ok else "endmd ausente"
        )
    }
    if not tmesh_complete:
        errors.append("TMESH incompleto")

    # ── 6. Fuente ────────────────────────────────────────────────────────
    sdef_ok = bool(re.search(r'sdef', text, re.IGNORECASE))
    si5_ok = bool(re.search(r'si5\s+l', text))
    sp5_ok = bool(re.search(r'sp5', text))
    source_ok = sdef_ok and si5_ok and sp5_ok
    checks["source"] = {
        "status": "PASS" if source_ok else "FAIL",
        "details": (
            ("" if sdef_ok else "FALTA sdef | ") +
            ("" if si5_ok else "FALTA si5 | ") +
            ("" if sp5_ok else "FALTA sp5")
        ).rstrip(" | ")
    }
    if not source_ok:
        errors.append("Fuente MCNP incompleta")

    # ── 7. Conteo RLE ───────────────────────────────────────────────────
    rle_ok = True
    rle_details = []
    # Buscar comentario de tamano
    img_size_match = re.search(r'Tamano de la imagen:\s+\[\s*(\d+)\s+(\d+)\s+(\d+)\]', text)
    if img_size_match:
        nx = int(img_size_match.group(1))
        ny = int(img_size_match.group(2))
        nz = int(img_size_match.group(3))
        expected_elements = nx * ny * nz

        # Extraer bloques RLE (entre fill y 9999)
        fill_section = re.search(
            r'fill=0:\d+\s+0:\d+\s+0:\d+\s*\n(.+?)(?=\n9999)',
            text, re.DOTALL
        )
        if fill_section:
            fill_text = fill_section.group(1)
            # Contar tokens numericos y runs 'r'
            tokens = re.findall(r'\b\d+\b', fill_text)
            # Contar runs: patrones como "Nr" donde N es entero
            run_matches = re.findall(r'\b(\d+)r\b', fill_text)
            tokens_after_runs = len(tokens)
            runs_expanded = sum(int(n) for n in run_matches)
            # Los runs en si son tokens que representan un solo valor
            # Formula: tokens_totales - count_run_tokens + runs_expanded
            count_run_tokens = len(run_matches)
            actual_elements = tokens_after_runs - count_run_tokens + runs_expanded

            if actual_elements == expected_elements:
                rle_details.append(
                    f"RLE count={actual_elements} == nx*ny*nz={expected_elements}"
                )
            else:
                rle_ok = False
                rle_details.append(
                    f"RLE count={actual_elements} != nx*ny*nz={expected_elements}"
                )
        else:
            rle_ok = False
            rle_details.append("No se encontro seccion fill")
    else:
        rle_ok = False
        rle_details.append("No se encontro tamano de imagen")

    checks["rle_count"] = {
        "status": "PASS" if rle_ok else "FAIL",
        "details": " | ".join(rle_details)
    }
    if not rle_ok:
        errors.append("Conteo RLE incorrecto")

    # ── Resultado final ──────────────────────────────────────────────────
    valid = all(
        check["status"] == "PASS" for check in checks.values()
    )

    result = {
        "file": os.path.abspath(filepath),
        "valid": valid,
        "checks": checks,
        "errors": errors,
        "warnings": warnings
    }

    if verbose:
        print_report(result)

    return result


def print_report(result):
    """Imprime un reporte formateado de la validacion."""
    width = 80
    print()
    print("━" * width)
    print("  Validación archivo MCNP")
    print("━" * width)
    print(f"  Archivo: {result['file']}")
    print()

    all_pass = True
    for check_name, check_data in result["checks"].items():
        status_icon = "✅" if check_data["status"] == "PASS" else "❌"
        if check_data["status"] != "PASS":
            all_pass = False
        print(f"  {status_icon} {check_name}: {check_data['details']}")

    if result["warnings"]:
        print()
        for w in result["warnings"]:
            print(f"  ⚠️  {w}")

    if result["errors"]:
        print()
        for e in result["errors"]:
            print(f"  ❌ ERROR: {e}")

    print()
    if all_pass and not result["errors"]:
        print(f"  🟢 Resultado: ARCHIVO VÁLIDO")
    else:
        print(f"  🔴 Resultado: ARCHIVO INVÁLIDO ({len(result['errors'])} errores)")
    print("━" * width)
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Validador de archivos de entrada MCNP de 3Dosim"
    )
    parser.add_argument("file", help="Ruta al archivo .i a validar")
    parser.add_argument("--verbose", "-v", action="store_true", default=True)
    args = parser.parse_args()

    validate_mcnp_input(args.file, verbose=args.verbose)
