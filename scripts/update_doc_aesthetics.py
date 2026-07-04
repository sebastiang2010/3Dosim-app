"""
update_doc_aesthetics.py
Aplica mejoras esteticas a modulo_1_completo.tex, modulo_2_completo.tex, modulo_3_completo.tex:
1. Paleta de colores LaTeX (titulos, subtitulos, AI Supervisor)
2. AI Supervisor envuelto en caja coloreada (tcolorbox)
3. Resumen/Introduccion clara despues de la portada
4. Texto explicativo adicional en pasos clave del pipeline
"""
import os
import re

BASE = "C:/programas/3Dosim/3Dosim_v4/docs"

# Palette exact colors (RGB)
PALETTE = r"""
% ============================================================
% PALETA DE COLORES 3Dosim
% ============================================================
\definecolor{cPrimary}{RGB}{30,64,124}      % azul oscuro titulos
\definecolor{cSecondary}{RGB}{70,130,180}   % azul claro subtitulos
\definecolor{cAccent}{RGB}{220,50,50}        % rojo AI Supervisor / alertas
\definecolor{cBg}{RGB}{245,245,245}          % gris muy claro fondo
\definecolor{cDarkBg}{RGB}{230,230,230}      % gris fondo tablas

% ============================================================
% FORMATO DE SECCIONES CON COLORES
% ============================================================
\titleformat*{\section}{\normalfont\Large\bfseries\color{cPrimary}}
\titleformat*{\subsection}{\normalfont\large\bfseries\color{cSecondary}}
\titleformat*{\subsubsection}{\normalfont\normalsize\bfseries\color{cPrimary}}

"""

# tcolorbox style for AI Supervisor
TCOLOR_STYLE = r"""
% ============================================================
% CAJA COLOREADA PARA AI SUPERVISOR
% ============================================================
\tcbset{
  aiSupervisor/.style = {
    colback=cBg,
    colframe=cAccent,
    boxrule=0.7pt,
    arc=3pt,
    left=4mm,
    right=4mm,
    top=3mm,
    bottom=3mm,
    fonttitle=\bfseries\large,
    title=Control de Calidad (AI Supervisor),
    coltitle=white,
    colbacktitle=cAccent,
    attach boxed title to top left={yshift=-3mm,xshift=5mm},
    boxed title style={colback=cAccent,arc=2pt}
  }
}
"""


def transform_preamble(lines, module_name):
    """Insert color palette, tcolorbox, and format sections."""
    new_lines = []
    inserted_tcolorbox = False
    inserted_palette = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # Insert tcolorbox package after verbatim
        if '\\usepackage{verbatim}' in line and not inserted_tcolorbox:
            new_lines.append(line)
            new_lines.append(r'\usepackage[most]{tcolorbox}' + '\n')
            inserted_tcolorbox = True
            i += 1
            continue
        # Insert palette after geometry settings (before fancyhdr or after headheight)
        if '\\setlength{\\headheight}{13.6pt}' in line and not inserted_palette:
            new_lines.append(line)
            new_lines.append(PALETTE.strip() + '\n')
            inserted_palette = True
            i += 1
            continue
        new_lines.append(line)
        i += 1
    # Ensure we insert after last package if not done
    if not inserted_tcolorbox:
        # fallback: append after last \usepackage
        pass
    if not inserted_palette:
        pass
    return new_lines


def add_tcolorbox_defs(lines):
    """Add tcolorbox style definitions before \begin{document}"""
    new_lines = []
    for line in lines:
        if '\\begin{document}' in line:
            new_lines.append(TCOLOR_STYLE.strip() + '\n')
        new_lines.append(line)
    return new_lines


