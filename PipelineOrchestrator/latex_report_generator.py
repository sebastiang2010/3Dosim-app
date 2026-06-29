"""
latex_report_generator.py — Genera reporte LaTeX compilado desde Python.

Pipeline:
    datos Python (dicts / dataclasses)
    → figuras PNG (matplotlib)
    → template .tex.j2 (Jinja2)
    → compilación PDF (latexmk -xelatex)

Uso:
    from PipelineOrchestrator.latex_report_generator import generate_latex_report
    pdf_path = generate_latex_report(results_data, output_dir, patient_id="4090159")
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("LaTeXReport")

try:
    import jinja2
except ImportError:
    jinja2 = None
    logger.warning("jinja2 no instalado. `pip install jinja2` para reportes LaTeX.")

# ─── Constantes ───────────────────────────────────────────────────────────────

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
TEMPLATE_NAME = "reporte.tex.j2"
COMPILE_BAT_NAME = "compile.bat"

# ─── Filtros Jinja2 ──────────────────────────────────────────────────────────


def _latex_escape(text: str) -> str:
    """Escapa caracteres especiales de LaTeX en cadenas."""
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "<": r"\textless{}",
        ">": r"\textgreater{}",
    }
    for char, escaped in replacements.items():
        text = text.replace(char, escaped)
    return text


def _commas(value: float | int) -> str:
    """Formatea número con separador de miles."""
    if isinstance(value, float):
        s = f"{value:,.2f}"
    else:
        s = f"{value:,}"
    return s


def _fmt1(value: float) -> str:
    return f"{value:.1f}"


def _fmt2(value: float) -> str:
    return f"{value:.2f}"


def _fmt3(value: float) -> str:
    return f"{value:.3f}"


def _fmt4(value: float) -> str:
    return f"{value:.4f}"


def _fmt2e(value: float) -> str:
    """Notación científica con 2 decimales: 1.23e+6"""
    return f"{value:.2e}"


def _get_jinja_env() -> jinja2.Environment:
    """Retorna Environment de Jinja2 con delimitadores LaTeX-safe."""
    loader = jinja2.FileSystemLoader(TEMPLATE_DIR)
    env = jinja2.Environment(
        loader=loader,
        block_start_string=r"\BLOCK{",
        block_end_string=r"}",
        variable_start_string=r"\VAR{",
        variable_end_string=r"}",
        comment_start_string=r"\#{",
        comment_end_string=r"}",
        autoescape=False,
    )
    env.filters["latex"] = _latex_escape
    env.filters["commas"] = _commas
    env.filters["fmt1"] = _fmt1
    env.filters["fmt2"] = _fmt2
    env.filters["fmt3"] = _fmt3
    env.filters["fmt4"] = _fmt4
    env.filters["fmt2e"] = _fmt2e
    return env


# ─── Figuras DVH ─────────────────────────────────────────────────────────────


def _plot_dvh_figures(
    dvh_curves: list[tuple[str, np.ndarray, np.ndarray]],
    figures_dir: str,
) -> None:
    """Genera PNG individuales + combinado para las curvas DVH."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#1B2A4A", "#E63946", "#2E86AB", "#2D6A4F", "#E09F3E", "#9B5DE5"]

    # DVH combinado
    plt.figure(figsize=(8, 5))
    for i, (name, d_vals, a_vals) in enumerate(dvh_curves):
        if len(d_vals) == 0 or len(a_vals) == 0:
            continue
        c = colors[i % len(colors)]
        plt.plot(d_vals, a_vals, color=c, linewidth=2, label=name)
    plt.xlabel("Dosis [Gy]", fontsize=12)
    plt.ylabel("Volumen [%]", fontsize=12)
    plt.title("DVH - Curvas Dosis-Volumen", fontsize=14, fontweight="bold")
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, "dvh_combined.png"), dpi=200)
    plt.close()

    # DVH individuales
    for i, (name, d_vals, a_vals) in enumerate(dvh_curves):
        if len(d_vals) == 0 or len(a_vals) == 0:
            continue
        safe_name = name.lower().replace(" ", "_").replace("í", "i").replace("ó", "o")
        plt.figure(figsize=(7, 4.5))
        c = colors[i % len(colors)]
        plt.plot(d_vals, a_vals, color=c, linewidth=2.5)
        plt.xlabel("Dosis [Gy]", fontsize=12)
        plt.ylabel("Volumen [%]", fontsize=12)
        plt.title(f"DVH - {name}", fontsize=14, fontweight="bold")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(figures_dir, f"dvh_{safe_name}.png"), dpi=200)
        plt.close()


