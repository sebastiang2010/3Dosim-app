"""
ai_supervisor - Revision inteligente del pipeline 3Dosim paso a paso.

Despues de cada paso del pipeline, recolecta el estado actual y se lo
envia a DeepSeek/OpenRouter para obtener sugerencias, correcciones y
mejoras en tiempo real.

Incluye reglas de pre-verificacion que detectan anomalias obvias
antes de consultar a la IA (e.g. segmentacion con 1 solo organo,
voxels en aire, etc.).
"""

import logging
import os
import threading
import time

from PipelineOrchestrator.deepseek_client import get_client

logger = logging.getLogger("3DosimTest")


# ======================================================================
# System prompt para el supervisor
# ======================================================================

SYSTEM_PROMPT = """
Sos un revisor experto en dosimetria de medicina nuclear, procesamiento
de imagenes medicas (CT, SPECT, PET), simulaciones Monte Carlo (MCNP),
y 3D Slicer.

Tu funcion es revisar CADA PASO del pipeline 3Dosim y dar feedback
util y conciso. Para cada paso decis:

1. Si el resultado del paso es razonable (OK / dudas / warning)
2. Una sugerencia concreta de mejora si aplica
3. Que verificar en el siguiente paso

Reglas:
- Respondé en castellano, maximo 4 lineas.
- No saludes ni te presentes.
- Si todo esta bien, decilo simple: "OK, seguir adelante."
- Si algo es sospechoso, avisa claro.
- NO uses emojis ni markdown.
- Si ves que la segmentacion tiene pocos organos o voxels en el aire,
  decilo claramente como un problema.
"""


# ======================================================================
# Pre-verificacion: reglas duras antes de consultar a la IA
# ======================================================================

def pre_verificar(pipeline_ctx: dict, consola=None) -> list:
    """Ejecuta reglas de calidad antes de la consulta a la IA.

    Revisa el contexto del paso y emite warnings inmediatos si
    detecta anomalias obvias (sin esperar a la IA).

    Returns:
        list: lista de mensajes de warning (strings).
    """
    warnings = []
    paso = pipeline_ctx.get("paso", "").lower()
    datos = pipeline_ctx.get("datos", {})
    ok = pipeline_ctx.get("ok", True)

    if not ok:
        return warnings  # si el paso fallo, no tiene sentido pre-verificar

    # ---- Reglas para segmentacion ----
    if "segment" in paso:
        seg_metrics = datos.get("segmentation_metrics", {})
        seg_type = datos.get("segmenter_type", "desconocido")

        # Advertencia segun metodo de segmentacion
        if seg_type == "simple":
            msg = (
                "[calidad] Metodo de segmentacion: simple (threshold). "
                "Esto produce un solo volumen binario sin distincion de "
                "organos. Para dosimetria se recomienda TotalSegmentator "
                "que genera ~104 organos etiquetados."
            )
            warnings.append(msg)
            if consola:
                consola.log(msg)

        # Verificar cantidad de segmentos
        num_seg = seg_metrics.get("num_segments", 0)
        if num_seg <= 2:
            msg = (
                f"[calidad] Solo {num_seg} segmento(s) detectado(s). "
                "Un phantom dosimetrico completo requiere organos "
                "segmentados individualmente (higado, rinones, medula, "
                "etc). Con threshold simple no es posible."
            )
            warnings.append(msg)
            if consola:
                consola.log(msg)

        # Verificar voxels fuera del cuerpo
        fuera = seg_metrics.get("voxels_fuera_cuerpo", 0)
        if fuera > 1000:
            msg = (
                f"[calidad] {fuera} voxels segmentados fuera del "
                "contorno corporal (en aire/camilla). La segmentacion "
                "incluye ruido que debe ser corregido antes de continuar."
            )
            warnings.append(msg)
            if consola:
                consola.log(msg)

    return warnings


# ======================================================================
# Funcion principal: revisar un paso del pipeline
# ======================================================================

def revisar_paso(pipeline_ctx: dict, consola=None):
    """Revisa el paso que acaba de completarse y muestra feedback.

    Args:
        pipeline_ctx: Dict con el estado actual del pipeline:
            {
                "paso": nombre del paso completado,
                "ok": True/False,
                "tiempo": segundos,
                "datos": { ... datos relevantes del paso ... },
                "errores": [ ... ],
            }
        consola: Instancia de ConsolaComandos para mostrar feedback.
    """
    paso = pipeline_ctx.get("paso", "desconocido")
    ok = pipeline_ctx.get("ok", True)
    datos = pipeline_ctx.get("datos", {})

    if not ok:
        return  # no revisar pasos fallidos

    if consola:
        try:
            consola.log(f"  [AI supervisor revisando paso '{paso}']...")
        except Exception:
            pass

    # ---- Pre-verificacion: reglas de calidad inmediatas ----
    pre_warnings = pre_verificar(pipeline_ctx, consola=consola)

    # Construir prompt con el contexto del paso
    prompt = _construir_prompt(pipeline_ctx, pre_warnings)

    # Inicializar cliente si no lo esta
    client = get_client()
    if not client.ready:
        client.cargar_api_key()
        if not client.ready:
            msg = f"  [AI reviewer no disponible: {client.ultimo_error}]"
            if consola:
                consola.log(msg)
            logger.info(msg)
            return

    # Log que la IA esta revisando (no bloqueante)
    msg_revisando = f"[IA revisando paso '{paso}']..."
    if consola:
        consola.log(msg_revisando)
    else:
        logger.info(msg_revisando)

    # Llamar a la IA en thread separado y mostrar resultado
    def revisar_thread():
        try:
            respuesta = client.consultar(
                prompt,
                sistema=SYSTEM_PROMPT,
                temperatura=0.2,
                max_tokens=512,
            )
            if consola and consola._visible:
                consola.log_ai(respuesta)
            else:
                logger.info(f"  [AI review] {respuesta}")
        except RuntimeError as e:
            msg_error = f"  [AI reviewer: {e}]"
            if consola:
                consola.log(msg_error)
            logger.warning(msg_error)

    t = threading.Thread(target=revisar_thread, daemon=True)
    t.start()


# ======================================================================
# Construccion de prompt
# ======================================================================

def _construir_prompt(ctx: dict, pre_warnings: list = None) -> str:
    """Construye el prompt para la IA segun el paso y sus datos."""
    paso = ctx.get("paso", "")
    datos = ctx.get("datos", {})

    prompt = f"Paso completado: {paso}\n"
    prompt += "Datos del paso:\n"

    for key, value in datos.items():
        # Formatear sub-dicts de forma legible
        if isinstance(value, dict):
            prompt += f"  {key}:\n"
            for sk, sv in value.items():
                prompt += f"    {sk}: {sv}\n"
        elif isinstance(value, list):
            prompt += f"  {key}: {', '.join(str(v) for v in value)}\n"
        else:
            prompt += f"  {key}: {value}\n"

    # Incluir pre-warnings si los hay
    if pre_warnings:
        prompt += "\nAdvertencias de calidad detectadas:\n"
        for w in pre_warnings:
            prompt += f"  - {w}\n"

    prompt += "\nRevisa este paso y decí si esta correcto, si hay algo que mejorar, y que verificar en el proximo paso."

    return prompt
