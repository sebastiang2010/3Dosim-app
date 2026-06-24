"""
mcp_helper - Conexion MCP con 3D Slicer para tu pipeline.

QUE HACE:
  - Ejecuta codigo Python en Slicer (desde afuera)
  - Toma screenshots de las vistas de Slicer
  - Lista los nodos cargados en Slicer

COMO USAR (2 pasos):

  PASO 1: En Slicer, abre Python Console y pega:
      import urllib.request
      url = "https://raw.githubusercontent.com/pieper/slicer-skill/main/slicer-mcp-server.py"
      exec(urllib.request.urlopen(url).read().decode("utf-8"))

  PASO 2: Desde tu script Python (afuera de Slicer):
      from mcp_helper import MCP
      mcp = MCP()
      mcp.connect()
      resultado = mcp.ejecutar("slicer.app.majorVersion")
      print(resultado)

SIN SLA:
  Si no tenes internet, descarga slicer-mcp-server.py manualmente de:
  https://github.com/pieper/slicer-skill/blob/main/slicer-mcp-server.py
  Y en Slicer: exec(open(r'C:/ruta/slicer-mcp-server.py').read())
"""

import json
import logging
import urllib.request
import urllib.error
import base64

logger = logging.getLogger("MCP")


class MCP:
    """Cliente MCP minimo para 3D Slicer.

    Conecta al server MCP que corre DENTRO de Slicer.
    """

    def __init__(self, url="http://localhost:2026"):
        self.url = url.rstrip("/") + "/mcp"
        self.conectado = False
        self._id = 0

    # ------------------------------------------------------------------
    # CONEXION
    # ------------------------------------------------------------------

    def connect(self):
        """Conecta al MCP server de Slicer.

        Returns: True si conecto, False si no.
        """
        try:
            logger.info(f'Conectando a MCP Slicer: {self.url}')
            # Handshake MCP: initialize
            resp = self._call("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "3Dosim", "version": "3.14"}
            })
            # Descubrir tools disponibles
            tools = self._call("tools/list", {})
            tools_list = [t.get("name") for t in tools.get("tools", [])]
            logger.info(f"  Tools: {', '.join(tools_list)}")
            self.conectado = True
            return True
        except Exception as e:
            logger.warning(f"  No conecta: {e}")
            self.conectado = False
            return False

    def disconnect(self):
        self.conectado = False

    # ------------------------------------------------------------------
    # COMANDOS QUE LE SIRVEN A TU PIPELINE
    # ------------------------------------------------------------------

    def ejecutar(self, codigo_python):
        """Ejecuta Python en Slicer y devuelve el resultado.

        Args:
            codigo_python: String con codigo Python valido.

        Returns:
            Dict con {"output": "...", "result": ...} o None si error.
        """
        if not self.conectado:
            logger.error("MCP no conectado. Llama connect() primero.")
            return None
        try:
            resp = self._call("tools/call", {
                "name": "execute_python",
                "arguments": {"code": codigo_python}
            })
            return self._extraer_texto(resp)
        except Exception as e:
            logger.error(f"Error ejecutando codigo: {e}")
            return None

    def screenshot(self, vista="3D"):
        """Toma screenshot de Slicer.

        Args:
            vista: "3D", "Red", "Yellow", "Green"

        Returns:
            Bytes de la imagen PNG, o None si error.
        """
        if not self.conectado:
            logger.error("MCP no conectado.")
            return None
        try:
            resp = self._call("tools/call", {
                "name": "screenshot",
                "arguments": {"view": vista}
            })
            contenido = resp.get("content", [])
            for parte in contenido:
                if isinstance(parte, dict) and parte.get("type") == "text":
                    return base64.b64decode(parte["text"])
                if isinstance(parte, dict) and "data" in parte:
                    return base64.b64decode(parte["data"])
            return None
        except Exception as e:
            logger.error(f"Error screenshot: {e}")
            return None

    def listar_nodos(self, filtro=""):
        """Lista los nodos cargados en Slicer.

        Returns:
            Lista de dicts con info de nodos, o [] si error.
        """
        if not self.conectado:
            return []
        try:
            args = {"filter": filtro} if filtro else {}
            resp = self._call("tools/call", {
                "name": "list_nodes", "arguments": args
            })
            texto = self._extraer_texto(resp)
            if isinstance(texto, list):
                return texto
            if isinstance(texto, str):
                return json.loads(texto)
            return []
        except Exception as e:
            logger.error(f"Error listando nodos: {e}")
            return []

    # ------------------------------------------------------------------
    # INTERNO
    # ------------------------------------------------------------------

    def _call(self, method, params):
        """Llama JSON-RPC al server MCP."""
        self._id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params,
        }).encode()

        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if "error" in data and data["error"]:
            raise Exception(f"MCP error: {data['error']}")
        return data.get("result", data)

    def _extraer_texto(self, resp):
        """Extrae texto de la respuesta MCP."""
        content = resp.get("content", [])
        if isinstance(content, list):
            textos = [p.get("text", "") for p in content
                      if isinstance(p, dict) and p.get("type") == "text"]
            if len(textos) == 1:
                try:
                    return json.loads(textos[0])
                except json.JSONDecodeError:
                    return textos[0]
            if textos:
                return textos
        if isinstance(content, str):
            return content
        return content

    def __repr__(self):
        return f"<MCP {'conectado' if self.conectado else 'desconectado'}>"


# ------------------------------------------------------------------
# TEST RAPIDO (correr FUERA de Slicer)
# ------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    mcp = MCP()
    if not mcp.connect():
        print()
        print("=" * 60)
        print(" NO CONECTA. Hace falta el PASO 1:")
        print("=" * 60)
        print()
        print(" Abre 3D Slicer, ve a Python Console y pega:")
        print()
        print('  import urllib.request')
        print('  url = "https://raw.githubusercontent.com/pieper/')
        print('  slicer-skill/main/slicer-mcp-server.py"')
        print("  exec(urllib.request.urlopen(url).read().decode())")
        print()
        print(" O descarga el archivo y corre:")
        print("  exec(open(r'C:/ruta/slicer-mcp-server.py').read())")
        print()
        exit(1)

    # Probar conexion
    print()
    print("=" * 60)
    print(" CONECTADO A SLICER VIA MCP")
    print("=" * 60)
    print()

    # 1. Version de Slicer
    v = mcp.ejecutar("slicer.app.majorVersion")
    print(f"  Slicer version: {v}")

    # 2. Nodos en escena
    nodos = mcp.listar_nodos()
    print(f"  Nodos en escena: {len(nodos)}")
    for n in nodos[:5]:
        if isinstance(n, dict):
            print(f"    - {n.get('name', n.get('id', '?'))}")

    # 3. Screenshot
    img = mcp.screenshot("3D")
    if img:
        with open("_test_screenshot.png", "wb") as f:
            f.write(img)
        print(f"  Screenshot: _test_screenshot.png ({len(img)} bytes)")

    # 4. Tu pipeline: cargar volumen
    print()
    print("  Probando pipeline...")
    r = mcp.ejecutar("""
# Esto corre dentro de Slicer
vol = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
if vol:
    dims = vol.GetImageData().GetDimensions()
    f"Volumen: {vol.GetName()} ({dims[0]}x{dims[1]}x{dims[2]})"
else:
    "No hay volumenes cargados"
""")
    print(f"  {r}")

    print()
    print(" LISTO. Ahora integra 'from mcp_helper import MCP'")
    print(" en tu pipeline y usa mcp.ejecutar('codigo').")
    print()
