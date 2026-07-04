# Eliminación de Camilla y Aire Exterior

> **El CT incluye la camilla (mesa de exploración) y el aire alrededor del paciente, que no deben formar parte del modelo dosimétrico.** Este paso separa el cuerpo del paciente del fondo mediante un umbral de Hounsfield Units, seguido de operaciones morfológicas y de conectividad para obtener una máscara corporal limpia. El CT original se conserva intacto; se crea un nuevo nodo `CT_sin_camilla` con la máscara aplicada.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| HU | Hounsfield Unit |
| FOV | Field of View |
| AI | Artificial Intelligence (Supervisor) |

---

## 1. El Problema

Un CT abdominal típico incluye:
- **El paciente** (tejidos: $-200$ a $+3000$ HU)
- **La camilla** (plástico/metal: $-500$ a $+1000$ HU, según el material)
- **Aire exterior** ($-1024$ HU) alrededor del paciente
- **Aire interior** (pulmones: $-900$ a $-200$ HU, intestino: burbujas gaseosas)

El objetivo es conservar **solo el cuerpo del paciente**, incluyendo pulmones y contenido abdominal, pero excluyendo la camilla y el aire exterior. El CT original no se modifica porque TotalSegmentator (Paso 7) necesita el FOV completo para segmentar correctamente.

---

## 2. Algoritmo Detallado

### 2.1 Notación

| Símbolo | Descripción | Unidades |
|:-------:|-------------|:--------:|
| $I_{\text{CT}}(x,y,z)$ | Volumen CT original | HU |
| $M(x,y,z)$ | Máscara corporal binaria ($1$ = cuerpo, $0$ = fondo) | — |
| $I_{\text{enmasc}}(x,y,z)$ | CT enmascarado (fondo $= -1024$ HU) | HU |
| $B$ | Elemento estructurante ($3 \times 3 \times 3$) | vox |
| $\mathcal{C}_z$ | Conjunto de componentes conectadas en el slice $z$ | — |

### 2.2 Paso 1: Umbralización

Se aplica un umbral sobre los valores HU para separar tejido del aire:

$$M_1(x,y,z) = \begin{cases} 1 & \text{si } I_{\text{CT}}(x,y,z) > -200 \\ 0 & \text{en caso contrario} \end{cases}$$

| Condición | Interpretación |
|-----------|----------------|
| $I_{\text{CT}} > -200$ HU | Tejido (incluye pulmón, grasa, músculo, hueso) |
| $I_{\text{CT}} \leq -200$ HU | Aire (fondo) |

El valor $-200$ HU es el límite inferior del tejido blando. Tejidos con menor densidad quedan incluidos:
- Pulmón: $-900$ a $-200$ HU ✅
- Grasa: $-100$ a $-50$ HU ✅
- Agua/tejido blando: $0$ a $+100$ HU ✅
- Hueso: $+150$ a $+2000$ HU ✅

Solo aire puro ($<-900$ HU) queda excluido.

### 2.3 Paso 2: Cierre Morfológico

Operación morfológica para rellenar huecos internos (vasos sanguíneos, bronquios, burbujas intestinales) dentro del cuerpo:

$$M_2 = (M_1 \oplus B) \ominus B$$

| Operación | Símbolo | Descripción |
|-----------|:-------:|-------------|
| Dilatación | $\oplus$ | Expande bordes: rellena huecos pequeños |
| Erosión | $\ominus$ | Contrae bordes: restaura el tamaño original |
| Cierre | $\oplus$ seguido de $\ominus$ | Rellena huecos sin cambiar el tamaño |

Parámetros:

| Parámetro | Valor | Descripción |
|-----------|:-----:|-------------|
| Elemento estructurante $B$ | $3 \times 3 \times 3$ | Cubo de 27 voxels (conectividad 26-vecina 3D) |
| Iteraciones | 3 | Número de aplicaciones sucesivas |
| Función | `scipy.ndimage.binary_closing` | Implementación SciPy |

Si SciPy no está disponible, se omite este paso y se usa un fallback con NumPy puro.

### 2.4 Paso 3: Componente Conexa Mayoritaria

En cada slice axial $z$, se etiquetan las componentes conectadas (conectividad 8-vecina en 2D) y se conserva solo la más grande:

$$M_3(z,:,:) = \arg\max_{c \in \mathcal{C}_z} |c|$$

| Símbolo | Descripción |
|:-------:|-------------|
| $\mathcal{C}_z$ | Conjunto de todas las componentes conectadas en el slice $z$ de $M_2$ |
| $c$ | Una componente conectada individual (conjunto de voxels) |
| $|c|$ | Número de voxels en la componente $c$ |
| $\arg\max$ | Selecciona la componente con mayor $|c|$ |

Esto elimina:
- Brazos desconectados del cuerpo (si los hubiera)
- Artefactos aislados
- Camilla (desconectada del cuerpo en la mayoría de los casos)

### 2.5 Paso 4: Eliminación de Camilla

