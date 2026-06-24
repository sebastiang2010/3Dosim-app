"""
comandos - Consola interactiva de comandos para 3D Slicer.

Permite escribir comandos en lenguaje natural (castellano) y los traduce
a acciones dentro de Slicer. Sin IA — usa pattern matching predefinido.

Comandos soportados:
  screenshot [vista]     → Captura pantalla (3D, Red, Yellow, Green)
  vista [nombre]         → Cambia layout (3D, axial, sagital, coronal)
  fusion [0.0-1.0]       → Opacidad del foreground (fusion)
  listar nodos / nodos   → Muestra los nodos cargados
  cargar [ruta]          → Carga un volumen NIfTI/NRRD/DICOM
  colormap [nodo] [mapa] → Cambia colormap (Rainbow, Hot, etc)
  ventana [w] [l] / wl   → Ajusta window/level del CT
  ayuda / ? / help       → Lista de comandos
  cls / limpiar          → Limpia la consola
  salir / exit           → Cierra la consola

Uso desde pipeline.py:
  from PipelineOrchestrator.comandos import ConsolaComandos
  consola = ConsolaComandos()
  consola.mostrar()
  consola.log("Pipeline iniciado")
"""

import logging
import os
import re

logger = logging.getLogger("3DosimTest")


class ConsolaComandos:
    """Consola Qt interactiva para controlar Slicer con comandos de texto.

    Crea un QDialog flotante con historial de comandos y salida.
    """

    def __init__(self, output_dir: "str | None" = None):
        self._dialog = None
        self._output = None
        self._input = None
        self._visible = False
        self.output_dir = output_dir
        self._historial = []
        self._hist_idx = -1

        # Diccionario de comandos: (patron_regex, descripcion, funcion)
        self._comandos = [
            (r"^(screenshot|captura|foto)(\s+\w+)?$",
             "screenshot [vista]",
             self._cmd_screenshot),
            (r"^(vista|layout)\s+(.+)$",
             "vista <3D|axial|sagital|coronal|conventional>",
             self._cmd_vista),
            (r"^(fusion|opacidad|opacity)\s+([0-9](\.[0-9]+)?|1\.0)$",
             "fusion <0.0-1.0>",
             self._cmd_fusion),
            (r"^(listar\s+)?nodos$",
             "listar nodos",
             self._cmd_nodos),
            (r"^(cargar|load)\s+(.+)$",
             "cargar <ruta>",
             self._cmd_cargar),
            (r"^colormap\s+(.+?)\s+(\w+)$",
             "colormap <nodo> <mapa>",
             self._cmd_colormap),
            (r"^(ventana|wl)\s+([-\d.]+)\s+([-\d.]+)$",
             "ventana <width> <level>",
             self._cmd_ventana),
            (r"^(ayuda|\?|help|comandos)$",
             "ayuda",
             self._cmd_ayuda),
            (r"^(cls|limpiar|clear)$",
             "cls",
             self._cmd_limpiar),
            (r"^(salir|exit|cerrar)$",
             "salir",
             self._cmd_salir),
        ]

    # ------------------------------------------------------------------
    # API PUBLICA
    # ------------------------------------------------------------------

    def mostrar(self):
        """Muestra (o crea) la consola como ventana flotante."""
        try:
            import qt
            QDialog = qt.QDialog
            QVBoxLayout = qt.QVBoxLayout
            QTextEdit = qt.QTextEdit
            QPushButton = qt.QPushButton
            QHBoxLayout = qt.QHBoxLayout
            QApplication = qt.QApplication
            QLineEdit = qt.QLineEdit

            if self._dialog and self._visible:
                self._dialog.raise_()
                return

            self._dialog = QDialog()
            self._dialog.setWindowTitle("3Dosim - Consola de Comandos")
            self._dialog.setMinimumSize(600, 400)
            self._dialog.resize(650, 450)

            layout = QVBoxLayout()

            # Output: QTextEdit read-only
            self._output = QTextEdit()
            self._output.setReadOnly(True)
            self._output.setStyleSheet(
                "background-color: #1e1e1e; color: #d4d4d4; "
                "font-family: Consolas, Courier New; font-size: 12px;"
            )
            layout.addWidget(self._output)

            # Input row
            input_layout = QHBoxLayout()

            self._input = QLineEdit()
            self._input.setPlaceholderText("Escribi un comando (ej: screenshot, ayuda)...")
            self._input.setStyleSheet(
                "font-family: Consolas, Courier New; font-size: 12px; "
                "padding: 6px;"
            )
            self._input.returnPressed.connect(self._procesar_input)
            input_layout.addWidget(self._input)

            btn_enviar = QPushButton("Enviar")
            btn_enviar.setStyleSheet(
                "font-weight: bold; padding: 6px 16px;"
            )
            btn_enviar.clicked.connect(self._procesar_input)
            input_layout.addWidget(btn_enviar)

            layout.addLayout(input_layout)

            # Hint
            self._output.append(
                '<span style="color: #888;">'
                "Escribi un comando. 'ayuda' para lista completa."
                "</span>"
            )
            self._output.append(
                '<span style="color: #888;">'
                "Ej: screenshot, nodos, fusion 0.5, vista 3D"
                "</span>"
            )
            self._output.append("")

            self._dialog.setLayout(layout)
            self._visible = True
            self._dialog.show()
            self._input.setFocus()

        except ImportError:
            logger.info("  (Qt no disponible en este entorno)")
        except Exception as e:
            logger.warning(f"  No se pudo crear consola: {e}")

    def ocultar(self):
        """Cierra la consola."""
        if self._dialog and self._visible:
            self._dialog.close()
        self._visible = False

    def log(self, mensaje: str):
        """Agrega una linea al output de la consola.

        Args:
            mensaje: Texto a mostrar (soporta HTML basico)
        """
        if not self._output or not self._visible:
            logger.info(f"[consola] {mensaje}")
            return
        try:
            # Escapar HTML para evitar inyeccion, preservar saltos de linea
            safe = mensaje.replace("&", "&amp;").replace("<", "&lt;") \
                          .replace(">", "&gt;").replace("\n", "<br>")
            self._output.append(f'<span style="color: #ccc;">{safe}</span>')
            # Hacer scroll al final
            scrollbar = self._output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    def log_ok(self, mensaje: str):
        """Agrega un mensaje de exito (verde)."""
        if not self._output or not self._visible:
            return
        try:
            safe = mensaje.replace("&", "&amp;").replace("<", "&lt;") \
                          .replace(">", "&gt;").replace("\n", "<br>")
            self._output.append(f'<span style="color: #4ec94e;">✓ {safe}</span>')
            self._scroll_abajo()
        except Exception:
            pass

    def log_error(self, mensaje: str):
        """Agrega un mensaje de error (rojo)."""
        if not self._output or not self._visible:
            return
        try:
            safe = mensaje.replace("&", "&amp;").replace("<", "&lt;") \
                          .replace(">", "&gt;").replace("\n", "<br>")
            self._output.append(f'<span style="color: #e74c3c;">✗ {safe}</span>')
            self._scroll_abajo()
        except Exception:
            pass

    def log_ai(self, mensaje: str):
        """Agrega un mensaje de respuesta de IA (cyan)."""
        if not self._output or not self._visible:
            logger.info(f"[IA] {mensaje}")
            return
        try:
            safe = mensaje.replace("&", "&amp;").replace("<", "&lt;") \
                          .replace(">", "&gt;").replace("\n", "<br>")
            self._output.append(
                f'<span style="color: #00bcd4; font-style: italic;">'
                f"[IA] {safe}</span>"
            )
            self._scroll_abajo()
        except Exception:
            pass

    def log_comando(self, comando: str):
        """Muestra el comando que se ejecuto (en azul)."""
        if not self._output or not self._visible:
            return
        try:
            safe = comando.replace("&", "&amp;").replace("<", "&lt;") \
                          .replace(">", "&gt;")
            self._output.append(
                f'<span style="color: #569cd6; font-weight: bold;">'
                f"&gt; {safe}</span>"
            )
            self._scroll_abajo()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # INTERNO: manejo de input
    # ------------------------------------------------------------------

    def _procesar_input(self):
        """Lee el input, lo procesa y lo muestra."""
        texto = self._input.text.strip()
        if not texto:
            return

        self._input.clear()

        # Mostrar comando en consola
        self.log_comando(texto)

        # Guardar en historial
        self._historial.append(texto)
        self._hist_idx = len(self._historial)

        # Ejecutar
        self._ejecutar(texto)

    def _ejecutar(self, texto: str):
        """Busca el comando que matchea y lo ejecuta."""
        texto_lower = texto.lower().strip()

        for patron, desc, func in self._comandos:
            m = re.match(patron, texto_lower)
            if m:
                try:
                    func(m)
                except Exception as e:
                    self.log_error(f"Error al ejecutar: {e}")
                    logger.error(f"Comando fallo '{texto}': {e}")
                return

        self.log_error(
            f'No entiendo "{texto}". Escribi "ayuda" para comandos disponibles.'
        )

    def _scroll_abajo(self):
        try:
            scrollbar = self._output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # COMANDOS
    # ------------------------------------------------------------------

    def _cmd_screenshot(self, match):
        """screenshot [vista]"""
        vista = match.group(2)
        if vista:
            vista = vista.strip().capitalize()
            # Normalizar nombres
            if vista.lower() in ("3d", "3"):
                vista = "3D"
            elif vista.lower() in ("red", "rojo", "axial"):
                vista = "Red"
            elif vista.lower() in ("yellow", "amarillo", "sagital"):
                vista = "Yellow"
            elif vista.lower() in ("green", "verde", "coronal"):
                vista = "Green"
        else:
            vista = "3D"

        try:
            import slicer
            from datetime import datetime

            out_dir = self.output_dir or os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "..",
                "resultados_test", "screenshots"
            )
            os.makedirs(out_dir, exist_ok=True)

            ts = datetime.now().strftime("%H%M%S")
            filename = f"consola_{ts}_{vista}.png"
            filepath = os.path.join(out_dir, filename)

            lm = slicer.app.layoutManager()
            if not lm:
                self.log_error("No hay layout manager")
                return

            if vista == "3D":
                w = lm.threeDWidget(0).threeDView()
            else:
                w = lm.sliceWidget(vista).sliceView()

            if not w:
                self.log_error(f"Vista {vista} no disponible")
                return

            # grab() devuelve QPixmap, disponible en cualquier Slicer 5.x
            pixmap = w.grab()
            pixmap.save(filepath)
            self.log_ok(f"Screenshot guardado: {os.path.basename(filepath)}")

        except Exception as e:
            self.log_error(f"No se pudo tomar screenshot: {e}")

    def _cmd_vista(self, match):
        """vista <nombre>"""
        destino = match.group(2).strip().lower()

        import slicer
        lm = slicer.app.layoutManager()

        layout_map = {
            "3d": slicer.vtkMRMLLayoutNode.SlicerLayoutThreeDView,
            "axial": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView,
            "sagital": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpYellowSliceView,
            "coronal": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpGreenSliceView,
            "conventional": slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,
            "original": slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,
            "todas": slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,
        }

        if destino in layout_map:
            lm.setLayout(layout_map[destino])
            self.log_ok(f"Vista cambiada a: {destino}")
        else:
            self.log_error(
                f'Vista "{destino}" no reconocida. Opciones: '
                + ", ".join(layout_map.keys())
            )

    def _cmd_fusion(self, match):
        """fusion <opacidad>"""
        opacidad = float(match.group(2))

        if opacidad < 0 or opacidad > 1:
            self.log_error("Opacidad debe estar entre 0.0 y 1.0")
            return

        try:
            import slicer
            compositores = slicer.app.layoutManager().sliceWidgets()
            for i in range(compositores.count()):
                sw = compositores[i]
                slice_logic = sw.sliceLogic()
                fg = slice_logic.GetForegroundLayer()
                if fg:
                    fg.SetOpacity(opacidad)

            slicer.util.setSliceViewerLayers(foregroundOpacity=opacidad)
            self.log_ok(f"Opacidad de fusion: {opacidad:.2f}")
        except Exception as e:
            self.log_error(f"Error cambiando opacidad: {e}")

    def _cmd_nodos(self, match):
        """listar nodos"""
        try:
            import slicer

            # Recorrer todos los nodos de la escena
            it = slicer.mrmlScene.NewIterator()
            it.InitTraversal()

            count = 0
            lines = []
            while True:
                node = it.GetCurrentItem()
                if not node:
                    break
                clase = node.GetClassName()
                nombre = node.GetName()
                lines.append(f"  [{clase}] {nombre}")
                count += 1
                it.GoToNextItem()

            # Mostrar en consola
            self.log(f"Nodos en escena ({count} totales):")
            for line in lines:
                self.log(line)
            self.log_ok(f"{count} nodos listados")

        except Exception as e:
            self.log_error(f"Error listando nodos: {e}")

    def _cmd_cargar(self, match):
        """cargar <ruta>"""
        ruta = match.group(2).strip()

        # Expandir ~ si es necesario
        if ruta.startswith("~"):
            ruta = os.path.expanduser(ruta)

        if not os.path.exists(ruta):
            self.log_error(f"Archivo no encontrado: {ruta}")
            return

        try:
            import slicer
            ext = os.path.splitext(ruta)[1].lower()

            if ext in (".nrrd", ".nii", ".nii.gz", ".mha", ".mhd"):
                node = slicer.util.loadVolume(ruta)
                self.log_ok(f"Volumen cargado: {node.GetName()}")
            elif ext == ".dcm" or os.path.isdir(ruta):
                from DICOMLib import DICOMUtils
                db_dir = DICOMUtils.openTemporaryDatabase()
                DICOMUtils.importDicom(ruta)
                series = DICOMUtils.allSeriesUIDsInDatabase()
                if series:
                    DICOMUtils.loadSeriesByUID(series)
                    self.log_ok(f"DICOM cargado desde: {ruta}")
                DICOMUtils.closeTemporaryDatabase(db_dir, cleanup=True)
            else:
                self.log_error(f"Extension no soportada: {ext}")

        except Exception as e:
            self.log_error(f"Error cargando archivo: {e}")

    def _cmd_colormap(self, match):
        """colormap <nodo> <mapa>"""
        nodo_nombre = match.group(1).strip()
        mapa = match.group(2).strip()

        try:
            import slicer

            # Buscar nodo por nombre
            node = None
            it = slicer.mrmlScene.NewIterator()
            it.InitTraversal()
            while True:
                n = it.GetCurrentItem()
                if not n:
                    break
                if n.GetName().lower() == nodo_nombre.lower():
                    node = n
                    break
                it.GoToNextItem()

            if not node:
                self.log_error(f'Nodo "{nodo_nombre}" no encontrado')
                return

            # Buscar colormap
            color_id = f"vtkMRMLColorTableNode{mapa}"
            color_node = slicer.mrmlScene.GetNodeByID(color_id)
            if not color_node:
                # Buscar por nombre parcial
                it2 = slicer.mrmlScene.NewIterator()
                it2.InitTraversal()
                while True:
                    cn = it2.GetCurrentItem()
                    if not cn:
                        break
                    if cn.IsA("vtkMRMLColorTableNode") and \
                            mapa.lower() in cn.GetName().lower():
                        color_node = cn
                        break
                    it2.GoToNextItem()

            if not color_node:
                self.log_error(
                    f'Colormap "{mapa}" no encontrado. '
                    "Opciones: Rainbow, Hot, Cold, Grey, CT-..."
                )
                return

            # Aplicar al display node
            dn = node.GetDisplayNode()
            if dn:
                dn.SetAndObserveColorNodeID(color_node.GetID())
                self.log_ok(f"Colormap '{mapa}' aplicado a '{node.GetName()}'")
            else:
                self.log_error(f"El nodo '{node.GetName()}' no tiene display node")

        except Exception as e:
            self.log_error(f"Error cambiando colormap: {e}")

    def _cmd_ventana(self, match):
        """ventana <width> <level>"""
        width = float(match.group(2))
        level = float(match.group(3))

        try:
            import slicer

            # Aplicar a todos los volumenes escalares visibles
            aplicados = 0
            it = slicer.mrmlScene.NewIterator()
            it.InitTraversal()
            while True:
                node = it.GetCurrentItem()
                if not node:
                    break
                if node.IsA("vtkMRMLScalarVolumeNode"):
                    dn = node.GetDisplayNode()
                    if dn:
                        dn.AutoWindowLevelOff()
                        dn.SetWindowLevel(width, level)
                        aplicados += 1
                it.GoToNextItem()

            self.log_ok(
                f"Window/Level {width}/{level} aplicado a {aplicados} volumen(es)"
            )
        except Exception as e:
            self.log_error(f"Error ajustando ventana: {e}")

    def _cmd_ayuda(self, match):
        """ayuda"""
        self.log("")
        self.log('<span style="color: #569cd6; font-weight: bold;">'
                 "COMANDOS DISPONIBLES:</span>")
        self.log("")
        for patron, desc, func in self._comandos:
            self.log(f"  {desc:<45s}")
        self.log("")
        self.log('<span style="color: #888;">'
                 "Tips: Los comandos se entienden en castellano o ingles."
                 "</span>")
        self.log('<span style="color: #888;">'
                 "Ej: 'screenshot', 'fusion 0.5', 'vista 3D', 'nodos'"
                 "</span>")

    def _cmd_limpiar(self, match):
        """cls"""
        if self._output:
            self._output.clear()

    def _cmd_salir(self, match):
        """salir"""
        self.ocultar()
