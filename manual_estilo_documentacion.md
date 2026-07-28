# Manual de Estilo — Documentación Técnica 3Dosim-app

**Objetivo de este manual:** que los 4 documentos (`modulo_1`, `modulo_2`, `modulo_3`, `calculo_dosis_mctall_kernel`) —y los que se agreguen después— dejen de ser básicamente *material de referencia* (tablas, fórmulas, código) y se conviertan en documentación que explica, no solo que enumera.

Este manual está basado en dos marcos de referencia consolidados de documentación técnica:
- **Diátaxis / Divio Documentation System** — el estándar más usado hoy para distinguir tipos de documentación según su función.
- **Google Developer Documentation Style Guide** — para convenciones de redacción, voz y notación matemática.

---

## 1. El diagnóstico, en términos del marco Diátaxis

Diátaxis divide toda documentación técnica en 4 funciones distintas, cada una con su propia lógica de escritura: <cite index="16-1">tutoriales y guías how-to (orientadas a la práctica) frente a explicación y referencia (orientadas a la teoría)</cite>. La referencia responde "¿qué es esto exactamente?"; la explicación responde "¿por qué es así, y por qué importa?".

Los 4 documentos de 3Dosim son **casi 100% referencia y 0% explicación**: tablas de parámetros, fórmulas, código, checklists de QA — todo eso es referencia legítima y necesaria. Lo que falta es la capa de explicación que le da sentido a esa referencia. Como advierte el propio framework Divio sobre las guías de referencia: <cite index="20-1">hay que evitar la tentación de usar el material de referencia para dar instrucciones o dejar que se desarrollen explicaciones de conceptos — eso corresponde a otra sección, y en cambio hay que enlazar a explicación cuando corresponda</cite>. El problema en 3Dosim es el inverso: la referencia está, pero el enlace/sección de "explicación" a la que debería remitir **no existe**, así que el lector se queda solo con la tabla.

**Regla general de este manual: ninguna sección puede ser 100% referencia. Toda sección técnica necesita su párrafo de explicación antes de la tabla/fórmula/código.**

---

## 2. Estructura obligatoria de cada sección (`\section`)

Cada sección de nivel `\section{}` debe seguir este orden fijo:

1. **Párrafo de apertura (3-6 frases, prosa, sin tablas ni fórmulas).** Responde:
   - ¿Qué problema resuelve este paso dentro del pipeline?
   - ¿Qué entra y qué sale, en términos generales (antes del detalle técnico)?
   - ¿Por qué se implementó así (la decisión de diseño), no solo qué hace?
2. **Tabla de acrónimos** (si aplica) — va *después* del párrafo de apertura, nunca antes. Hoy en varias secciones aparece primero, lo que hace que el lector entre a una tabla antes de saber de qué se está hablando.
3. **Detalle técnico** (subsecciones, fórmulas, tablas, código).
4. **Cierre breve (opcional pero recomendado, 1-2 frases):** qué pasa si este paso falla, o cómo se conecta con el paso siguiente.

> Ejemplo de lo que falta hoy: la sección "Comparación de Métodos" en `calculo_dosis_mctall_kernel.tex` pasa directo a una tabla comparativa sin ningún párrafo previo que explique cuándo importa elegir un método u otro y qué se arriesga si se elige mal. Ese es exactamente el párrafo de apertura que el punto 1 exige.

---

## 3. Regla específica para fórmulas — "nunca una fórmula sola"

Esta es la regla más importante de este manual, porque es la que más se está incumpliendo. Ninguna fórmula puede aparecer sin **las 4 partes siguientes**, en este orden:

1. **Motivación en prosa** (1-2 frases): qué representa físicamente esta fórmula y por qué la necesitamos en este punto del pipeline.
2. **Definición de cada variable en prosa dentro del texto**, no solo en una tabla de símbolos aparte. La tabla de símbolos puede coexistir, pero no puede ser la única explicación — el propio Google Style Guide recomienda que, para <cite index="7-1">fórmulas complejas o multilínea que son difíciles de representar con claridad, conviene apoyarse en diagramas u otras imágenes que ayuden a la comprensión</cite>, no solo en la notación matemática aislada.
3. **Un ejemplo numérico breve** con valores reales del dominio (actividad tipo, dosis tipo Y-90, etc.) — no hace falta en cada fórmula trivial, pero sí en toda fórmula que alimenta un resultado clínico (dosis absorbida, BED, EQD2).
4. **Interpretación del resultado**: qué significa clínicamente/físicamente un valor alto o bajo de esa magnitud.

**Ejemplo de aplicación** (sección "Fundamentos Físicos" de `calculo_dosis_mctall_kernel.tex`, que hoy pasa directo a una lista de constantes del ⁹⁰Y sin ningún marco): el párrafo de apertura debería explicar primero por qué esas magnitudes concretas (vida media, alcance en tejido) son las que determinan el resto del documento — por ejemplo, que el alcance limitado en tejido es lo que justifica tratar la dosis como local y no como un problema de transporte a larga distancia, y que la vida media entra directamente en la integración temporal de la sección de dosis absorbida más adelante.

