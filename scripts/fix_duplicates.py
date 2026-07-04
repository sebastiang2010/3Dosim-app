import os

BASE = "C:/programas/3Dosim/3Dosim_v4/docs"

def fix_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    lines = text.splitlines()
    new_lines = []
    seen_include = False
    seen_palette = False
    seen_resumen = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # Remove duplicate tcolorbox include
        if r'\usepackage[most]{tcolorbox}' in line:
            if seen_include:
                i += 1
                continue
            seen_include = True
            new_lines.append(line)
            i += 1
            continue
        # Remove duplicate palette block (detect "PALETA DE COLORES 3Dosim" comment)
        if 'PALETA DE COLORES 3Dosim' in line:
            if seen_palette:
                # Skip until next comment line or \geometry{ or \pagestyle{ or empty line after block
                j = i
                while j < len(lines) and not (lines[j].strip().startswith('%') or lines[j].strip().startswith('\\\\')):
                    j += 1
                # Actually skip a fixed number of lines or until a known marker
                # Better: skip until the titleformat block ends, but let's just skip until next line with '% ===' or '\geometry' or '\pagestyle'
                while j < len(lines) and not (lines[j].strip().startswith(r'\ge') or lines[j].strip().startswith(r'\pa') or lines[j].strip().startswith(r'% ===')):
                    j += 1
                i = j
                continue
            seen_palette = True
            new_lines.append(line)
            i += 1
            continue
        # Remove duplicate Resumen
        if r'\section*{Resumen}' in line or r'\addcontentsline{toc}{section}{Resumen}' in line:
            if seen_resumen:
                # Skip until next main section marker or blank line followed by section
                j = i
                while j < len(lines) and not lines[j].strip().startswith(r'\section'):
                    j += 1
                i = j
                continue
            seen_resumen = True
            new_lines.append(line)
            i += 1
            continue
        new_lines.append(line)
        i += 1
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    print(f"Fixed {os.path.basename(path)}")

if __name__ == '__main__':
    for n in [1,2,3]:
        fix_file(os.path.join(BASE, f'modulo_{n}', f'modulo_{n}_completo.tex'))
