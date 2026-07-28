# Revisión de Texto y Contenido — Documentación 3Dosim-app

**Alcance:** `docs/modulo_1/modulo_1_completo_backup.tex`, `docs/modulo_2/modulo_2_completo_backup.tex`, `docs/modulo_3/modulo_3_completo_backup.tex`, `docs/modulo_3/calculo_dosis_mctall_kernel.tex`

La estética ya está resuelta. Esta pasada se enfoca **solo en el texto/contenido**: bugs de estructura LaTeX que rompen el documento, contenido duplicado, inconsistencias de idioma, y un hallazgo importante donde la documentación describe un comportamiento que contradice el fix ya identificado en el código.

---

## 1. 🔴 Bugs estructurales reales (no solo estética — pueden romper la compilación o duplicar contenido en el PDF)

### 1.1 `mod1.tex` — sección "Resumen" duplicada íntegramente

Líneas **137–152** y **158–172** son exactamente el mismo texto repetido dos veces seguidas (mismo `\section*{Resumen}`, mismo párrafo introductorio, misma "Pregunta que resuelve" y "Resultado principal"). En el PDF esto se ve como el resumen apareciendo dos veces consecutivas.

### 1.2 `mod2.tex` — sección "Apéndice: Constantes Físicas" repetida 4 veces, con contenido equivocado en las primeras 3

Líneas **2579, 2606, 2633, 2660**: el encabezado `\section*{Apendice: Constantes Fisicas}` aparece 4 veces consecutivas. Las **primeras 3 repeticiones** van seguidas de la misma tabla de verificación de pipeline ("Flujo completo ejecutado", "Conservación de energía", etc.) — que no tiene nada que ver con constantes físicas. El contenido real del apéndice (tabla de isótopos, vida media, energías beta) **solo aparece en la 4ª repetición**. Da la impresión de que una tabla de otra sección quedó "atrapada" bajo el título equivocado tres veces por un problema en el script que consolidó los `.md` en el `.tex`.

### 1.3 Desbalance de entornos `tcolorbox` — el más grave

| Archivo | `\begin{tcolorbox}` | `\end{tcolorbox}` | Diferencia |
|---|---|---|---|
| mod1.tex | 48 | 112 | **-64** |
| mod2.tex | 16 | 24 | **-8** |
| mod3.tex | 9 | 9 | 0 ✅ |
| kernel.tex | 0 | 0 | 0 ✅ |

`mod1.tex` tiene **64 `\end{tcolorbox}` de más** (o `\begin` de menos). En el punto concreto que revisé (mod2.tex, línea 2553-2555) encontré la causa: hay dos `\begin{tcolorbox}[aiSupervisor]` abiertos **uno tras otro** sin cerrar el primero, y luego un solo `\end{tcolorbox}` que cierra apenas uno. Esto es exactamente el mismo patrón de "duplicación por concatenación" que causó los dos bugs anteriores.

**Por qué importa:** este tipo de desbalance en LaTeX normalmente **falla la compilación** (`\end{tcolorbox} without matching \begin`) o, si el motor lo tolera, deja cajas de color vacías, mal ubicadas, o corta contenido de la página siguiente. Si el PDF que ya generaste se ve bien, probablemente sea porque compilaste una versión distinta/más reciente de estos archivos — vale la pena confirmar que el `.tex` que estás usando para compilar no es este mismo con el bug latente.

**Acción sugerida:** correr un chequeo automático de balance de entornos antes de cada compilación (ver sección 4).

---

## 2. 🟡 Inconsistencia de idioma entre documentos

| Archivo | Caracteres acentuados (á é í ó ú ñ) |
|---|---|
| mod1.tex | **0** |
| mod2.tex | **0** |
| mod3.tex | 700 |
| kernel.tex | 200 |

`modulo_1` y `modulo_2` están escritos **sin ninguna tilde ni eñe** ("Segmentacion", "Dosimetria", "Modulo", "Metodo", "validacion", "funcion", "tamano", "pequeno"...), mientras que `modulo_3` y el documento de kernel sí usan acentuación correcta ("Módulo", "Análisis", "convolución", "análisis"). Esto se nota mucho al leer los 4 documentos como una colección: los dos primeros se sienten como un borrador y los dos últimos como el texto ya revisado.

**Acción sugerida:** pasar `mod1.tex` y `mod2.tex` por un corrector ortográfico de español (o pedirme que lo haga) para unificar el nivel de pulido con `mod3`/`kernel`.

---

## 3. 🟡 Contenido de checklist/QA clonado sin adaptar (dilución del valor del contenido)

Estas filas aparecen **idénticas, palabra por palabra, múltiples veces** en la misma tabla-tipo repetida para distintas etapas del pipeline, sin que el criterio se ajuste a la etapa específica:

