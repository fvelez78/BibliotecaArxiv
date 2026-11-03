"""Ventanas secundarias: agregar por código, monitoreo de temas, identificar e importar PDFs,
versiones nuevas y duplicados."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTime, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextBrowser, QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import renombrar_arxiv as core
import tareas
import temas as tm
from i18n import en_ingles, nombre_categoria, tr

APP_DIR = Path(__file__).resolve().parent
TAREA_WINDOWS = "Biblioteca arXiv - Monitor"
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def abrir_archivo(ruta):
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # noqa: S606
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))


def mostrar_en_carpeta(ruta):
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(Path(ruta))])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(ruta).parent)))


def item(texto, tooltip=None, color=None, datos=None, marcable=False, marcado=True):
    it = QTableWidgetItem(str(texto) if texto is not None else "")
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsUserCheckable if marcable else Qt.NoItemFlags))
    if marcable:
        it.setCheckState(Qt.Checked if marcado else Qt.Unchecked)
    if tooltip:
        it.setToolTip(tooltip)
    if color:
        it.setForeground(QColor(color))
    if datos is not None:
        it.setData(Qt.UserRole, datos)
    return it


def tabla(columnas, estirar=1):
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(estirar, QHeaderView.Stretch)
    t.verticalHeader().setDefaultSectionSize(28)
    return t


# =============================================================================================
class DialogoAgregar(QDialog):
    def __init__(self, padre):
        super().__init__(padre)
        self.setWindowTitle(tr("Agregar artículos por código"))
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        info = QLabel(tr("Pega códigos o enlaces de arXiv, en cualquier formato (uno por línea, separados "
                         "por comas, URLs de arXiv…). Los que ya están en la biblioteca se omiten."))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("1706.03762\nhttps://arxiv.org/abs/2410.05229v2\nhep-th/9711200")
        lay.addWidget(self.texto, 1)
        bb = QDialogButtonBox()
        b = bb.addButton(tr("Descargar y agregar"), QDialogButtonBox.AcceptRole)
        b.setObjectName("primario")
        bb.addButton(tr("Cancelar"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# =============================================================================================
class DialogoTema(QDialog):
    """Crear o editar un tema a monitorear."""

    def __init__(self, padre, m=None):
        super().__init__(padre)
        self.m = dict(m or {})
        self.setWindowTitle(tr("Editar tema") if m else tr("Nuevo tema"))
        self.resize(620, 430)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.nombre = QLineEdit(self.m.get("nombre", ""))
        self.nombre.setPlaceholderText(tr("Ej.: Materia oscura"))
        self.palabras = QPlainTextEdit(self.m.get("palabras", ""))
        self.palabras.setPlaceholderText(tr("Frases separadas por coma. Ej.: dark matter, galaxy rotation curves"))
        self.palabras.setFixedHeight(80)
        self.categorias = QLineEdit(self.m.get("categorias", ""))
        self.categorias.setPlaceholderText(tr("Opcional. Códigos separados por coma. Ej.: astro-ph.CO, astro-ph.GA"))
        codigos = sorted(set(core.SUBCATEGORIAS) | {"gr-qc", "quant-ph", "math-ph"})
        comp = QCompleter(codigos, self.categorias)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.categorias.setCompleter(comp)
        self.autores = QLineEdit(self.m.get("autores", ""))
        self.autores.setPlaceholderText(tr("Opcional. Apellidos separados por coma"))
        self.frecuencia = QComboBox()
        self.frecuencia.addItem(tr("Semanal"), "semanal")
        self.frecuencia.addItem(tr("Diaria"), "diaria")
        self.frecuencia.setCurrentIndex(1 if self.m.get("frecuencia") == "diaria" else 0)
        self.activo = QCheckBox(tr("Activo"))
        self.activo.setChecked(bool(self.m.get("activo", 1)))
        form.addRow(tr("Nombre"), self.nombre)
        form.addRow(tr("Palabras o frases"), self.palabras)
        form.addRow(tr("Categorías"), self.categorias)
        form.addRow(tr("Autores"), self.autores)
        form.addRow(tr("Frecuencia"), self.frecuencia)
        form.addRow("", self.activo)
        lay.addLayout(form)
        self.vista = QLabel()
        self.vista.setWordWrap(True)
        self.vista.setObjectName("etiqueta")
        self.vista.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.vista)
        for w in (self.palabras,):
            w.textChanged.connect(self._vista)
        for w in (self.categorias, self.autores):
            w.textChanged.connect(self._vista)
        self._vista()
        lay.addStretch(1)
        bb = QDialogButtonBox()
        b = bb.addButton(tr("Guardar"), QDialogButtonBox.AcceptRole)
        b.setObjectName("primario")
        bb.addButton(tr("Cancelar"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._aceptar)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def valor(self):
        return dict(self.m, nombre=self.nombre.text().strip(), palabras=self.palabras.toPlainText().strip(),
                    categorias=self.categorias.text().strip(), autores=self.autores.text().strip(),
                    frecuencia=self.frecuencia.currentData(), activo=int(self.activo.isChecked()))

    def _vista(self):
        q = tareas.construir_consulta(self.valor())
        self.vista.setText(tr("Consulta a arXiv: ") + (q or "—"))

    def _aceptar(self):
        v = self.valor()
        if not v["nombre"] or not (v["palabras"] or v["categorias"] or v["autores"]):
            QMessageBox.warning(self, tr("Falta información"),
                                tr("Escribe un nombre y al menos palabras, categorías o autores."))
            return
        self.accept()


# =============================================================================================
class DialogoMonitor(QDialog):
    """Temas monitoreados (izquierda) y artículos nuevos encontrados (derecha)."""

    def __init__(self, ventana):
        super().__init__(ventana)
        self.v = ventana
        self.cat = ventana.catalogo
        self.setWindowTitle(tr("Monitoreo de temas en arXiv"))
        self.resize(1250, 720)
        raiz = QHBoxLayout(self)
        div = QSplitter(Qt.Horizontal)
        raiz.addWidget(div)

        # --- izquierda: temas ---
        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(0, 0, 8, 0)
        t = QLabel(tr("Temas"))
        t.setObjectName("etiqueta")
        li.addWidget(t)
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(lambda _: self.cargar_novedades())
        self.lista.itemDoubleClicked.connect(lambda _: self.editar())
        li.addWidget(self.lista, 1)
        fila = QHBoxLayout()
        for texto, fn in ((tr("Nuevo"), self.nuevo), (tr("Editar"), self.editar), (tr("Eliminar"), self.eliminar)):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            fila.addWidget(b)
        li.addLayout(fila)
        b = QPushButton(tr("Revisar ahora"))
        b.setObjectName("primario")
        b.setToolTip(tr("Busca ya mismo artículos nuevos en todos los temas activos"))
        b.clicked.connect(self.revisar)
        li.addWidget(b)
        self.lbl_ultima = QLabel()
        self.lbl_ultima.setObjectName("etiqueta")
        self.lbl_ultima.setWordWrap(True)
        li.addWidget(self.lbl_ultima)

        caja = QWidget()
        caja.setObjectName("tarjeta")
        lc = QVBoxLayout(caja)
        t = QLabel(tr("Revisión automática"))
        t.setStyleSheet("font-weight: 600;")
        lc.addWidget(t)
        self.chk_abrir = QCheckBox(tr("Al abrir la app, revisar los temas a los que les toca"))
        self.chk_abrir.setChecked(self.v.cfg.get("monitor_al_abrir", True))
        self.chk_abrir.toggled.connect(self._cfg_abrir)
        lc.addWidget(self.chk_abrir)
        fila = QHBoxLayout()
        fila.addWidget(QLabel(tr("Con la app cerrada, todos los días a las")))
        self.hora = QTimeEdit(QTime.fromString(self.v.cfg.get("monitor_hora", "08:40"), "HH:mm"))
        self.hora.setDisplayFormat("HH:mm")
        fila.addWidget(self.hora)
        fila.addStretch(1)
        lc.addLayout(fila)
        fila = QHBoxLayout()
        self.b_prog = QPushButton(tr("Programar en Windows"))
        self.b_prog.clicked.connect(lambda: self.programar(True))
        self.b_quitar = QPushButton(tr("Quitar"))
        self.b_quitar.clicked.connect(lambda: self.programar(False))
        fila.addWidget(self.b_prog)
        fila.addWidget(self.b_quitar)
        lc.addLayout(fila)
        self.lbl_prog = QLabel()
        self.lbl_prog.setWordWrap(True)
        self.lbl_prog.setObjectName("etiqueta")
        lc.addWidget(self.lbl_prog)
        li.addWidget(caja)
        div.addWidget(izq)

        # --- derecha: novedades ---
        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(8, 0, 0, 0)
        fila = QHBoxLayout()
        self.lbl_nov = QLabel()
        self.lbl_nov.setObjectName("etiqueta")
        fila.addWidget(self.lbl_nov, 1)
        self.chk_vistos = QCheckBox(tr("Mostrar también vistos y descargados"))
        self.chk_vistos.setChecked(True)
        self.chk_vistos.toggled.connect(lambda _: self.cargar_novedades())
        fila.addWidget(self.chk_vistos)
        ld.addLayout(fila)
        self.tabla = tabla(["", tr("Título"), tr("Autores"), tr("Fecha"), tr("Categoría"), tr("Estado")])
        self.tabla.currentCellChanged.connect(lambda r, *_: self._mostrar_resumen(r))
        self.tabla.cellDoubleClicked.connect(lambda r, _c: self._ver_arxiv(r))
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.tabla)
        self.resumen = QTextBrowser()
        self.resumen.setOpenExternalLinks(True)
        sp.addWidget(self.resumen)
        sp.setSizes([430, 190])
        ld.addWidget(sp, 1)
        fila = QHBoxLayout()
        b = QPushButton(tr("Descargar marcados a la biblioteca"))
        b.setObjectName("primario")
        b.clicked.connect(self.descargar)
        fila.addWidget(b)
        for texto, estado in ((tr("Marcar como vistos"), "visto"), (tr("Descartar"), "descartado")):
            b = QPushButton(texto)
            b.clicked.connect(lambda _=False, e=estado: self.marcar(e))
            fila.addWidget(b)
        b = QPushButton(tr("Marcar todos / ninguno"))
        b.clicked.connect(self.alternar_marcas)
        fila.addWidget(b)
        fila.addStretch(1)
        b = QPushButton(tr("Cerrar"))
        b.clicked.connect(self.accept)
        fila.addWidget(b)
        ld.addLayout(fila)
        div.addWidget(der)
        div.setSizes([360, 890])

        self.cargar_temas()
        self._estado_programacion()

    # ----- temas -----
    def cargar_temas(self, seleccionar=None):
        self.monitores = self.cat.monitores()
        fila_actual = self.lista.currentRow()
        self.lista.blockSignals(True)
        self.lista.clear()
        total = sum(m["nuevos"] for m in self.monitores)
        it = QListWidgetItem(tr("Todos los temas") + (f"  ({total})" if total else ""))
        it.setData(Qt.UserRole, None)
        self.lista.addItem(it)
        for m in self.monitores:
            frec = tr("diaria") if m["frecuencia"] == "diaria" else tr("semanal")
            txt = m["nombre"] + (f"  ({m['nuevos']})" if m["nuevos"] else "")
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, m["id"])
            it.setToolTip(f"{frec} · " + tareas.construir_consulta(m))
            if not m["activo"]:
                it.setForeground(tm.color("tenue"))
            if m["nuevos"]:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.lista.addItem(it)
        fila = 0
        if seleccionar is not None:
            fila = next((i for i in range(self.lista.count())
                         if self.lista.item(i).data(Qt.UserRole) == seleccionar), 0)
        elif 0 <= fila_actual < self.lista.count():
            fila = fila_actual
        self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        fechas = [m["ultima_revision"] for m in self.monitores if m["ultima_revision"]]
        self.lbl_ultima.setText(tr("Última revisión: ") + (max(fechas).replace("T", " ")[:16] if fechas else "—")
                                if self.monitores else tr("Crea un tema con «Nuevo» para empezar."))
        self.cargar_novedades()

    def _tema_actual(self):
        it = self.lista.currentItem()
        mid = it.data(Qt.UserRole) if it else None
        return next((m for m in self.monitores if m["id"] == mid), None)

    def nuevo(self):
        d = DialogoTema(self)
        if d.exec() == QDialog.Accepted:
            mid = self.cat.guardar_monitor(d.valor())
            self.cargar_temas(mid)
            if QMessageBox.question(self, tr("Tema creado"),
                                    tr("¿Buscar ya los artículos de las últimas dos semanas?")) == QMessageBox.Yes:
                self.revisar([m for m in self.monitores if m["id"] == mid])

    def editar(self):
        m = self._tema_actual()
        if not m:
            return
        d = DialogoTema(self, m)
        if d.exec() == QDialog.Accepted:
            self.cat.guardar_monitor(d.valor())
            self.cargar_temas(m["id"])

    def eliminar(self):
        m = self._tema_actual()
        if m and QMessageBox.question(self, tr("Eliminar tema"),
                                      tr("¿Eliminar «{n}» y sus resultados?", n=m["nombre"])) == QMessageBox.Yes:
            self.cat.borrar_monitor(m["id"])
            self.cargar_temas()
            self.v.actualizar_insignia()

    def revisar(self, monitores=None):
        monitores = monitores or [m for m in self.monitores if m["activo"]]
        if not monitores:
            return

        def fin(res):
            n = sum(self.cat.guardar_novedades(m["id"], res.get(m["id"], [])) for m in monitores)
            for m in monitores:
                if m["id"] in res:
                    self.cat.marcar_revisado(m["id"])
            self.cargar_temas()
            self.v.actualizar_insignia()
            self.lbl_nov.setText(tr("{n} artículo(s) nuevo(s) encontrados.", n=n) + "  " + self.lbl_nov.text())
        self.v.correr(tr("Buscando artículos nuevos en arXiv…"),
                      lambda av, ca: tareas.revisar_monitores(monitores, av, ca), fin, padre=self)

    # ----- novedades -----
    def cargar_novedades(self):
        m = self._tema_actual()
        filas = self.cat.novedades(m["id"] if m else None)
        if not self.chk_vistos.isChecked():
            filas = [f for f in filas if f["estado"] == "nuevo"]
        self.filas = filas
        self.tabla.setRowCount(0)
        nombres = {"nuevo": tr("Nuevo"), "visto": tr("Visto"), "descargado": tr("En la biblioteca"),
                   "descartado": tr("Descartado")}
        colores = {"nuevo": "leyendo", "descargado": "leido", "visto": "tenue"}
        for f in filas:
            r = self.tabla.rowCount()
            self.tabla.insertRow(r)
            nuevo = f["estado"] == "nuevo"
            autores = f["autores"].split("; ")
            corto = autores[0] + (" et al." if len(autores) > 1 else "")
            self.tabla.setItem(r, 0, item("", marcable=f["estado"] in ("nuevo", "visto"), marcado=False,
                                          datos=f["id_arxiv"]))
            t = item(f["titulo"], tooltip=f["titulo"])
            if nuevo:
                fu = t.font()
                fu.setBold(True)
                t.setFont(fu)
            self.tabla.setItem(r, 1, t)
            self.tabla.setItem(r, 2, item(corto, tooltip=f["autores"]))
            self.tabla.setItem(r, 3, item((f["publicado"] or "")[:10]))
            self.tabla.setItem(r, 4, item(nombre_categoria(f["categoria"]), tooltip=f["categoria"]))
            self.tabla.setItem(r, 5, item(nombres.get(f["estado"], f["estado"]),
                                          color=tm.T[colores.get(f["estado"], "texto")]))
        n_nuevos = sum(f["estado"] == "nuevo" for f in filas)
        self.lbl_nov.setText(tr("{t} artículos · {n} nuevos", t=len(filas), n=n_nuevos))
        h = self.tabla.horizontalHeader()
        for col, ancho in ((0, 30), (2, 160), (3, 92), (4, 230), (5, 120)):
            h.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tabla.setColumnWidth(col, ancho)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        if filas:
            self.tabla.setCurrentCell(0, 1)
        else:
            self.resumen.setHtml(f'<p style="color:{tm.T["texto3"]}">' +
                                 tr("No hay artículos para mostrar. Usa «Revisar ahora».") + "</p>")

    def _mostrar_resumen(self, r):
        if not (0 <= r < len(self.filas)):
            return
        f = self.filas[r]
        self.resumen.setHtml(
            f'<h3 style="margin:0">{f["titulo"]}</h3>'
            f'<p style="color:{tm.T["texto2"]}">{f["autores"]}<br>{(f["publicado"] or "")[:10]} · '
            f'{f["categoria"]} · <a href="{f["url_abs"]}" style="color:{tm.T["link"]}">{f["id_arxiv"]}</a></p>'
            f'<p>{f["resumen"]}</p>')

    def _ver_arxiv(self, r):
        if 0 <= r < len(self.filas):
            QDesktopServices.openUrl(QUrl(self.filas[r]["url_abs"]))

    def _marcados(self):
        ids = [self.tabla.item(r, 0).data(Qt.UserRole) for r in range(self.tabla.rowCount())
               if self.tabla.item(r, 0).checkState() == Qt.Checked]
        if not ids:  # si no marcó ninguno, usa las filas seleccionadas
            ids = [self.tabla.item(ix.row(), 0).data(Qt.UserRole)
                   for ix in self.tabla.selectionModel().selectedRows()]
        return ids

    def alternar_marcas(self):
        marcables = [self.tabla.item(r, 0) for r in range(self.tabla.rowCount())
                     if self.tabla.item(r, 0).flags() & Qt.ItemIsUserCheckable]
        todos = all(i.checkState() == Qt.Checked for i in marcables)
        for i in marcables:
            i.setCheckState(Qt.Unchecked if todos else Qt.Checked)

    def marcar(self, estado):
        ids = self._marcados()
        if ids:
            self.cat.marcar_novedades(ids, estado)
            self.cargar_temas()
            self.v.actualizar_insignia()

    def descargar(self):
        ids = set(self._marcados())
        filas = [f for f in self.filas if f["id_arxiv"] in ids and f["estado"] != "descargado"]
        if not filas:
            QMessageBox.information(self, tr("Descargar"), tr("Marca primero los artículos que quieres descargar."))
            return
        metas = [json.loads(f["meta_json"]) for f in filas]

        def fin(hechos):
            self.v.registrar_descargados(hechos)
            self.cat.marcar_novedades([h[0] for h in hechos], "descargado")
            self.cargar_temas()
            self.v.actualizar_insignia()
        self.v.correr(tr("Descargando {n} artículo(s)…", n=len(metas)),
                      lambda av, ca: tareas.descargar_a_biblioteca(metas, self.v.catalogo.biblioteca,
                                                                    self.v.formato_nombre(), av, ca), fin,
                      padre=self)

    # ----- configuración -----
    def _cfg_abrir(self, v):
        self.v.cfg["monitor_al_abrir"] = v
        self.v.guardar_cfg()

    def _estado_programacion(self):
        if not sys.platform.startswith("win"):
            self.lbl_prog.setText(tr("La programación automática solo está disponible en Windows."))
            self.b_prog.setEnabled(False)
            self.b_quitar.setEnabled(False)
            return
        r = subprocess.run(["schtasks", "/Query", "/TN", TAREA_WINDOWS], capture_output=True, text=True,
                           creationflags=SIN_VENTANA)
        activa = r.returncode == 0
        self.lbl_prog.setText(tr("Programada: Windows revisa los temas todos los días, aunque la app esté "
                                 "cerrada, y te avisa con una notificación.") if activa else
                              tr("No programada: los temas se revisan solo cuando abres la app."))
        self.b_quitar.setEnabled(activa)

    def programar(self, activar):
        if activar:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            exe = pyw if pyw.exists() else Path(sys.executable)
            hora = self.hora.time().toString("HH:mm")
            cmd = ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", hora, "/TN", TAREA_WINDOWS,
                   "/TR", f'"{exe}" "{APP_DIR / "monitor.py"}"']
            self.v.cfg["monitor_hora"] = hora
            self.v.guardar_cfg()
        else:
            cmd = ["schtasks", "/Delete", "/F", "/TN", TAREA_WINDOWS]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=SIN_VENTANA)
        if r.returncode != 0:
            QMessageBox.warning(self, tr("Programador de tareas"), (r.stderr or r.stdout).strip())
        self._estado_programacion()


# =============================================================================================
class DialogoIdentificados(QDialog):
    """Resultado de identificar PDFs: el usuario elige cuáles incorporar y si mover o copiar."""

    def __init__(self, padre, resultados, ids_existentes):
        super().__init__(padre)
        self.setWindowTitle(tr("Identificar e importar PDFs"))
        self.resize(1200, 600)
        self.res = resultados
        lay = QVBoxLayout(self)
        ok = sum(1 for r in resultados if r["meta"])
        info = QLabel(tr("Se identificaron {ok} de {n} archivos. Revisa la lista: los marcados se "
                         "renombran, se guardan en su carpeta de la biblioteca y entran al catálogo.",
                         ok=ok, n=len(resultados)))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.t = tabla(["", tr("Archivo"), tr("Identificado como"), tr("Tipo"), tr("Cómo"), tr("Situación")], estirar=2)
        for r in resultados:
            fila = self.t.rowCount()
            self.t.insertRow(fila)
            meta = r["meta"]
            if meta and r["aid"] in ids_existentes:
                tiene_pdf = ids_existentes[r["aid"]]
                sit = tr("ya está en la biblioteca") if tiene_pdf else \
                    tr("está en el catálogo sin PDF: se vuelve a vincular")
                color, marcar = ("tenue", False) if tiene_pdf else ("leyendo", True)
            elif meta:
                sit, color, marcar = tr("nuevo"), "leido", True
            else:
                sit, color, marcar = tr("no identificado"), "alerta", False
            r["situacion"] = sit
            self.t.setItem(fila, 0, item("", marcable=bool(meta), marcado=marcar))
            self.t.setItem(fila, 1, item(Path(r["ruta"]).name, tooltip=r["ruta"]))
            titulo = (meta or {}).get("titulo") or (tr("título leído: ") + r["titulo_leido"] if r["titulo_leido"] else "—")
            self.t.setItem(fila, 2, item(titulo, tooltip=titulo))
            tipo = {"arxiv": "arXiv " + (r["aid"] or ""), "otro": tr("Otro (no arXiv)")}.get(r["tipo"], "—")
            self.t.setItem(fila, 3, item(tipo, tooltip=r["aid"] or ""))
            self.t.setItem(fila, 4, item(tr(r["metodo"]) if r["metodo"] else ""))
            self.t.setItem(fila, 5, item(sit, color=tm.T[color]))
        lay.addWidget(self.t, 1)
        fila = QHBoxLayout()
        self.r_mover = QRadioButton(tr("Mover los archivos a la biblioteca"))
        self.r_copiar = QRadioButton(tr("Copiar (dejar los originales donde están)"))
        self.r_mover.setChecked(True)
        fila.addWidget(self.r_mover)
        fila.addWidget(self.r_copiar)
        fila.addStretch(1)
        lay.addLayout(fila)
        bb = QDialogButtonBox()
        b = bb.addButton(tr("Importar marcados"), QDialogButtonBox.AcceptRole)
        b.setObjectName("primario")
        bb.addButton(tr("Cancelar"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def elegidos(self):
        return [r for i, r in enumerate(self.res)
                if self.t.item(i, 0).checkState() == Qt.Checked and r["meta"]]


# =============================================================================================
class DialogoVersiones(QDialog):
    def __init__(self, padre, pares):
        super().__init__(padre)
        self.setWindowTitle(tr("Versiones nuevas en arXiv"))
        self.resize(820, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("{n} artículos tienen una versión más reciente en arXiv. Marca los que "
                                "quieras descargar (reemplazan al PDF actual).", n=len(pares))))
        self.lista = QTreeWidget()
        self.lista.setHeaderLabels([tr("Artículo"), tr("Tu versión"), tr("En arXiv")])
        self.lista.setRootIsDecorated(False)
        self.lista.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pares = pares
        for a, m in pares:
            it = QTreeWidgetItem([a["titulo"], a["version"] or "", m["id_version"]])
            it.setCheckState(0, Qt.Checked)
            self.lista.addTopLevelItem(it)
        lay.addWidget(self.lista)
        bb = QDialogButtonBox()
        b = bb.addButton(tr("Descargar marcadas"), QDialogButtonBox.AcceptRole)
        b.setObjectName("primario")
        bb.addButton(tr("Solo dejar el aviso"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def marcados(self):
        return [p for i, p in enumerate(self.pares) if self.lista.topLevelItem(i).checkState(0) == Qt.Checked]


# =============================================================================================
class DialogoDuplicados(QDialog):
    def __init__(self, padre, res, biblioteca):
        super().__init__(padre)
        self.setWindowTitle(tr("Duplicados y archivos sueltos"))
        self.resize(900, 520)
        self.biblioteca = Path(biblioteca)
        self.movidos = 0
        lay = QVBoxLayout(self)
        info = QLabel(tr("Nada se borra: los archivos que elijas se mueven a la carpeta <b>_duplicados</b> "
                         "dentro de la biblioteca, para que los revises y borres tú."))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels([tr("Archivo / artículo"), tr("Detalle")])
        self.arbol.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.arbol.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.arbol)
        s = QTreeWidgetItem([tr("PDF sueltos en la biblioteca que el catálogo no usa ({n})", n=len(res["sueltos"]))])
        self.arbol.addTopLevelItem(s)
        for ruta, aid, art in res["sueltos"]:
            if art:
                det = tr("copia de un artículo ya catalogado ({aid})", aid=aid)
            elif aid:
                det = tr("arXiv {aid}, sin catalogar: usa «Importar PDFs»", aid=aid)
            else:
                det = tr("no se reconoce como arXiv: usa «Importar PDFs» para identificarlo")
            it = QTreeWidgetItem([Path(ruta).name, det])
            it.setToolTip(0, ruta)
            it.setData(0, Qt.UserRole, ruta)
            s.addChild(it)
        t = QTreeWidgetItem([tr("Artículos distintos con el mismo título ({n} grupos)", n=len(res["titulos"]))])
        self.arbol.addTopLevelItem(t)
        for grupo in res["titulos"]:
            g = QTreeWidgetItem([grupo[0]["titulo"], tr("{n} registros", n=len(grupo))])
            t.addChild(g)
            for a in grupo:
                it = QTreeWidgetItem([a["nombre_archivo"] or a["id_arxiv"],
                                      f'{a["id_arxiv"]} · {nombre_categoria(a["categoria_principal"], a["categoria_es"])}'])
                it.setToolTip(0, a["ruta_archivo"] or "")
                if a["existe"]:
                    it.setData(0, Qt.UserRole, a["ruta_archivo"])
                g.addChild(it)
        self.arbol.expandAll()
        bb = QHBoxLayout()
        b1 = QPushButton(tr("Mostrar en carpeta"))
        b1.clicked.connect(self._mostrar)
        b2 = QPushButton(tr("Mover seleccionados a _duplicados"))
        b2.clicked.connect(self._mover)
        b3 = QPushButton(tr("Cerrar"))
        b3.clicked.connect(self.accept)
        bb.addWidget(b1)
        bb.addWidget(b2)
        bb.addStretch(1)
        bb.addWidget(b3)
        lay.addLayout(bb)

    def _rutas(self):
        return [it.data(0, Qt.UserRole) for it in self.arbol.selectedItems() if it.data(0, Qt.UserRole)]

    def _mostrar(self):
        r = self._rutas()
        if r:
            mostrar_en_carpeta(r[0])

    def _mover(self):
        rutas = self._rutas()
        if not rutas:
            return
        destino = self.biblioteca / "_duplicados"
        destino.mkdir(exist_ok=True)
        for r in rutas:
            shutil.move(r, core.destino_libre(destino, Path(r).name))
            self.movidos += 1
        for it in self.arbol.selectedItems():
            if it.data(0, Qt.UserRole) in rutas:
                it.setText(1, tr("movido a _duplicados"))
                it.setData(0, Qt.UserRole, None)
                it.setForeground(0, tm.color("tenue"))
