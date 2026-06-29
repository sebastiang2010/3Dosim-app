"""
deepseek_client - Conexion a OpenRouter/DeepSeek desde la consola 3Dosim.

Permite:
  - Consultar modelos LLM (DeepSeek, Claude, GPT, Gemini, etc.)
  - Cambiar de modelo en caliente
  - Listar modelos sugeridos

Usa la API de OpenRouter (compatible con OpenAI SDK).
Configuracion en deepseek.env (raiz del proyecto).
"""

import logging
import os
import sys

logger = logging.getLogger("3DosimTest")

# Modelos sugeridos (parcial, solo los mas usados)
MODELOS_SUGERIDOS = {
    "deepseek/deepseek-chat": "DeepSeek-V3 (default, economico)",
    "deepseek/deepseek-r1": "DeepSeek-R1 (razonamiento profundo)",
    "anthropic/claude-3.5-haiku": "Claude 3.5 Haiku (rapido)",
    "anthropic/claude-3.5-sonnet": "Claude 3.5 Sonnet (potente)",
    "openai/gpt-4o": "GPT-4o (multimodal)",
    "openai/gpt-4o-mini": "GPT-4o Mini (rapido/barato)",
    "google/gemini-2.0-flash": "Gemini 2.0 Flash (rapido/gratuito)",
    "qwen/qwen-2.5-72b-instruct": "Qwen 2.5 72B (open source)",
    "mistral/mistral-large": "Mistral Large (europeo)",
    "meta-llama/llama-3.3-70b-instruct": "Llama 3.3 70B (Meta)",
}