Se procesa cada slice axial:
1. **Encontrar fila inferior del cuerpo**: buscar desde abajo hacia arriba la primera fila con voxeles corporales
2. **Eliminar debajo**: todo lo que está debajo de esa fila se pone a $0$ (es la camilla)
3. **Recortar bordes**: eliminar 2-3 pixeles de los bordes laterales (artefactos de la camilla)

### 2.6 Paso 5: Aplicación de Máscara

$$I_{\text{enmasc}}(x,y,z) = \begin{cases} I_{\text{CT}}(x,y,z) & \text{si } M(x,y,z) = 1 \\ -1024 & \text{en caso contrario} \end{cases}$$

Se crea un nuevo nodo `CT_sin_camilla` con la misma geometría (dimensiones, espaciado, origen) que el CT original, pero con los voxeles fuera del cuerpo fijados a $-1024$ HU (valor de aire).

---

## 3. Parámetros

| Parámetro | Valor | Descripción |
|-----------|:-----:|-------------|
| Umbral HU | $> -200$ | Separa tejido de aire |
| Elemento estructurante $B$ | $3 \times 3 \times 3$ | Cubo para cierre morfológico |
| Iteraciones de cierre | 3 | Relleno de huecos internos |
| Conectividad 2D | 8-vecina | Vecindario por slice |
| Fondo | $-1024$ HU | Valor de aire asignado fuera del cuerpo |

---

## 4. Diagrama de Flujo

```
CT original (512 × 512 × N)
       │
       ▼
┌──────────────────┐
│ Umbral HU > -200 │
│ M₁ = CT > -200   │
└────────┬─────────┘
         │
         ▼
┌─────────────────────┐
│ Cierre morfológico  │
│ M₂ = close(M₁, B)  │
│ B = 3×3×3, 3 iters │
└────────┬────────────┘
         │
         ▼
┌──────────────────────────────┐
│ Componente conectada mayor   │
│ M₃(z) = argmax |c| en C_z   │
│ (por slice axial)            │
└────────┬─────────────────────┘
         │
         ▼
┌──────────────────────┐
│ Eliminar camilla     │
│ - fila inferior      │
│ - recorte lateral    │
│ 2-3 pixeles          │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────┐
│ Aplicar máscara              │
│ CT_enmasc = CT_original      │
│ CT_enmasc[M==0] = -1024 HU  │
│                              │
│ Nuevo nodo: CT_sin_camilla   │
└──────────────────────────────┘
```

---

## 5. Ejemplo Visual (Texto)

```
Slice axial antes:
┌──────────────────────────────────────┐
│ Aire (-1024)                         │
│         ┌──────────────────┐         │
│         │  Cuerpo del       │         │
│         │  paciente (HU     │         │
│         │  variados)        │         │
│         └──────────────────┘         │
│ ═════════════════════════════════════ │ ← Camilla (HU ~ -500 a 0)
└──────────────────────────────────────┘

Slice axial después (CT_sin_camilla):
┌──────────────────────────────────────┐
│ Aire (-1024)                         │
│         ┌──────────────────┐         │
│         │  Cuerpo del       │         │
│         │  paciente (HU     │         │
│         │  variados)        │         │
│         └──────────────────┘         │
│ Aire (-1024) ← camilla eliminada     │
└──────────────────────────────────────┘
```

---

## 6. Verificaciones de Calidad (AI Supervisor)

| Verificación | Criterio | Acción si falla |
|-------------|:--------:|:---------------:|
| Fracción de volumen eliminado $f_{\text{rem}}$ | $f_{\text{rem}} < 0.5$ ($< 50\%$) | Warning (se eliminó más de la mitad del volumen) |
| Mascara no vacía | $M$ tiene al menos un voxel $= 1$ | Error → detener pipeline |
| CT_sin_camilla creado | Nodo existe en escena | Error → detener pipeline |

$$f_{\text{rem}} = \frac{V_{\text{original}} - V_{\text{mascara}}}{V_{\text{original}}}$$

| Símbolo | Descripción |
|:-------:|-------------|
| $f_{\text{rem}}$ | Fracción de voxeles eliminados (camilla + aire) |
| $V_{\text{original}}$ | Voxeles totales del CT original |
| $V_{\text{mascara}}$ | Voxeles dentro de la máscara corporal |

Una $f_{\text{rem}} > 0.5$ sugiere que el umbral o la morfología fueron demasiado agresivos.

---

## 7. Notas Técnicas

- El CT original **no se modifica**: se conserva intacto para TotalSegmentator, que necesita el FOV completo.
- `CT_sin_camilla` se usa para la superposición PET en las vistas médicas (Paso 5).
- La máscara conserva solo la **componente 2D más grande por slice**, lo que elimina eficazmente brazos desconectados, camilla y artefactos.
- Los voxeles corporales típicamente ocupan entre el 30% y el 60% del FOV total en un CT abdominal.
- Si `scipy.ndimage` no está disponible, el cierre morfológico se omite (la máscara puede tener pequeños huecos internos).