def _copy_screenshots(figures_dir: str, screenshot_paths: list[str]) -> list[str]:
    """Copia screenshots reales al directorio figures/ y retorna paths relativos."""
    copied = []
    for src in screenshot_paths:
        if not os.path.isfile(src):
            logger.warning(f"  Screenshot no encontrado: {src}")
            continue
        basename = os.path.basename(src)
        dst = os.path.join(figures_dir, basename)
        try:
            shutil.copy2(src, dst)
            copied.append(f"figures/{basename}")
            logger.info(f"  Screenshot copiado: {basename} ({os.path.getsize(src)//1024} KB)")
        except Exception as e:
            logger.warning(f"  Error copiando {src}: {e}")
    return copied


# ─── Compilación LaTeX ───────────────────────────────────────────────────────


def _find_latexmk() -> Optional[str]:
    """Busca latexmk en PATH o en rutas MiKTeX conocidas."""
    latexmk = shutil.which("latexmk")
    if latexmk:
        return latexmk
    # MiKTeX known paths
    miktex_paths = [
        r"C:\Users\Sebastian\AppData\Local\Programs\MiKTeX\miktex\bin\x64\latexmk.exe",
        r"C:\Program Files\MiKTeX\miktex\bin\x64\latexmk.exe",
    ]
    for p in miktex_paths:
        if os.path.isfile(p):
            return p
    return None