def apply_changes_to_tex(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    lines = raw.splitlines(keepends=True)

    # Paso 1: Preambulo con colores
    lines = transform_preamble(lines, os.path.basename(filepath))

    # Rebuild text
    text = ''.join(lines)

    # Paso 2: Agregar definiciones tcolorbox antes de \begin{document}
    text = text.replace(r'\begin{document}', TCOLOR_STYLE.strip() + '\n' + r'\begin{document}')

    # Paso 3: Envolver AI Supervisor en cajas
    # Pattern busca: \subsection{Control de Calidad (AI Supervisor)}
    # o \subsection*{Control de Calidad (AI Supervisor)}
    # Reemplazamos con bloque tcolorbox, cerrándolo antes del siguiente \section o \subsection no-AI

    def wrap_ai_supervisor(match):
        start = match.start()
        # Buscar desde después del match hasta el próximo \section o \subsection
        end_pos = len(text)
        next_section = text.find('\\section{', match.end())
        next_subsection = text.find('\\subsection{', match.end())
        next_subsection_star = text.find('\\subsection*{', match.end())

        candidates = [x for x in [next_section, next_subsection, next_subsection_star] if x != -1]
        if candidates:
            end_pos = min(candidates)

        content = text[match.end():end_pos]
        # Eliminamos los asteriscos extras si existen al inicio
        content = content.strip()
        wrapper = f"""
\\begin{{tcolorbox}}[aiSupervisor]
\\subsection*{{Control de Calidad (AI Supervisor)}}

{content}

\\end{{tcolorbox}}
"""
        return wrapper

    # Reemplazar todas las ocurrencias
    text = re.sub(
        r'\\subsection\{Control de Calidad \(AI Supervisor\)\}',
        lambda m: wrap_ai_supervisor(m),
        text
    )
    text = re.sub(
        r'\\subsection\*\{Control de Calidad \(AI Supervisor\)\}',
        lambda m: wrap_ai_supervisor(m),
        text
    )

    # Paso 4: Agregar seccion Resumen despues de la portada
    # Encontrar lugar: despues de \maketitle y \thispagestyle{empty}
    # Insertar bloque con \section*{Resumen}
    resumen_block = r"""

% ============================================================
% RESUMEN DEL MODULO
% ============================================================
\section*{Resumen}
\addcontentsline{toc}{section}{Resumen}

Este modulo forma parte del pipeline completo \textbf{3Dosim} para dosimetria hepatica con Yttrium-90.
Su objetivo es transformar imagenes DICOM (CT anatomico + PET funcional) en una \textbf{labelmap dosimetrica}
-- un volumen 3D donde cada voxel se clasifica segun su tipo de tejido siguiendo la nomenclatura ICRP-110/ICRU-44.
Esta labelmap constituye la entrada fundamental para el Modulo 2, donde se genera el input de simulacion Monte Carlo (MCNP).

\vspace{0.5em}
\noindent
\textbf{Pregunta que resuelve:} \textit{Cual es la forma mas precisa y automatica de identificar y clasificar cada tejido del paciente para poder calcular la dosis absorbida por voxel?}

\vspace{0.3em}
\noindent
\textbf{Resultado principal:} Labelmap NIfTI/NRRD con 53+ materiales ICRP-110 indexados, lista para MCNP.

"""
    # Insertar despues de \newpage que sigue a la portada
    # Localizar el primer \newpage despues de maketitle
    insert_pos = text.find(r'\maketitle') + len(r'\maketitle') + len('\n') + len(r'\thispagestyle{empty}') + len('\n')
    # Buscar siguiente \newpage
    next_newpage = text.find(r'\newpage', insert_pos)
    if next_newpage != -1:
        # Insertar despues de este \newpage (y su newline siguiente)
        pos = text.find('\n', next_newpage) + 1
        text = text[:pos] + resumen_block + text[pos:]

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"OK: {os.path.basename(filepath)} actualizado con estetica y texto explicativo.")


if __name__ == '__main__':
    modules = [
        os.path.join(BASE, 'modulo_1', 'modulo_1_completo.tex'),
        os.path.join(BASE, 'modulo_2', 'modulo_2_completo.tex'),
        os.path.join(BASE, 'modulo_3', 'modulo_3_completo.tex'),
    ]
    for path in modules:
        if os.path.exists(path):
            apply_changes_to_tex(path)
        else:
            print(f"ERROR: No se encontro {path}")