---

## 4. Reglas de redacción (voz, tono, formato)

Adaptado del Google Developer Documentation Style Guide para este proyecto:

- **Voz activa, sujeto explícito.** <cite index="5-1">Usar voz activa: dejar claro quién realiza la acción</cite>. Evitar "se normaliza el kernel" cuando lo correcto es "`dose_kernel.py` normaliza el kernel" — así se sabe qué componente hace qué, algo crítico en un pipeline con muchos módulos.
- **Condición antes de instrucción.** <cite index="5-1">Poner las condiciones antes de las instrucciones, no después</cite> — por ejemplo: "Si el PET no está en Bq/mL, calibrar antes de fusionar" en vez de "Fusionar el PET con el CT, siempre que ya esté calibrado en Bq/mL".
- **Títulos y encabezados en minúscula tipo oración** (salvo nombres propios/acrónimos): <cite index="5-1">usar mayúscula de oración para títulos de documento y encabezados de sección</cite>.
- **Un estilo editorial único para todo el proyecto.** No importa si se elige tildes sí/no, mayúscula de título o de oración — lo que importa es que <cite index="2-1">la organización adopte una sola guía editorial y la respete</cite>. Hoy `modulo_1`/`modulo_2` están sin tildes y `modulo_3`/`kernel` con tildes correctas: eso rompe la regla más básica de cualquier estilo editorial. **Decisión de este proyecto: usar español con tildes y eñes completas en los 4 documentos.**
- **Reglas, no dogma.** Como recuerda el propio Google guide: <cite index="1-1">estas son pautas, no reglas — hay que apartarse de ellas cuando hacerlo mejora el contenido</cite>. Este manual funciona igual: es la referencia por defecto, no una camisa de fuerza.

---

## 5. Checklist de revisión (para aplicar antes de cerrar cada sección o cada PDF)

- [ ] ¿Hay un párrafo de apertura en prosa antes de la primera tabla/subsección/fórmula?
- [ ] ¿Cada fórmula tiene motivación + variables explicadas en prosa + interpretación del resultado?
- [ ] ¿Las fórmulas clínicamente relevantes (dosis, BED, EQD2, actividad) tienen un ejemplo numérico?
- [ ] ¿Hay al menos una figura real (no ASCII-art) donde el concepto sea inherentemente espacial (geometría, DVH, mapas de dosis)?
- [ ] ¿El texto usa tildes/eñes de forma consistente con el resto del proyecto?
- [ ] ¿Las tablas de QA/checklist tienen un criterio específico de esa etapa, no una fila copiada de otra?
- [ ] ¿Los entornos `\begin{tcolorbox}` y `\end{tcolorbox}` (u otros entornos) están balanceados?
- [ ] ¿La sección explica qué pasa si el paso falla, o remite a la tabla de QA correspondiente?

---

## 6. Nota sobre "manual de estilo" vs. correcciones puntuales

Este documento reemplaza el enfoque de "te marco línea por línea qué está mal" por reglas reutilizables que se pueden aplicar a cualquier sección nueva, presente o futura, sin tener que auditarla desde cero cada vez. La idea es que este manual se pueda consultar antes de escribir una sección nueva, no solo después.

Como sugiere la práctica estándar de documentación técnica: <cite index="18-1">el primer párrafo de cada sección/tema es crítico para establecer el contexto — al plantear el propósito y alcance del contenido desde el principio, el lector puede entender de inmediato si llegó al lugar correcto</cite>. Ese primer párrafo es exactamente lo que falta hoy en la mayoría de las secciones de 3Dosim, y es la corrección de mayor impacto que puede hacerse.

---

## 7. Siguiente paso: convertir este manual en un Skill de Claude

Como comentás que ahora la IA tiene acceso a internet: además de este manual en texto, puedo empaquetarlo como un **Skill** (`SKILL.md`) para que cualquier instancia de Claude que trabaje en este repo (yo mismo en otra conversación, u otra persona del equipo usando Claude) aplique automáticamente estas reglas al escribir o revisar la documentación, en vez de tener que copiar/pegar este manual cada vez.

Ese Skill incluiría:
- Las reglas de estructura y de fórmulas de este manual, en formato que Claude puede seguir paso a paso.
- Los scripts de auditoría que ya usé (medir palabras de prosa antes de la primera subsección, chequear balance de `tcolorbox`, detectar inconsistencia de tildes) como parte del proceso de revisión automática.
- Un checklist de salida antes de considerar una sección "terminada".

¿Querés que lo genere ahora como `SKILL.md`, o preferís primero aplicar este manual a mano en `calculo_dosis_mctall_kernel.tex` (el más corto y conceptualmente más importante) para validar que las reglas funcionan bien antes de automatizarlas?