def _compile_latex(latex_dir: str) -> Optional[str]:
    """Compila main.tex con latexmk -xelatex. Fallback a xelatex directo."""
    latex_dir = os.path.normpath(latex_dir)
    main_tex = os.path.normpath(os.path.join(latex_dir, "main.tex"))
    out_dir = os.path.normpath(os.path.join(latex_dir, "out"))

    if not os.path.exists(main_tex):
        logger.error(f"  main.tex no encontrado: {main_tex}")
        return None

    # Intentar con latexmk primero
    latexmk_exe = _find_latexmk()
    if latexmk_exe:
        logger.info("  Compilando con latexmk -xelatex...")
        try:
            result = subprocess.run(
                [
                    latexmk_exe,
                    "-xelatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-outdir={out_dir}",
                    main_tex,
                ],
                cwd=latex_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                pdf_path = os.path.join(out_dir, "main.pdf")
                if os.path.exists(pdf_path):
                    return pdf_path
            else:
                logger.warning(f"  latexmk falló (código {result.returncode}), "
                               f"intentando xelatex directo...")
                if logger.isEnabledFor(logging.DEBUG):
                    for line in result.stderr.splitlines():
                        logger.debug(f"  latexmk: {line}")
        except Exception as e:
            logger.warning(f"  latexmk excepción: {e}, intentando xelatex...")
    else:
        logger.info("  latexmk no encontrado, usando xelatex directo...")

    # Fallback: xelatex directo (2 pasadas)
    xelatex = shutil.which("xelatex")
    if not xelatex:
        logger.error("  xelatex no encontrado en PATH")
        return None

    for i in range(1, 3):
        logger.info(f"  Pasada {i}/2 de xelatex...")
        try:
            subprocess.run(
                [
                    xelatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={out_dir}",
                    main_tex,
                ],
                cwd=latex_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except Exception as e:
            logger.error(f"  Error en pasada {i}: {e}")
            return None

    pdf_path = os.path.join(out_dir, "main.pdf")
    if os.path.exists(pdf_path):
        return pdf_path

    logger.error(f"  PDF no generado. Revise {os.path.join(out_dir, 'main.log')}")
    return None


# ─── Generador principal ─────────────────────────────────────────────────────


def generate_latex_report(
    results_data: dict,
    output_dir: str,
    patient_id: str = "",
    dvh_curves: Optional[list] = None,
    screenshot_paths: Optional[list[str]] = None,
) -> Optional[str]:
    """
    Genera un reporte LaTeX profesional y lo compila a PDF.

    Args:
        results_data: Diccionario con metadata, structures y mird.
        output_dir: Directorio raíz de salida.
        patient_id: ID del paciente para la portada.
        dvh_curves: list of (name, d_vals_array, a_vals_array)
        screenshot_paths: Opcional, paths a screenshots reales del pipeline.

    Returns:
        ruta al PDF generado, o None si falla.
    """
    if jinja2 is None:
        logger.error("jinja2 no está instalado. No se puede generar el reporte LaTeX.")
        return None

    output_dir = os.path.normpath(output_dir)
    latex_dir = os.path.normpath(os.path.join(output_dir, "latex_report"))
    figures_dir = os.path.join(latex_dir, "figures")
    out_dir = os.path.normpath(os.path.join(latex_dir, "out"))
    os.makedirs(figures_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    meta = results_data.get("metadata", {})
    structures = results_data.get("structures", {})
    mird_data = results_data.get("mird", {})

    # ── Preparar datos para el template ──────────────────────────
    scene_name = meta.get("scene", "").replace("\\", "/").split("/")[-1]
    mctal_name = meta.get("mctal", "").replace("\\", "/").split("/")[-1]
    activity_gbq = float(meta.get("activity_gbq", 0))
    nps_val = int(meta.get("nps", 0))
    dims = meta.get("dimensions", [])
    flip_val = bool(meta.get("flip", True))
    gen_date = time.strftime("%Y-%m-%d %H:%M")

    # Estructuras ordenadas
    struct_order = ["higado", "tumor", "pretumor"]
    struct_labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}

    structure_list = []
    for key in struct_order:
        s = structures.get(key, {})
        if not s:
            continue
        structure_list.append({
            "key": key,
            "label": struct_labels.get(key, key),
            "index": int(s.get("index", 0)),
            "n_voxels": int(s.get("n_voxels", 0)),
            "volume_cm3": float(s.get("volume_cm3", 0)),
            "mean_dose_gy": float(s.get("mean_dose_gy", 0)),
            "min_dose_gy": float(s.get("min_dose_gy", 0)),
            "max_dose_gy": float(s.get("max_dose_gy", 0)),
            "std_dose_gy": float(s.get("std_dose_gy", 0)),
            "d98_gy": float(s.get("d98_gy", 0)),
            "d95_gy": float(s.get("d95_gy", 0)),
            "d70_gy": float(s.get("d70_gy", 0)),
            "d50_gy": float(s.get("d50_gy", 0)),
            "d5_gy": float(s.get("d5_gy", 0)),
            "d2_gy": float(s.get("d2_gy", 0)),
            "v30_pct": float(s.get("v30_pct", 0)),
            "v70_pct": float(s.get("v70_pct", 0)),
            "bed_gy": float(s.get("bed_gy", 0)),
            "eud_gy": float(s.get("eud_gy", 0)),
            "eqd2_gy": float(s.get("eqd2_gy", 0)),
        })

    mird_list = []
    for key in struct_order:
        entry = mird_data.get(key, {})
        if not entry:
            continue
        mird_list.append({
            "key": key,
            "label": struct_labels.get(key, key),
            "n_voxels": int(entry.get("n_voxels", 0)),
            "mean_dose_gy": float(entry.get("mean_dose_gy", 0)),
        })
    mird_activity_gbq = float(mird_data.get("activity_gbq", activity_gbq))

    # ── Generar figuras DVH ──────────────────────────────────────
    if dvh_curves:
        _plot_dvh_figures(dvh_curves, figures_dir)
    else:
        logger.warning("  No se proporcionaron curvas DVH")

    # ── Copiar screenshots reales ──────────────────────────────
    screenshot_rel = _copy_screenshots(figures_dir, screenshot_paths or [])

    # ── Renderizar template ──────────────────────────────────────
    env = _get_jinja_env()
    template = env.get_template(TEMPLATE_NAME)

    # ── Constantes físicas ──
    y90_half_life_h = 64.1
    lamda_decay = 0.0108
    mu_repair = 0.462
    tau_seconds = 332753.0
    mev2j = 1.602e-13

    # ── Tablas auxiliares ──
    alpha_beta_rows = [
        {"label": "Hígado sano", "value": 2.5, "type": "Tardío"},
        {"label": "Tumor", "value": 10.0, "type": "Agudo"},
    ]
    density_rows = [
        {"material": "Hígado", "density": 1.06, "use": "Parénquima hepático"},
        {"material": "Tumor", "density": 1.03, "use": "Lesión tumoral"},
        {"material": "Tejido blando", "density": 1.04, "use": "Fondo corporal"},
        {"material": "Aire/Pulmón", "density": 0.0012, "use": "Aire"},
    ]

    has_structures = len(structure_list) > 0
    has_biophysical = any(s.get("bed_gy", 0) > 0 for s in structure_list)
    has_dvh = dvh_curves is not None and len(dvh_curves) > 0

    # ── DVH files ──
    dvh_combined_rel = "figures/dvh_combined.png" if has_dvh else ""
    dvh_individual_files = []
    if has_dvh and dvh_curves:
        for name, _, _ in dvh_curves:
            safe_name = name.lower().replace(" ", "_").replace("í", "i").replace("ó", "o")
            dvh_individual_files.append(f"dvh_{safe_name}.png")

    # ── Parámetros de conclusión ──
    tumor = structures.get("tumor", {})
    higado = structures.get("higado", {})
    tumor_dmax = float(tumor.get("max_dose_gy", 0))
    tumor_dmean = float(tumor.get("mean_dose_gy", 0))
    liver_dmean = float(higado.get("mean_dose_gy", 0))
    mird_tumor = mird_data.get("tumor", {}).get("mean_dose_gy", 0)
    mird_liver = mird_data.get("liver", {}).get("mean_dose_gy", 0)
    ratio = float(mird_tumor) / max(float(mird_liver), 0.001) if mird_liver else 0

    template_vars = {
        # ── Portada ──
        "patient_id": patient_id,
        "scene_name": scene_name,
        "mctal_name": mctal_name,
        "gen_date": gen_date,
        # ── Estudio ──
        "activity_gbq": activity_gbq,
        "nps": nps_val,
        "dim_x": int(dims[0]) if len(dims) > 0 else 0,
        "dim_y": int(dims[1]) if len(dims) > 1 else 0,
        "dim_z": int(dims[2]) if len(dims) > 2 else 0,
        "flip": flip_val,
        # ── Constantes físicas ──
        "y90_half_life_h": y90_half_life_h,
        "lamda_decay": lamda_decay,
        "mu_repair": mu_repair,
        "tau_seconds": int(tau_seconds),
        "mev2j": mev2j,
        # ── Tablas ──
        "alpha_beta_rows": alpha_beta_rows,
        "density_rows": density_rows,
        # ── Estructuras ──
        "has_structures": has_structures,
        "structure_list": structure_list,
        "has_biophysical": has_biophysical,
        # ── MIRD ──
        "mird_list": mird_list,
        "mird_activity_gbq": mird_activity_gbq,
        # ── DVH ──
        "has_dvh": has_dvh,
        "dvh_combined_rel": dvh_combined_rel,
        "dvh_individual_files": dvh_individual_files,
        # ── Screenshots ──
        "has_screenshots": len(screenshot_rel) > 0,
        "screenshot_list": screenshot_rel,
        # ── Conclusiones ──
        "tumor_dmax": tumor_dmax,
        "tumor_dmean": tumor_dmean,
        "liver_dmean": liver_dmean,
        "ratio": ratio,
    }

    tex_content = template.render(**template_vars)
    main_tex_path = os.path.join(latex_dir, "main.tex")
    with open(main_tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)
    logger.info(f"  Template renderizado: {main_tex_path}")

    # ── compile.bat de respaldo ──────────────────────────────────
    xelatex_path = shutil.which("xelatex") or "xelatex"
    bat_content = f"""@echo off
REM compile.bat generado por latex_report_generator.py
REM Compilacion manual de respaldo

set OUTDIR=%~dp0out
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

"{xelatex_path}" -interaction=nonstopmode -halt-on-error -output-directory="%OUTDIR%" "%~dp0main.tex"
"{xelatex_path}" -interaction=nonstopmode -halt-on-error -output-directory="%OUTDIR%" "%~dp0main.tex"
echo.
echo Si se genero correctamente, el PDF esta en: %OUTDIR%\\main.pdf
pause
"""
    compile_bat = os.path.join(latex_dir, COMPILE_BAT_NAME)
    with open(compile_bat, "w", encoding="utf-8") as f:
        f.write(bat_content)
    logger.info(f"  compile.bat escrito: {compile_bat}")

    # ── Copiar figures a out/ ────────────────────────────────────
    for fname in os.listdir(figures_dir):
        shutil.copy2(os.path.join(figures_dir, fname), os.path.join(out_dir, fname))

    # ── Compilar ─────────────────────────────────────────────────
    pdf_path = _compile_latex(latex_dir)
    if not pdf_path:
        return None

    # ── Copiar PDF a output_dir ──────────────────────────────────
    final_pdf = os.path.join(output_dir, "dosimetria_report_latex.pdf")
    shutil.copy2(pdf_path, final_pdf)
    size_kb = os.path.getsize(final_pdf) / 1024
    logger.info(f"  Reporte LaTeX copiado a: {final_pdf} ({size_kb:.0f} KB)")
    return final_pdf


# ── Demo sintético ────────────────────────────────────────────────────────────

def _demo_data() -> dict:
    """Retorna datos sintéticos de demostración."""
    return {
        "metadata": {
            "scene": "3Dosim_scene.mrb",
            "mctal": "mctal_demo.m",
            "activity_gbq": 3.137,
            "dimensions": [512, 512, 171],
            "nps": 100000000,
            "flip": True,
        },
        "structures": {
            "higado": {
                "index": 90, "n_voxels": 950000, "volume_cm3": 1250.0,
                "mean_dose_gy": 25.3, "min_dose_gy": 0.1, "max_dose_gy": 85.2,
                "std_dose_gy": 15.1, "d98_gy": 2.1, "d70_gy": 15.2,
                "d50_gy": 22.1, "d2_gy": 55.2, "bed_gy": 35.8, "eud_gy": 20.4,
                "eqd2_gy": 28.3, "v30_pct": 12.5, "v70_pct": 3.2,
            },
            "tumor": {
                "index": 100, "n_voxels": 12000, "volume_cm3": 15.8,
                "mean_dose_gy": 120.5, "min_dose_gy": 45.2, "max_dose_gy": 210.3,
                "std_dose_gy": 30.2, "d98_gy": 55.2, "d70_gy": 95.2,
                "d50_gy": 118.0, "d2_gy": 180.1, "bed_gy": 185.2, "eud_gy": 110.3,
                "eqd2_gy": 42.1, "v30_pct": 95.0, "v70_pct": 60.0,
            },
            "pretumor": {
                "index": 200, "n_voxels": 45000, "volume_cm3": 59.2,
                "mean_dose_gy": 18.7, "min_dose_gy": 0.5, "max_dose_gy": 55.2,
                "std_dose_gy": 10.2, "d98_gy": 1.5, "d70_gy": 10.2,
                "d50_gy": 16.5, "d2_gy": 40.1, "bed_gy": 25.3, "eud_gy": 15.2,
                "eqd2_gy": 20.4, "v30_pct": 5.0, "v70_pct": 1.0,
            },
        },
        "mird": {
            "activity_gbq": 3.137,
            "liver": {"n_voxels": 950000, "mean_dose_gy": 25.3},
            "tumor": {"n_voxels": 12000, "mean_dose_gy": 120.5},
            "pretumor": {"n_voxels": 45000, "mean_dose_gy": 18.7},
        },
    }


def _demo_dvh() -> list:
    """Retorna curvas DVH sintéticas con aspecto realista (100 puntos c/u)."""
    import numpy as np

    def _sigmoid_dvh(d50: float, k: float, d_max: float) -> tuple:
        """Genera curva DVH sigmoide dosis → volumen."""
        d = np.linspace(0, d_max, 100)
        v = 100 / (1 + np.exp(k * (d - d50) / d_max))
        return d.tolist(), v.tolist()

    return [
        ("Hígado", *_sigmoid_dvh(22, 8, 60)),
        ("Tumor",  *_sigmoid_dvh(110, 5, 220)),
        ("Peritumoral", *_sigmoid_dvh(18, 6, 60)),
    ]


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Generar reporte LaTeX desde JSON o demo"
    )
    parser.add_argument("--json", help="Ruta a dosimetria_report.json")
    parser.add_argument("--output", default=None, help="Directorio de salida")
    parser.add_argument("--patient-id", default="", help="ID del paciente")
    parser.add_argument(
        "--demo", action="store_true",
        help="Ejecutar con datos sintéticos",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.demo:
        logger.info("=" * 60)
        logger.info("  Demostración: Reporte LaTeX con datos sintéticos")
        logger.info("=" * 60)

        demo_data = _demo_data()

        out_dir = args.output or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "resultados_test", "latex_demo",
        )

        screenshots_dir = r"C:\MAT\3Dosim\ai-pipe\screenshots"
        demo_screenshots = []
        for fname in ["092801_04_fusion_ct_pet_registrada.png", "095544_08_segmentacion.png"]:
            fp = os.path.join(screenshots_dir, fname)
            if os.path.isfile(fp):
                demo_screenshots.append(fp)

        pdf = generate_latex_report(
            demo_data, out_dir,
            patient_id=args.patient_id or "DEMO-001",
            dvh_curves=_demo_dvh(),
            screenshot_paths=demo_screenshots,
        )

        if pdf:
            logger.info(f"\n  ✅ PDF generado: {pdf}")
            logger.info(f"  Tamaño: {os.path.getsize(pdf) / 1024:.0f} KB")
        else:
            logger.error("\n  ❌ No se pudo generar el PDF")
        sys.exit(0)

    if args.json:
        with open(args.json, "r") as f:
            data = json.load(f)
        out_dir = args.output or os.path.dirname(os.path.abspath(args.json))
        pdf = generate_latex_report(data, out_dir, patient_id=args.patient_id)
        if pdf:
            print(f"\nReporte LaTeX generado: {pdf}")
        else:
            print("\nERROR: No se pudo generar el reporte LaTeX")
            sys.exit(1)
    else:
        parser.print_help()