| Fila repetida | Archivo | Veces |
|---|---|---|
| "Integridad phantom — Todos los índices esperados presentes — Crítico" | mod1.tex | 9 |
| "Keywords MCNP presentes — Falta C, cells, surfaces, data — Crítico" | mod2.tex | 4 |
| "VOIs requeridos presentes — Falta Liver/Tumor/Kidney — Crítico" | mod2.tex | 4 |
| "Todos los materiales tienen celda U=1 — Falta celda voxel — Crítico" | mod2.tex | 4 |
| "Espectro definido para isótopo — Falta entrada en SPECTRA dict — Crítico" | mod2.tex | 4 |
| "CORA/CORB/CORC definidos..." / "ENDSD cierra TMESH..." | mod2.tex | 4 cada una |
| "Pares valor/error completos...", "DVH con 4 curvas...", "Nodos CT/PET/Labelmap presentes..." | mod3.tex | 2 cada una |

No es necesariamente un "error", pero como lector es una señal de que estas tablas de control de calidad se generaron con una plantilla y se pegaron por cada paso del pipeline sin personalizar el criterio de fallo real de ese paso puntual. Vale la pena revisar al menos las de mod1 (9 repeticiones) y decidir si cada etapa realmente comparte el mismo criterio o si merece uno específico.

---

## 4. 🔴 Hallazgo de contenido técnico — la documentación describe el comportamiento que ya identificamos como bug

Este es el hallazgo más importante de esta revisión.

**`calculo_dosis_mctall_kernel.tex`, sección "Normalización del kernel" (líneas 350–370):**
El texto explica que el kernel tiene la propiedad de que su integral espacial es igual a la dosis total por 1 Bq, y luego dice que **"para la convolución clínica, el kernel se normaliza a suma unitaria"** (`K_norm = K / sum(K)`), presentándolo como el paso correcto para "conservar la actividad total".

**`modulo_3_completo_backup.tex`, línea 758 (flujo MATLAB `convkernel.m`):**
Documenta literalmente el paso `Kernel = Kernel / sum(Kernel(:))` como parte normal del flujo, e incluso define `K_norm` (kernel normalizado, suma = 1) como variable estándar de la fórmula final de dosis.

**El problema:** en la misma sección de `mod3.tex` (línea 752) el texto también dice, correctamente, que la ruta Kernel **no** debe multiplicar por τ ni por A después de la convolución **porque `kernel.mat` ya incluye esos factores** (es decir, ya viene calibrado en Gy absolutos). Esas dos afirmaciones son contradictorias entre sí: si el kernel ya trae la calibración absoluta horneada, dividirlo por su propia suma para normalizarlo a 1 **destruye exactamente esa calibración** — que es la causa raíz confirmada de las dosis anómalamente bajas que ya identificamos en `run_dosimetry_from_scene.py` (el `load_kernel()` local que normaliza sin condición, vs. `dose_kernel.py::get_kernel(normalize=False)` que es el fix correcto y no se está usando).

**En otras palabras:** la documentación no solo no refleja el fix — activamente lo contradice, explicando la normalización como el paso "correcto" del método. Si alguien (o algún futuro colaborador) usa esta doc como referencia, va a asumir que normalizar el kernel es lo que hay que hacer, reintroduciendo el bug.

**Acción sugerida (contenido, no solo redacción):** reescribir esa subsección para explicar:
1. Por qué `kernel.mat` ya viene calibrado en Gy/GBq desde MATLAB (τ × A incluidos).
2. Por qué normalizar a suma 1 en el paso Python/MATLAB destruye esa calibración.
3. Cuál es el paso correcto: `A[Bq/mL] × V_voxel → A[Bq]` sin normalización posterior del kernel.

Puedo redactar ese párrafo corregido si querés, referenciando el commit `e8bab9e` y `dose_kernel.py::get_kernel()`.

---

## 5. Resumen de prioridades

| # | Hallazgo | Tipo | Prioridad |
|---|---|---|---|
| 1 | Documentación de normalización de kernel contradice el fix ya identificado | Técnico/contenido | 🔴 Alta |
| 2 | Desbalance `tcolorbox` (-64 en mod1, -8 en mod2) | Bug estructural LaTeX | 🔴 Alta |
| 3 | Sección "Resumen" duplicada en mod1 | Bug de contenido | 🔴 Alta |
| 4 | Sección "Apéndice: Constantes Físicas" repetida 4x con contenido equivocado en mod2 | Bug de contenido | 🔴 Alta |
| 5 | mod1/mod2 sin tildes vs. mod3/kernel con tildes | Consistencia de idioma | 🟡 Media |
| 6 | Filas de QA clonadas sin adaptar (9x, 4x, 2x) | Calidad de contenido | 🟡 Media |

---

## 6. Siguiente paso sugerido

Puedo avanzar directo sobre cualquiera de estos:
- Corregir el desbalance de `tcolorbox` y las duplicaciones de sección en `mod1.tex`/`mod2.tex`.
- Reescribir la sección de normalización del kernel en `calculo_dosis_mctall_kernel.tex` y `modulo_3_completo_backup.tex` para que quede alineada con el fix real.
- Pasar `mod1.tex` y `mod2.tex` por corrección ortográfica completa (tildes/eñes) para emparejarlos con el nivel de `mod3`/`kernel`.

Decime por cuál arrancamos.