class DeepSeekClient:
    """Cliente para OpenRouter con soporte multi-modelo.

    Uso:
        client = DeepSeekClient()
        client.cargar_api_key()
        resp = client.consultar("que es BED?")
        client.set_modelo("anthropic/claude-3.5-sonnet")
    """

    def __init__(self):
        self._client = None
        self._modelo = "deepseek/deepseek-chat"
        self._api_key = None
        self._ready = False
        self._ultimo_error = None

    # ------------------------------------------------------------------
    # API PUBLICA
    # ------------------------------------------------------------------

    def cargar_api_key(self, ruta_env: "str | None" = None) -> bool:
        """Carga la API key desde deepseek.env.

        Args:
            ruta_env: Ruta al archivo .env. Si es None, busca en:
                      1. deepseek.env en la raiz del proyecto
                      2. Variable de entorno OPENROUTER_API_KEY

        Returns:
            bool: True si se cargo la key exitosamente.
        """
        # Buscar archivo .env
        if ruta_env is None:
            ruta_env = self._buscar_env()

        if ruta_env and os.path.exists(ruta_env):
            try:
                self._cargar_desde_archivo(ruta_env)
            except Exception as e:
                logger.warning(f"No se pudo leer {ruta_env}: {e}")

        # Fallback a variable de entorno
        if not self._api_key:
            self._api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

        if not self._api_key:
            self._ultimo_error = (
                "No se encontro OPENROUTER_API_KEY. "
                "Crea deepseek.env en la raiz del proyecto con:\n"
                "  OPENROUTER_API_KEY=sk-or-v1-tu-key\n"
                "O configura la variable de entorno OPENROUTER_API_KEY."
            )
            logger.warning(self._ultimo_error)
            return False

        # Crear cliente OpenAI
        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._api_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://github.com/3Dosim/3Dosim",
                    "X-Title": "3Dosim Pipeline",
                },
                timeout=30.0,  # timeout de 30s para no colgarse
            )
            self._ready = True
            logger.info(
                f"DeepSeekClient listo. Modelo default: {self._modelo}"
            )
            return True

        except ImportError:
            self._ultimo_error = (
                "El paquete 'openai' no esta instalado. "
                "Ejecuta: pip install openai"
            )
            logger.error(self._ultimo_error)
            return False
        except Exception as e:
            self._ultimo_error = f"Error creando cliente OpenAI: {e}"
            logger.error(self._ultimo_error)
            return False

    def consultar(self, prompt: str, sistema: "str | None" = None,
                  temperatura: float = 0.3, max_tokens: int = 2048) -> str:
        """Envia una consulta al LLM y devuelve la respuesta.

        Args:
            prompt: Texto de la consulta del usuario.
            sistema: System prompt personalizado. Si es None, usa el default.
            temperatura: Creatividad de la respuesta (0.0 - 1.0).
            max_tokens: Maximo de tokens en la respuesta.

        Returns:
            str: Respuesta del modelo.

        Raises:
            RuntimeError: Si el cliente no esta inicializado.
        """
        if not self._ready or not self._client:
            raise RuntimeError(
                "DeepSeekClient no inicializado. Llamar cargar_api_key() primero."
            )

        system_msg = sistema or (
            "Sos un asistente experto en dosimetria de medicina nuclear, "
            "procesamiento de imagenes medicas (CT, SPECT, PET), "
            "simulaciones Monte Carlo (MCNP), y 3D Slicer. "
            "Respondé en castellano de forma clara y concisa. "
            "Si hablas de dosis, usa unidades Gy o Sv segun corresponda. "
            "NO uses emojis ni caracteres Unicode especiales."
        )

        try:
            respuesta = self._client.chat.completions.create(
                model=self._modelo,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperatura,
                max_tokens=max_tokens,
            )

            return respuesta.choices[0].message.content.strip()

        except Exception as e:
            error_msg = f"Error en consulta: {e}"
            logger.error(error_msg)
            self._ultimo_error = error_msg
            raise RuntimeError(error_msg)

    def consultar_con_stream(self, prompt: str,
                             on_chunk: "callable | None" = None,
                             sistema: "str | None" = None,
                             temperatura: float = 0.3,
                             max_tokens: int = 2048) -> str:
        """Version con streaming: va mostrando la respuesta a medida que llega.

        Args:
            prompt: Consulta del usuario.
            on_chunk: Callable que recibe cada fragmento de texto.
            sistema: System prompt personalizado.
            temperatura: Creatividad.
            max_tokens: Max tokens.

        Returns:
            str: Respuesta completa.
        """
        if not self._ready or not self._client:
            raise RuntimeError(
                "DeepSeekClient no inicializado. Llamar cargar_api_key() primero."
            )

        system_msg = sistema or (
            "Sos un asistente experto en dosimetria de medicina nuclear, "
            "procesamiento de imagenes medicas (CT, SPECT, PET), "
            "simulaciones Monte Carlo (MCNP), y 3D Slicer. "
            "Respondé en castellano de forma clara y concisa. "
            "NO uses emojis ni caracteres Unicode especiales."
        )

        try:
            respuesta_completa = []
            stream = self._client.chat.completions.create(
                model=self._modelo,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperatura,
                max_tokens=max_tokens,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    texto = delta.content
                    respuesta_completa.append(texto)
                    if on_chunk:
                        on_chunk(texto)

            return "".join(respuesta_completa).strip()

        except Exception as e:
            error_msg = f"Error en consulta streaming: {e}"
            logger.error(error_msg)
            self._ultimo_error = error_msg
            raise RuntimeError(error_msg)

    def set_modelo(self, modelo: str) -> str:
        """Cambia el modelo activo.

        Args:
            modelo: Nombre del modelo en OpenRouter
                    (ej: 'anthropic/claude-3.5-haiku').

        Returns:
            str: Nombre del modelo ahora activo.
        """
        modelo = modelo.strip()
        if not modelo:
            return self._modelo
        self._modelo = modelo
        logger.info(f"Modelo cambiado a: {modelo}")
        return self._modelo

    def listar_modelos(self) -> str:
        """Devuelve una cadena formateada con los modelos sugeridos."""
        lineas = ["MODELOS SUGERIDOS (OpenRouter):", ""]
        for modelo, desc in MODELOS_SUGERIDOS.items():
            marca = "  << ACTIVO" if modelo == self._modelo else ""
            lineas.append(f"  {modelo:<45s} {desc}{marca}")
        lineas.append("")
        lineas.append(
            "Todos los modelos disponibles: https://openrouter.ai/models"
        )
        return "\n".join(lineas)

    @property
    def modelo_actual(self) -> str:
        return self._modelo

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def ultimo_error(self) -> "str | None":
        return self._ultimo_error

    # ------------------------------------------------------------------
    # INTERNO
    # ------------------------------------------------------------------

    def _buscar_env(self) -> "str | None":
        """Busca .env o deepseek.env en ubicaciones posibles."""
        env_names = [".env", "deepseek.env"]
        basedir = os.path.dirname(__file__)  # PipelineOrchestrator/
        candidatos = []
        for name in env_names:
            candidatos.extend([
                # 1. Directorio actual (raiz del proyecto)
                os.path.join(os.getcwd(), name),
                # 2. Raiz del proyecto v4 (dos niveles arriba de PipelineOrchestrator/)
                os.path.join(basedir, "..", "..", name),
                # 3. Directorio padre del modulo (Testing/)
                os.path.join(basedir, "..", name),
                # 4. Junto al modulo
                os.path.join(basedir, name),
                # 5. Directorio raiz de 3Dosim v4 (hardcoded)
                os.path.join("C:\\programas\\3Dosim\\3Dosim_v4", name),
            ])

        # Normalizar rutas
        for ruta in candidatos:
            ruta = os.path.abspath(ruta)
            if os.path.exists(ruta):
                logger.debug(f".env encontrado en: {ruta}")
                return ruta

        logger.debug("No se encontro .env / deepseek.env")
        return None

    def _cargar_desde_archivo(self, ruta: str):
        """Lee el archivo .env manualmente (sin dependencias externas)."""
        with open(ruta, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    if key == "OPENROUTER_API_KEY":
                        self._api_key = value
                    elif key == "OPENROUTER_MODEL":
                        self._modelo = value


# ------------------------------------------------------------------
# Singleton de modulo (instancia unica para toda la pipeline)
# ------------------------------------------------------------------
_INSTANCIA = None


def get_client() -> DeepSeekClient:
    """Devuelve la instancia singleton del cliente."""
    global _INSTANCIA
    if _INSTANCIA is None:
        _INSTANCIA = DeepSeekClient()
    return _INSTANCIA
