"""
Biblioteca arXiv — app de escritorio para la biblioteca de artículos.

Navegar, buscar y leer · favoritos, estados, etiquetas y notas · portadas · BibTeX ·
versiones nuevas · duplicados · palabras clave · agregar por código · identificar e importar PDFs ·
monitoreo de temas en arXiv · tema claro/oscuro · español/inglés.

Usa el mismo catálogo que genera renombrar_arxiv.py (catalogo_arxiv.sqlite).
"""
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QAbstractTableModel, QModelIndex, QObject, QProcess,
                            QRunnable, QSize, QStringListModel, Qt, QThread, QThreadPool, QTimer, QUrl,
                            Signal)
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QCompleter, QDialog, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListView, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTableView,
                               QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                               QVBoxLayout, QWidget)

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import renombrar_arxiv as core  # noqa: E402
import bibtex  # noqa: E402
import tareas  # noqa: E402
import temas as tm  # noqa: E402
from datos import ESTADOS, NOMBRE_CATALOGO, Catalogo, sin_tildes  # noqa: E402
from dialogos import (DialogoAgregar, DialogoDuplicados, DialogoIdentificados, DialogoMonitor,  # noqa: E402
                      DialogoVersiones, abrir_archivo, mostrar_en_carpeta)
from i18n import en_ingles, nombre_area, nombre_categoria, poner_idioma, tr  # noqa: E402

CONFIG = APP_DIR / "config.json"
BIBLIOTECA_POR_DEFECTO = r"D:\Biblioteca_arXiv"
VERSION = "3.1"
FORMATO_NOMBRE = "{autor} {año} - {titulo}"
ROL_FILTRO = Qt.UserRole + 1
SUFIJO_MINI = "_hd.png"
CLAVE_ESTADO = {"Por leer": "por_leer", "Leyendo": "leyendo", "Leído": "leido"}


def leer_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def id_archivo(aid):
    import re
    return re.sub(r"[^\w.\-]", "_", aid)


def nombre_cat(a):
    return nombre_categoria(a["categoria_principal"], a["categoria_es"])


class Trabajo(QThread):
    """Corre una función larga fuera de la interfaz. fn(avance, cancelado) -> resultado."""
    avance = Signal(int, int, str)
    listo = Signal(object)
    fallo = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        try:
            res = self.fn(lambda i, n, t: self.avance.emit(i, n, t), lambda: self._cancelar)
            self.listo.emit(res)
        except Exception as e:  # noqa: BLE001
            self.fallo.emit(f"{e}\n\n{traceback.format_exc()}")


# =============================================================================================
# Miniaturas
# =============================================================================================
class SenalesMini(QObject):
    lista = Signal(str, str)


class TareaMini(QRunnable):
    def __init__(self, aid, pdf, destino):
        super().__init__()
        self.aid, self.pdf, self.destino = aid, pdf, destino
        self.senales = SenalesMini()

    def run(self):
        try:
            if not self.destino.exists():
                import pymupdf
                doc = pymupdf.open(self.pdf)
                pag = doc.load_page(0)
                esc = PanelVistaPrevia.ANCHO_RENDER / pag.rect.width
                pag.get_pixmap(matrix=pymupdf.Matrix(esc, esc)).save(str(self.destino))
                doc.close()
            self.senales.lista.emit(self.aid, str(self.destino))
        except Exception:
            self.senales.lista.emit(self.aid, "")


class GestorMiniaturas(QObject):
    lista = Signal(str)

    def __init__(self):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.carpeta = None
        self.png, self.chicas, self.pendientes, self._tareas = {}, {}, set(), []

    def preparar(self, biblioteca):
        self.carpeta = Path(biblioteca) / ".miniaturas"
        self.carpeta.mkdir(exist_ok=True)
        if sys.platform.startswith("win"):
            subprocess.run(["attrib", "+h", str(self.carpeta)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.png.clear()
        self.chicas.clear()
        for viejo in self.carpeta.glob("*.png"):          # miniaturas de baja resolución (versiones < 3.1)
            if not viejo.name.endswith(SUFIJO_MINI):
                viejo.unlink(missing_ok=True)

    def olvidar(self, aid):
        self.png.pop(aid, None)
        self.chicas.pop(aid, None)
        if self.carpeta:
            (self.carpeta / (id_archivo(aid) + SUFIJO_MINI)).unlink(missing_ok=True)

    def pedir(self, a):
        aid = a["id_arxiv"]
        if aid in self.png:
            return self.png[aid]
        if not a["existe"] or not self.carpeta:
            self.png[aid] = ""
            return ""
        destino = self.carpeta / (id_archivo(aid) + SUFIJO_MINI)
        if destino.exists():
            self.png[aid] = str(destino)
            return str(destino)
        if aid not in self.pendientes:
            self.pendientes.add(aid)
            t = TareaMini(aid, a["ruta_archivo"], destino)
            t.senales.lista.connect(self._hecha)
            self._tareas.append(t)
            self.pool.start(t)
        return None

    def _hecha(self, aid, png):
        self.pendientes.discard(aid)
        self._tareas = [t for t in self._tareas if t.aid != aid]
        self.png[aid] = png
        self.lista.emit(aid)

    def chica(self, a, tam):
        aid = a["id_arxiv"]
        if aid in self.chicas:
            return self.chicas[aid]
        png = self.pedir(a)
        if png:
            pm = QPixmap(png).scaled(tam, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.chicas[aid] = pm
            return pm
        return None


# =============================================================================================
# Modelos
# =============================================================================================
class ModeloArticulos(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.filas = []
        self._orden = (1, Qt.AscendingOrder)
        self.encabezados = ["★", tr("Título"), tr("Autores"), tr("Año"), tr("Categoría"), tr("Estado")]

    def cargar(self, filas):
        self.beginResetModel()
        self.filas = list(filas)
        self._ordenar(*self._orden)
        self.endResetModel()

    def refrescar(self):
        if self.filas:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.filas) - 1, self.columnCount() - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.filas)

    def columnCount(self, parent=QModelIndex()):
        return len(self.encabezados)

    def headerData(self, s, o, rol=Qt.DisplayRole):
        if o == Qt.Horizontal and rol == Qt.DisplayRole:
            return self.encabezados[s]
        if o == Qt.Horizontal and rol == Qt.ToolTipRole and s == 0:
            return tr("Favorito (clic para marcar)")
        return None

    @staticmethod
    def autores_corto(a):
        return (a["primer_autor"] or "") + (" et al." if (a["n_autores"] or 0) > 1 else "")

    def data(self, index, rol=Qt.DisplayRole):
        if not index.isValid():
            return None
        a, col = self.filas[index.row()], index.column()
        if rol == Qt.DisplayRole:
            if col == 0:
                return "★" if a["favorito"] else "☆"
            titulo = a["titulo"] + ("   ⟳" if a["version_nueva"] else "")
            return [None, titulo, self.autores_corto(a), a["anio"] or "", nombre_cat(a),
                    tr(a["estado"]) if a["estado"] else ""][col]
        if rol == Qt.ToolTipRole:
            if col == 0:
                return tr("Quitar de favoritos") if a["favorito"] else tr("Marcar como favorito")
            if not a["existe"]:
                return tr("No se encuentra el PDF en la ruta del catálogo")
            if col == 1:
                extra = "\n" + tr("Versión nueva en arXiv: {v}", v=a["version_nueva"]) if a["version_nueva"] else ""
                etq = "\n" + tr("Etiquetas: {e}", e=", ".join(a["etiquetas"])) if a["etiquetas"] else ""
                return a["titulo"] + etq + extra
            return [None, None, a["autores"], a["publicado"], a["categoria_principal"], None][col]
        if rol == Qt.ForegroundRole:
            if col == 0:
                return tm.color("dorado") if a["favorito"] else tm.color("estrella_off")
            if col == 5 and a["estado"]:
                return tm.color_estado(a["estado"])
            if not a["existe"]:
                return tm.color("tenue")
        if rol == Qt.TextAlignmentRole and col in (0, 3):
            return int(Qt.AlignCenter)
        if rol == Qt.FontRole and col == 0:
            f = QFont()
            f.setPointSize(f.pointSize() + 2)
            return f
        return None

    def articulo(self, fila):
        return self.filas[fila] if 0 <= fila < len(self.filas) else None

    def sort(self, columna, orden=Qt.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        self._ordenar(columna, orden)
        self.layoutChanged.emit()

    def _ordenar(self, columna, orden):
        self._orden = (columna, orden)
        claves = [lambda a: (not a["favorito"], sin_tildes(a["titulo"])),
                  lambda a: sin_tildes(a["titulo"]),
                  lambda a: sin_tildes(a["primer_autor"]),
                  lambda a: a["anio"] or 0,
                  lambda a: sin_tildes(nombre_cat(a)),
                  lambda a: (ESTADOS.index(a["estado"]) if a["estado"] in ESTADOS else 9)]
        self.filas.sort(key=claves[columna], reverse=(orden == Qt.DescendingOrder))


class ModeloPortadas(QAbstractListModel):
    ICONO = QSize(138, 184)

    def __init__(self, base, miniaturas):
        super().__init__()
        self.base, self.mini = base, miniaturas
        base.modelReset.connect(self._reset)
        base.layoutChanged.connect(self._reset)
        base.dataChanged.connect(self._todo_cambio)
        miniaturas.lista.connect(self._mini_lista)
        self.recolorear()

    def recolorear(self):
        pm = QPixmap(self.ICONO)
        pm.fill(tm.color("mini_vacia"))
        p = QPainter(pm)
        p.setPen(tm.color("tenue"))
        p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        p.drawText(pm.rect(), Qt.AlignCenter, "PDF")
        p.end()
        self._vacia = pm
        self._todo_cambio()

    def _todo_cambio(self, *_):
        if self.rowCount():
            self.dataChanged.emit(self.index(0), self.index(self.rowCount() - 1))

    def _reset(self, *_):
        self.beginResetModel()
        self.endResetModel()

    def _mini_lista(self, aid):
        for i, a in enumerate(self.base.filas):
            if a["id_arxiv"] == aid:
                ix = self.index(i)
                self.dataChanged.emit(ix, ix, [Qt.DecorationRole])
                break

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.base.filas)

    def data(self, index, rol=Qt.DisplayRole):
        if not index.isValid():
            return None
        a = self.base.filas[index.row()]
        if rol == Qt.DisplayRole:
            return ("★ " if a["favorito"] else "") + a["titulo"]
        if rol == Qt.DecorationRole:
            return self.mini.chica(a, self.ICONO) or self._vacia
        if rol == Qt.ToolTipRole:
            return f'{a["titulo"]}\n{ModeloArticulos.autores_corto(a)} · {a["anio"]}' + \
                   (f'\n{tr(a["estado"])}' if a["estado"] else "")
        if rol == Qt.ForegroundRole and a["favorito"]:
            return tm.color("dorado")
        return None


# =============================================================================================
# Panel de detalle
# =============================================================================================
class CompletadorEtiquetas(QCompleter):
    def splitPath(self, path):
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index):
        previas = [p.strip() for p in self.widget().text().split(",")[:-1] if p.strip()]
        return ", ".join(previas + [index.data()])


class PanelDetalle(QScrollArea):
    favorito = Signal(bool)
    estado = Signal(str)
    etiquetas = Signal(list)
    nota = Signal(str)
    buscar = Signal(str)
    accion = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumHeight(170)
        self.articulo = None
        self._cargando = False

        # Ficha en dos columnas: datos y acciones a la izquierda, resumen y notas a la derecha
        cont = QWidget()
        raiz = QHBoxLayout(cont)
        raiz.setContentsMargins(16, 12, 16, 12)
        raiz.setSpacing(24)
        lay = QVBoxLayout()
        lay.setSpacing(8)
        der = QVBoxLayout()
        der.setSpacing(6)
        raiz.addLayout(lay, 5)
        raiz.addLayout(der, 6)
        self.aviso_version = QPushButton()
        self.aviso_version.setObjectName("aviso")
        self.aviso_version.clicked.connect(lambda: self.accion.emit("version"))
        lay.addWidget(self.aviso_version)

        self.titulo = QLabel()
        self.titulo.setWordWrap(True)
        self.titulo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = QFont()
        f.setPointSize(f.pointSize() + 3)
        f.setBold(True)
        self.titulo.setFont(f)
        lay.addWidget(self.titulo)
        self.autores = QLabel()
        self.autores.setWordWrap(True)
        self.autores.setObjectName("secundario")
        self.autores.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.autores)

        org = QHBoxLayout()
        self.b_fav = QPushButton()
        self.b_fav.setCheckable(True)
        self.b_fav.setObjectName("favorito")
        self.b_fav.toggled.connect(self._fav)
        self.c_estado = QComboBox()
        self.c_estado.addItems([tr("Sin estado")] + [tr(e) for e in ESTADOS])
        self.c_estado.currentIndexChanged.connect(self._estado)
        org.addWidget(self.b_fav, 1)
        org.addWidget(self.c_estado, 1)
        lay.addLayout(org)

        self.e_etiquetas = QLineEdit()
        self.e_etiquetas.setPlaceholderText(tr("Etiquetas separadas por coma (Enter para guardar)"))
        self.e_etiquetas.editingFinished.connect(self._etiquetas)
        self.completador = CompletadorEtiquetas()
        self.completador.setCaseSensitivity(Qt.CaseInsensitive)
        self._modelo_comp = QStringListModel()
        self.completador.setModel(self._modelo_comp)
        self.e_etiquetas.setCompleter(self.completador)
        lay.addWidget(self.e_etiquetas)

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(6)
        self.campos = {}
        for clave, etiqueta in (("anio", tr("Año")), ("categoria", tr("Categoría")), ("otras", tr("También en")),
                                ("palabras", tr("Palabras clave")), ("tema", tr("Tema")),
                                ("revista", tr("Publicado en")), ("doi", "DOI"), ("comentario", tr("Comentario")),
                                ("id", tr("Identificador")), ("archivo", tr("Archivo"))):
            v = QLabel()
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
            if clave in ("palabras", "tema"):
                v.linkActivated.connect(lambda url: self.buscar.emit(url.split(":", 1)[1]))
            else:
                v.setOpenExternalLinks(True)
            et = QLabel(etiqueta)
            et.setObjectName("etiqueta")
            self.form.addRow(et, v)
            self.campos[clave] = (et, v)
        lay.addLayout(self.form)
        lay.addStretch(1)

        t = QLabel(tr("Resumen"))
        t.setObjectName("etiqueta")
        der.addWidget(t)
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.resumen.setAlignment(Qt.AlignJustify)
        der.addWidget(self.resumen)
        t = QLabel(tr("Mis notas"))
        t.setObjectName("etiqueta")
        der.addWidget(t)
        self.e_nota = QPlainTextEdit()
        self.e_nota.setPlaceholderText(tr("Escribe aquí tus notas sobre el artículo. Se guardan solas."))
        self.e_nota.setMinimumHeight(90)
        self.e_nota.textChanged.connect(self._nota_cambio)
        der.addWidget(self.e_nota, 1)
        self._t_nota = QTimer(self, singleShot=True, interval=800)
        self._t_nota.timeout.connect(self.guardar_nota)

        for etq in [self.titulo, self.autores, self.resumen] + [v for _, v in self.campos.values()]:
            etq.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            etq.setMinimumWidth(10)
        for w in (self.b_fav, self.c_estado, self.aviso_version, self.e_etiquetas):
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            w.setMinimumWidth(40)
        self.setWidget(cont)
        self.mostrar(None)

    def _fav(self, valor):
        self.b_fav.setText(("★ " if valor else "☆ ") + tr("Favorito"))
        if not self._cargando:
            self.favorito.emit(valor)

    def _estado(self, i):
        if not self._cargando:
            self.estado.emit("" if i == 0 else ESTADOS[i - 1])

    def _etiquetas(self):
        if self._cargando or not self.articulo:
            return
        lista = list(dict.fromkeys(e.strip() for e in self.e_etiquetas.text().split(",") if e.strip()))
        if lista != self.articulo["etiquetas"]:
            self.etiquetas.emit(lista)

    def _nota_cambio(self):
        if not self._cargando:
            self._t_nota.start()

    def guardar_nota(self):
        self._t_nota.stop()
        if self.articulo and self.e_nota.toPlainText() != self.articulo["nota"]:
            self.nota.emit(self.e_nota.toPlainText())

    def poner_sugerencias(self, etiquetas):
        self._modelo_comp.setStringList(etiquetas)

    def _campo(self, clave, texto):
        et, v = self.campos[clave]
        v.setText(texto or "")
        et.setVisible(bool(texto))
        v.setVisible(bool(texto))

    def mostrar(self, a):
        if self._t_nota.isActive():
            self.guardar_nota()
        self._cargando = True
        self.articulo = a
        vacio = a is None
        for w in (self.b_fav, self.c_estado, self.e_etiquetas, self.e_nota):
            w.setEnabled(not vacio)
        if vacio:
            self.titulo.setText(tr("Selecciona un artículo"))
            for w in (self.autores, self.resumen):
                w.setText("")
            self.aviso_version.hide()
            self.e_etiquetas.setText("")
            self.e_nota.setPlainText("")
            self.b_fav.setChecked(False)
            self.b_fav.setText("☆ " + tr("Favorito"))
            for k in self.campos:
                self._campo(k, "")
            self._cargando = False
            return
        T = tm.T
        self.titulo.setText(a["titulo"])
        self.autores.setText(a["autores"] or "")
        self.b_fav.setChecked(a["favorito"])
        self.b_fav.setText(("★ " if a["favorito"] else "☆ ") + tr("Favorito"))
        self.c_estado.setCurrentIndex(ESTADOS.index(a["estado"]) + 1 if a["estado"] in ESTADOS else 0)
        self.e_etiquetas.setText(", ".join(a["etiquetas"]))
        self.e_nota.setPlainText(a["nota"])
        if a["version_nueva"]:
            self.aviso_version.setText("⟳  " + tr("Versión nueva: {v} · Descargar", v=a["version_nueva"]))
            self.aviso_version.setToolTip(tr("Hay una versión más reciente en arXiv. Clic para descargarla "
                                             "(reemplaza el PDF; tus notas, etiquetas y favoritos se conservan)."))
            self.aviso_version.show()
        else:
            self.aviso_version.hide()
        es_arxiv = tareas.es_arxiv(a["id_arxiv"])
        self._campo("anio", str(a["anio"] or ""))
        cat = nombre_cat(a)
        self._campo("categoria", f'{cat}  ({a["categoria_principal"]})' if es_arxiv else cat)
        otras = [nombre_categoria(c) for c in (a["categorias"] or "").split("; ")
                 if c and c != a["categoria_principal"]]
        self._campo("otras", ", ".join(dict.fromkeys(otras)))
        enlace = lambda p: f'<a href="buscar:{p}" style="text-decoration:none; color:{T["link"]}">{p}</a>'  # noqa: E731
        gris = f'color:{T["texto3"]}'
        autor = [p for p, f in a["palabras"] if f == "autor"]
        oalex = [p for p, f in a["palabras"] if f == "OpenAlex"]
        tema = [p for p, f in a["palabras"] if f == "tema OpenAlex"]
        texto = ""
        if autor:
            texto += ", ".join(enlace(p) for p in autor) + f' <span style="{gris}">({tr("autor")})</span>'
        if oalex:
            texto += ("<br>" if texto else "") + ", ".join(enlace(p) for p in oalex) + \
                f' <span style="{gris}">(OpenAlex)</span>'
        self._campo("palabras", texto)
        self._campo("tema", ", ".join(enlace(p) for p in tema))
        self._campo("revista", a["journal_ref"])
        doi = a["doi"]
        link = f'color:{T["link"]}'
        self._campo("doi", f'<a href="https://doi.org/{doi}" style="{link}">{doi}</a>' if doi else "")
        self._campo("comentario", a["comentario"] if es_arxiv else "")
        self._campo("id", f'<a href="{a["url_abs"]}" style="{link}">{a["version"] or a["id_arxiv"]}</a>'
                    if es_arxiv else (a["id_arxiv"] if not doi else ""))
        self._campo("archivo", a["nombre_archivo"] if a["existe"]
                    else f'<span style="color:{T["alerta"]}">{tr("No se encuentra el PDF")}</span>')
        self.resumen.setText(a["resumen"] or "")
        self._cargando = False



class PanelVistaPrevia(QWidget):
    """Vista previa grande del PDF (primera página y siguientes)."""
    ANCHO_RENDER = 1100

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(280)
        self.articulo, self.original, self.pagina, self.paginas = None, None, 0, 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(6)
        self.imagen = QLabel()
        self.imagen.setObjectName("miniatura")
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.imagen.setCursor(Qt.PointingHandCursor)
        self.imagen.setToolTip(tr("Doble clic para abrir el PDF"))
        lay.addWidget(self.imagen, 1)
        nav = QHBoxLayout()
        self.b_ant = QPushButton("◀")
        self.b_sig = QPushButton("▶")
        for b in (self.b_ant, self.b_sig):
            b.setFixedWidth(44)
        self.b_ant.setToolTip(tr("Página anterior"))
        self.b_sig.setToolTip(tr("Página siguiente"))
        self.b_ant.clicked.connect(lambda: self.ir(self.pagina - 1))
        self.b_sig.clicked.connect(lambda: self.ir(self.pagina + 1))
        self.lbl = QLabel()
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setObjectName("secundario")
        nav.addWidget(self.b_ant)
        nav.addWidget(self.lbl, 1)
        nav.addWidget(self.b_sig)
        lay.addLayout(nav)
        fila = QHBoxLayout()
        self.b_pdf = QPushButton(tr("Abrir PDF"))
        self.b_pdf.setObjectName("primario")
        self.b_arxiv = QPushButton(tr("Web"))
        self.b_arxiv.setToolTip(tr("Ver la página del artículo (arXiv o DOI)"))
        self.b_carpeta = QPushButton(tr("Carpeta"))
        self.b_carpeta.setToolTip(tr("Mostrar el archivo en su carpeta"))
        self.b_bib = QPushButton("BibTeX")
        self.b_bib.setToolTip(tr("Copiar la referencia BibTeX (Ctrl+B)"))
        self.accion = lambda cual: None
        for b, acc in ((self.b_pdf, "pdf"), (self.b_arxiv, "arxiv"), (self.b_carpeta, "carpeta"), (self.b_bib, "bibtex")):
            b.clicked.connect(lambda _=False, x=acc: self.accion(x))
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumWidth(50)
            fila.addWidget(b, 3 if b is self.b_pdf else 2)
        lay.addLayout(fila)
        self.mostrar(None, "")

    def mouseDoubleClickEvent(self, e):
        self.accion("pdf")

    def mostrar(self, a, png):
        """png: ruta de la primera página ya renderizada, '' sin vista previa, None = generándose."""
        self.articulo, self.pagina = a, 0
        self.paginas = 0
        self.b_pdf.setEnabled(bool(a and a["existe"]))
        self.b_carpeta.setEnabled(bool(a and a["existe"]))
        self.b_arxiv.setEnabled(bool(a and a["url_abs"]))
        self.b_bib.setEnabled(a is not None)
        if a and a["existe"]:
            try:
                import pymupdf
                with pymupdf.open(a["ruta_archivo"]) as doc:
                    self.paginas = doc.page_count
            except Exception:
                self.paginas = 0
        self.poner_png(png)

    def poner_png(self, png):
        self.original = QPixmap(png) if png else None
        if png is None:
            self._texto(tr("Generando vista previa…"))
        elif not png:
            self._texto(tr("Sin vista previa") if self.articulo else "")
        self._actualizar()

    def ir(self, pagina):
        if not self.articulo or not (0 <= pagina < self.paginas):
            return
        self.pagina = pagina
        if pagina == 0:
            self.original = None
            self.poner_png(self._png_primera())
            return
        try:
            import pymupdf
            with pymupdf.open(self.articulo["ruta_archivo"]) as doc:
                pag = doc.load_page(pagina)
                esc = self.ANCHO_RENDER / pag.rect.width
                pm = pag.get_pixmap(matrix=pymupdf.Matrix(esc, esc))
                img = QPixmap()
                img.loadFromData(pm.tobytes("png"))
                self.original = img
        except Exception:
            self.original = None
        self._actualizar()

    def _png_primera(self):
        return getattr(self, "fuente_primera", lambda: "")()

    def _texto(self, t):
        self.imagen.setPixmap(QPixmap())
        self.imagen.setText(t)

    def _actualizar(self):
        if self.original and not self.original.isNull():
            r = self.imagen.contentsRect()
            self.imagen.setPixmap(self.original.scaled(r.width() - 8, r.height() - 8,
                                                       Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.lbl.setText(tr("Página {i} de {n}", i=self.pagina + 1, n=self.paginas) if self.paginas else "")
        self.b_ant.setEnabled(self.pagina > 0)
        self.b_sig.setEnabled(self.pagina < self.paginas - 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._actualizar()


# =============================================================================================
# Ventana principal
# =============================================================================================
class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Biblioteca arXiv")
        self.resize(1460, 900)
        self.cfg = leer_config()
        self.catalogo = None
        self.todos = []
        self.filtro = ("todo", None)
        self.ids_busqueda = None
        self._trabajos = []
        self.mini = GestorMiniaturas()
        self.mini.lista.connect(self._mini_lista)

        # ---------- barra de búsqueda ----------
        barra = QWidget()
        barra.setObjectName("barra")
        hb = QHBoxLayout(barra)
        hb.setContentsMargins(12, 8, 12, 8)
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText(tr("Buscar en título, resumen, autores, etiquetas, notas y palabras clave")
                                         + "   (Ctrl+F)")
        self.busqueda.setClearButtonEnabled(True)
        hb.addWidget(self.busqueda, 1)
        self._t_busqueda = QTimer(self, singleShot=True, interval=250)
        self._t_busqueda.timeout.connect(self.aplicar_busqueda)
        self.busqueda.textChanged.connect(lambda _: self._t_busqueda.start())

        # ---------- árbol ----------
        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setMinimumWidth(260)
        self.arbol.setIndentation(16)
        self.arbol.currentItemChanged.connect(self.cambio_filtro)

        # ---------- tabla ----------
        self.modelo = ModeloArticulos()
        self.tabla = QTableView()
        self.tabla.setModel(self.modelo)
        self.tabla.setSortingEnabled(True)
        self.tabla.sortByColumn(1, Qt.AscendingOrder)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(30)
        h = self.tabla.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        for col, ancho in ((0, 34), (2, 150), (3, 56), (4, 190), (5, 80)):
            h.resizeSection(col, ancho)
        h.setHighlightSections(False)
        self.tabla.selectionModel().currentRowChanged.connect(
            lambda ix, _p: ix.isValid() and self._mostrar(self.modelo.articulo(ix.row())))
        self.tabla.doubleClicked.connect(lambda ix: ix.column() != 0 and self.accion("pdf"))
        self.tabla.clicked.connect(self._clic_tabla)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self.menu_contextual)

        # ---------- portadas ----------
        self.portadas_modelo = ModeloPortadas(self.modelo, self.mini)
        self.portadas = QListView()
        self.portadas.setModel(self.portadas_modelo)
        self.portadas.setViewMode(QListView.IconMode)
        self.portadas.setIconSize(ModeloPortadas.ICONO)
        self.portadas.setGridSize(QSize(172, 252))
        self.portadas.setResizeMode(QListView.Adjust)
        self.portadas.setMovement(QListView.Static)
        self.portadas.setUniformItemSizes(True)
        self.portadas.setWordWrap(True)
        self.portadas.setSpacing(6)
        self.portadas.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.portadas.selectionModel().currentChanged.connect(
            lambda ix, _p: ix.isValid() and self._mostrar(self.modelo.articulo(ix.row())))
        self.portadas.doubleClicked.connect(lambda _: self.accion("pdf"))
        self.portadas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.portadas.customContextMenuRequested.connect(self.menu_contextual)
        self.vistas = QStackedWidget()
        self.vistas.addWidget(self.tabla)
        self.vistas.addWidget(self.portadas)

        # ---------- detalle ----------
        self.detalle = PanelDetalle()
        self.detalle.favorito.connect(lambda v: self.poner_favorito([self.detalle.articulo], v))
        self.detalle.estado.connect(lambda e: self.poner_estado([self.detalle.articulo], e))
        self.detalle.etiquetas.connect(self._etiquetas_detalle)
        self.detalle.nota.connect(self._nota_detalle)
        self.detalle.buscar.connect(self.busqueda.setText)
        self.detalle.accion.connect(self.accion)

        # ---------- estado vacío ----------
        self.vacio = QWidget()
        vl = QVBoxLayout(self.vacio)
        vl.addStretch(1)
        self.lbl_vacio = QLabel()
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        self.lbl_vacio.setWordWrap(True)
        b = QPushButton(tr("Elegir carpeta de la biblioteca"))
        b.setObjectName("primario")
        b.clicked.connect(self.elegir_biblioteca)
        vl.addWidget(self.lbl_vacio)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(b)
        fila.addStretch(1)
        vl.addLayout(fila)
        vl.addStretch(2)

        # ---------- vista previa (derecha) ----------
        self.previa = PanelVistaPrevia()
        self.previa.accion = self.accion
        self.previa.fuente_primera = lambda: (self.mini.png.get(self.previa.articulo["id_arxiv"], "")
                                              if self.previa.articulo else "")

        centro = QSplitter(Qt.Vertical)          # lista arriba, ficha abajo
        centro.addWidget(self.vistas)
        centro.addWidget(self.detalle)
        centro.setStretchFactor(0, 1)
        centro.setSizes([520, 330])
        centro.setHandleWidth(1)
        divisor = QSplitter(Qt.Horizontal)
        divisor.addWidget(self.arbol)
        divisor.addWidget(centro)
        divisor.addWidget(self.previa)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([280, 760, 440])
        divisor.setHandleWidth(1)
        self.divisores = (divisor, centro)
        for d, clave in ((divisor, "tam_horizontal"), (centro, "tam_vertical")):
            if self.cfg.get(clave):
                d.setSizes(self.cfg[clave])
        self.pila = QStackedWidget()
        self.pila.addWidget(divisor)
        self.pila.addWidget(self.vacio)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(barra)
        cl.addWidget(self.pila, 1)
        self.setCentralWidget(central)
        self.estado_barra = self.statusBar()

        self._crear_acciones()
        self._crear_barra_iconos()
        self._crear_menu()
        if self.cfg.get("vista") == "portadas":
            self.cambiar_vista(1)
        self.abrir_biblioteca(self.cfg.get("biblioteca", BIBLIOTECA_POR_DEFECTO))

    # ------------------------------------------------------------------ configuración
    def guardar_cfg(self):
        try:
            CONFIG.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def formato_nombre(self):
        return self.cfg.get("formato_nombre", FORMATO_NOMBRE)

    # ------------------------------------------------------------------ acciones, barra y menú
    def _nueva(self, clave, texto, fn, icono=None, atajo=None, ayuda=None, marcable=False):
        a = QAction(texto, self)
        a.setData(icono)
        if atajo:
            a.setShortcut(QKeySequence(atajo))
        if ayuda or atajo:
            a.setToolTip((ayuda or texto) + (f"  ({atajo})" if atajo else ""))
        a.setCheckable(marcable)
        a.triggered.connect(fn)
        self.acciones[clave] = a
        return a

    def _crear_acciones(self):
        self.acciones = {}
        n = self._nueva
        n("agregar", tr("Agregar"), self.agregar_por_codigo, "agregar", "Ctrl+N",
          tr("Agregar artículos por código de arXiv"))
        n("importar", tr("Importar PDFs"), self.importar_pdfs, "importar", "Ctrl+I",
          tr("Identificar PDFs (aunque no tengan el nombre de arXiv) e incorporarlos a la biblioteca"))
        n("monitor", tr("Monitor"), self.abrir_monitor, "monitor", "Ctrl+M",
          tr("Temas monitoreados y artículos nuevos en arXiv"))
        n("pdf", tr("Abrir"), lambda: self.accion("pdf"), "pdf", None, tr("Abrir el PDF (doble clic o Enter)"))
        n("favorito", tr("Favorito"), self.alternar_favorito, "favorito", "Ctrl+D", tr("Marcar o quitar favorito"))
        n("etiqueta", tr("Etiqueta"), self.agregar_etiqueta, "etiqueta", "Ctrl+T",
          tr("Agregar una etiqueta a los artículos seleccionados"))
        n("bibtex", "BibTeX", lambda: self.copiar_bibtex(), "bibtex", "Ctrl+B",
          tr("Copiar la referencia BibTeX de la selección"))
        n("versiones", tr("Versiones"), lambda: self.buscar_versiones(self.todos), "versiones", None,
          tr("Buscar versiones nuevas en arXiv"))
        n("palabras", tr("Palabras clave"), lambda: self.obtener_palabras([a for a in self.todos if not a["palabras"]]),
          "palabras", None, tr("Obtener palabras clave (del PDF y de OpenAlex) de los artículos que no tienen"))
        n("duplicados", tr("Duplicados"), self.buscar_duplicados, "duplicados", None,
          tr("Buscar duplicados y archivos sueltos"))
        n("lista", tr("Lista"), lambda: self.cambiar_vista(0), "lista", None, tr("Ver como lista"), True)
        n("portadas", tr("Portadas"), lambda: self.cambiar_vista(1), "portadas", None, tr("Ver portadas"), True)
        n("tema", tr("Tema"), self.alternar_tema, "luna", None, tr("Cambiar entre tema claro y oscuro"))
        n("recargar", tr("Recargar"), self.recargar, "recargar", "F5", tr("Volver a leer el catálogo"))
        grupo = QActionGroup(self)
        grupo.addAction(self.acciones["lista"])
        grupo.addAction(self.acciones["portadas"])
        self.acciones["lista"].setChecked(True)

    def _crear_barra_iconos(self):
        self.barra_iconos = QToolBar(tr("Barra de herramientas"))
        self.barra_iconos.setMovable(False)
        self.barra_iconos.setIconSize(QSize(24, 24))
        self.barra_iconos.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        grupos = [["agregar", "importar", "monitor"], ["pdf", "favorito", "etiqueta", "bibtex"],
                  ["versiones", "palabras", "duplicados"], ["lista", "portadas"], ["tema", "recargar"]]
        for i, g in enumerate(grupos):
            if i:
                self.barra_iconos.addSeparator()
            for clave in g:
                self.barra_iconos.addAction(self.acciones[clave])
        self.addToolBar(Qt.TopToolBarArea, self.barra_iconos)
        self.barra_iconos.setVisible(self.cfg.get("barra_iconos", True))
        self.recolorear_iconos()

    def recolorear_iconos(self):
        for clave, a in self.acciones.items():
            nombre = a.data()
            if clave == "tema":
                nombre = "sol" if tm.T["nombre"] == "oscuro" else "luna"
            if nombre:
                a.setIcon(tm.icono(nombre))

    def _crear_menu(self):
        A = self.acciones
        m = self.menuBar().addMenu(tr("&Biblioteca"))
        for c in ("agregar", "importar", "monitor"):
            m.addAction(A[c])
        m.addSeparator()
        self._item_menu(m, tr("Cambiar carpeta de la biblioteca…"), self.elegir_biblioteca)
        self._item_menu(m, tr("Abrir carpeta de la biblioteca"),
                        lambda: self.catalogo and abrir_archivo(self.catalogo.biblioteca))
        m.addAction(A["recargar"])
        self._item_menu(m, tr("Regenerar CSV del catálogo"), self.regenerar_csv)
        m.addSeparator()
        self._item_menu(m, tr("Salir"), self.close, "Ctrl+Q")

        m = self.menuBar().addMenu(tr("&Artículo"))
        m.addAction(A["pdf"])
        m.addAction(A["favorito"])
        sub = m.addMenu(tr("Estado de lectura"))
        for i, e in enumerate(ESTADOS):
            self._item_menu(sub, tr(e), lambda _=False, x=e: self.poner_estado(self.seleccionados(), x), f"Ctrl+{i + 1}")
        self._item_menu(sub, tr("Sin estado"), lambda: self.poner_estado(self.seleccionados(), ""), "Ctrl+0")
        m.addAction(A["etiqueta"])
        m.addSeparator()
        m.addAction(A["bibtex"])
        self._item_menu(m, tr("Exportar BibTeX de la selección…"), lambda: self.exportar_bibtex(False))
        self._item_menu(m, tr("Exportar BibTeX de la lista visible…"), lambda: self.exportar_bibtex(True))

        m = self.menuBar().addMenu(tr("&Herramientas"))
        for c in ("versiones", "palabras", "duplicados"):
            m.addAction(A[c])

        m = self.menuBar().addMenu(tr("&Ver"))
        m.addAction(A["lista"])
        m.addAction(A["portadas"])
        m.addSeparator()
        a = self._item_menu(m, tr("Barra de iconos"), lambda v: self._mostrar_barra(v))
        a.setCheckable(True)
        a.setChecked(self.barra_iconos.isVisible())
        sub = m.addMenu(tr("Tema"))
        g = QActionGroup(self)
        for clave, texto in (("oscuro", tr("Oscuro")), ("claro", tr("Claro"))):
            a = self._item_menu(sub, texto, lambda _=False, x=clave: self.poner_tema(x))
            a.setCheckable(True)
            a.setChecked(tm.T["nombre"] == clave)
            g.addAction(a)
        self.menu_tema = g
        sub = m.addMenu(tr("Idioma") + " / Language")
        g = QActionGroup(self)
        for clave, texto in (("es", "Español"), ("en", "English")):
            a = self._item_menu(sub, texto, lambda _=False, x=clave: self.poner_idioma(x))
            a.setCheckable(True)
            a.setChecked(("en" if en_ingles() else "es") == clave)
            g.addAction(a)

        m = self.menuBar().addMenu(tr("A&yuda"))
        self._item_menu(m, tr("Atajos de teclado"), self.ayuda)
        self._item_menu(m, tr("Acerca de"), lambda: QMessageBox.about(
            self, "Biblioteca arXiv", f"<b>Biblioteca arXiv</b> {VERSION}<br><br>" + tr("Catálogo: ") +
            f"{self.catalogo.ruta if self.catalogo else '—'}"))

        a = QAction(self, shortcut=QKeySequence("Ctrl+F"))
        a.triggered.connect(lambda: (self.busqueda.setFocus(), self.busqueda.selectAll()))
        self.addAction(a)
        for vista in (self.tabla, self.portadas):
            a = QAction(vista, shortcut=QKeySequence(Qt.Key_Return))
            a.triggered.connect(lambda: self.accion("pdf"))
            vista.addAction(a)

    def _item_menu(self, menu, texto, fn, atajo=None):
        a = QAction(texto, self)
        if atajo:
            a.setShortcut(QKeySequence(atajo))
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def _mostrar_barra(self, v):
        self.barra_iconos.setVisible(v)
        self.cfg["barra_iconos"] = v
        self.guardar_cfg()

    def ayuda(self):
        QMessageBox.information(self, tr("Atajos de teclado"), tr(
            "Doble clic / Enter: abrir PDF\nCtrl+F: buscar\nF5: recargar\n\n"
            "Ctrl+N: agregar por código\nCtrl+I: importar PDFs\nCtrl+M: monitor de temas\n\n"
            "Ctrl+D: favorito\nCtrl+1 / 2 / 3: Por leer / Leyendo / Leído\nCtrl+0: quitar estado\n"
            "Ctrl+T: agregar etiqueta a la selección\nCtrl+B: copiar BibTeX\n\n"
            "Ctrl o Mayús + clic: seleccionar varios artículos\n"
            "Clic en ☆ de la tabla: marcar favorito\nClic en una palabra clave: buscarla"))

    # ------------------------------------------------------------------ tema e idioma
    def poner_tema(self, nombre):
        tm.aplicar(QApplication.instance(), nombre)
        self.cfg["tema"] = nombre
        self.guardar_cfg()
        self.recolorear_iconos()
        for a in self.menu_tema.actions():
            a.setChecked(a.text() == (tr("Oscuro") if nombre == "oscuro" else tr("Claro")))
        self.portadas_modelo.recolorear()
        self._llenar_arbol()
        self.modelo.refrescar()
        if self.detalle.articulo:
            a = self.detalle.articulo
            self.detalle.articulo = None
            self._mostrar(a)

    def alternar_tema(self):
        self.poner_tema("claro" if tm.T["nombre"] == "oscuro" else "oscuro")

    def poner_idioma(self, codigo):
        if codigo == self.cfg.get("idioma", "es"):
            return
        self.cfg["idioma"] = codigo
        self.guardar_cfg()
        r = QMessageBox.question(
            self, "Idioma / Language",
            "El idioma se aplica al reiniciar la app. ¿Reiniciar ahora?\n\n"
            "The language is applied when the app restarts. Restart now?")
        if r == QMessageBox.Yes:
            self.detalle.guardar_nota()
            QProcess.startDetached(sys.executable, [str(APP_DIR / "app.py")])
            QApplication.instance().quit()

    # ------------------------------------------------------------------ menú contextual
    def menu_contextual(self, pos):
        sel = self.seleccionados()
        if not sel:
            return
        m = QMenu(self)
        n = f" ({len(sel)})" if len(sel) > 1 else ""
        if len(sel) == 1:
            self._item_menu(m, tr("Abrir PDF"), lambda: self.accion("pdf"))
            self._item_menu(m, tr("Ver en la web"), lambda: self.accion("arxiv"))
            self._item_menu(m, tr("Mostrar en carpeta"), lambda: self.accion("carpeta"))
            m.addSeparator()
        todos_fav = all(a["favorito"] for a in sel)
        self._item_menu(m, (tr("Quitar de favoritos") if todos_fav else tr("Marcar como favorito")) + n,
                        lambda: self.poner_favorito(sel, not todos_fav))
        sub = m.addMenu(tr("Estado de lectura") + n)
        for e in ESTADOS:
            self._item_menu(sub, tr(e), lambda _=False, x=e: self.poner_estado(sel, x))
        self._item_menu(sub, tr("Sin estado"), lambda: self.poner_estado(sel, ""))
        self._item_menu(m, tr("Agregar etiqueta…") + n, self.agregar_etiqueta)
        comunes = sorted(set.intersection(*(set(a["etiquetas"]) for a in sel)))
        if comunes:
            sub = m.addMenu(tr("Quitar etiqueta"))
            for e in comunes:
                self._item_menu(sub, e, lambda _=False, x=e: self.quitar_etiqueta(sel, x))
        m.addSeparator()
        self._item_menu(m, tr("Copiar BibTeX") + n, lambda: self.copiar_bibtex())
        self._item_menu(m, tr("Exportar BibTeX…") + n, lambda: self.exportar_bibtex(False))
        m.addSeparator()
        self._item_menu(m, tr("Buscar versión nueva") + n, lambda: self.buscar_versiones(sel))
        self._item_menu(m, tr("Obtener palabras clave") + n, lambda: self.obtener_palabras(sel))
        if len(sel) == 1:
            self._item_menu(m, tr("Regenerar vista previa"), lambda: self._regenerar_mini(sel[0]))
        m.exec(self.vistas.currentWidget().viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ biblioteca
    def elegir_biblioteca(self):
        actual = self.catalogo.biblioteca if self.catalogo else self.cfg.get("biblioteca", "")
        carpeta = QFileDialog.getExistingDirectory(self, tr("Carpeta de la biblioteca"), str(actual))
        if carpeta:
            self.abrir_biblioteca(carpeta)

    def abrir_biblioteca(self, carpeta):
        carpeta = Path(carpeta)
        if not (carpeta / NOMBRE_CATALOGO).exists():
            self.lbl_vacio.setText(tr("No encontré <b>{c}</b> en<br>{d}<br><br>Elige la carpeta de tu biblioteca "
                                      "(la que contiene el catálogo).", c=NOMBRE_CATALOGO, d=carpeta))
            self.pila.setCurrentWidget(self.vacio)
            return
        if self.catalogo:
            self.catalogo.cerrar()
        try:
            self.catalogo = Catalogo(carpeta)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("No se pudo abrir el catálogo"), str(e))
            return
        self.cfg["biblioteca"] = str(carpeta)
        self.guardar_cfg()
        self.mini.preparar(carpeta)
        self.setWindowTitle(f"Biblioteca arXiv — {carpeta}")
        self.pila.setCurrentIndex(0)
        self.recargar()
        self.actualizar_insignia()
        if self.cfg.get("monitor_al_abrir", True):
            QTimer.singleShot(1500, self.revisar_monitores_al_abrir)

    def recargar(self):
        if not self.catalogo:
            return
        actual = self.detalle.articulo["id_arxiv"] if self.detalle.articulo else None
        self.todos = self.catalogo.articulos()
        self.detalle.poner_sugerencias(self.catalogo.todas_etiquetas())
        self._llenar_arbol()
        self.aplicar_busqueda(actual)

    def regenerar_csv(self):
        if self.catalogo:
            self.catalogo.exportar_csv()
            self.estado_barra.showMessage(tr("CSV del catálogo regenerado"), 4000)

    # ------------------------------------------------------------------ árbol
    def _item(self, padre, texto, filtro, color=None, tooltip=None, negrita=False):
        it = QTreeWidgetItem([texto])
        it.setData(0, ROL_FILTRO, filtro)
        if color:
            it.setForeground(0, tm.color(color))
        if tooltip:
            it.setToolTip(0, tooltip)
        if negrita:
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        (self.arbol.addTopLevelItem(it) if padre is None else padre.addChild(it))
        return it

    def _seccion(self, texto):
        it = QTreeWidgetItem([texto.upper()])
        it.setFlags(Qt.ItemIsEnabled)
        it.setForeground(0, tm.color("seccion"))
        f = it.font(0)
        f.setPointSize(max(7, f.pointSize() - 1))
        it.setFont(0, f)
        self.arbol.addTopLevelItem(it)

    def _items_arbol(self):
        it = QTreeWidgetItemIterator(self.arbol)
        while it.value():
            yield it.value()
            it += 1

    def _llenar_arbol(self):
        previo = self.filtro
        expandidos = {it.data(0, ROL_FILTRO) for it in self._items_arbol() if it.isExpanded()}
        primera = not expandidos
        self.arbol.blockSignals(True)
        self.arbol.clear()
        raiz = self._item(None, tr("Biblioteca") + f"  ({len(self.todos)})", ("todo", None), negrita=True)
        areas = {}
        for a in self.todos:
            area = a["area"] or "?"
            areas.setdefault(area, {"nombre": nombre_area(area, a["area_es"]), "cats": {}})
            c = areas[area]["cats"].setdefault(a["categoria_principal"] or "?", {"nombre": nombre_cat(a), "n": 0})
            c["n"] += 1
        for area, info in sorted(areas.items(), key=lambda kv: (kv[0] == "otros", sin_tildes(kv[1]["nombre"]))):
            n = sum(c["n"] for c in info["cats"].values())
            it = self._item(raiz, f'{info["nombre"]}  ({n})', ("area", area), tooltip=f'{info["nombre"]}  ·  {area}')
            if area == "otros":
                continue
            for cat, c in sorted(info["cats"].items(), key=lambda kv: sin_tildes(kv[1]["nombre"])):
                self._item(it, f'{c["nombre"]}  ({c["n"]})', ("cat", cat), tooltip=f'{c["nombre"]}  ·  {cat}')

        self._seccion(tr("Colecciones"))
        self._item(None, "★  " + tr("Favoritos") + f"  ({sum(a['favorito'] for a in self.todos)})", ("fav", None),
                   color="dorado")
        for e in ESTADOS:
            n = sum(a["estado"] == e for a in self.todos)
            self._item(None, f"●  {tr(e)}  ({n})", ("estado", e), color=CLAVE_ESTADO[e])
        conteo = {}
        for a in self.todos:
            for e in a["etiquetas"]:
                conteo[e] = conteo.get(e, 0) + 1
        if conteo:
            self._seccion(tr("Etiquetas"))
            for e in sorted(conteo, key=sin_tildes):
                self._item(None, f"#  {e}  ({conteo[e]})", ("tag", e))
        nver = sum(bool(a["version_nueva"]) for a in self.todos)
        falt = sum(not a["existe"] for a in self.todos)
        nnov = self.catalogo.total_novedades() if self.catalogo else 0
        if nver or falt or nnov:
            self._seccion(tr("Avisos"))
            if nnov:
                self._item(None, "🔔  " + tr("Artículos nuevos en tus temas") + f"  ({nnov})", ("monitor", None),
                           color="leyendo")
            if nver:
                self._item(None, "⟳  " + tr("Versión nueva en arXiv") + f"  ({nver})", ("nueva", None), color="leyendo")
            if falt:
                self._item(None, "!  " + tr("PDF no encontrados") + f"  ({falt})", ("faltan", None), color="alerta")
        seleccionar = raiz
        for it in self._items_arbol():
            f = it.data(0, ROL_FILTRO)
            if f in expandidos or f == ("todo", None) or (primera and f and f[0] == "area"):
                it.setExpanded(True)
            if f == previo:
                seleccionar = it
        self.arbol.setCurrentItem(seleccionar)
        self.filtro = seleccionar.data(0, ROL_FILTRO)
        self.arbol.blockSignals(False)

    # ------------------------------------------------------------------ filtros y vistas
    def cambio_filtro(self, actual, _previo):
        if not actual or not actual.data(0, ROL_FILTRO):
            return
        if actual.data(0, ROL_FILTRO)[0] == "monitor":
            QTimer.singleShot(0, self.abrir_monitor)
            return
        self.filtro = actual.data(0, ROL_FILTRO)
        self.actualizar_vista()

    def aplicar_busqueda(self, mantener=None):
        texto = self.busqueda.text().strip()
        self.ids_busqueda = self.catalogo.buscar(texto, self.todos) if (self.catalogo and texto) else None
        self.actualizar_vista(mantener)

    def _filtradas(self):
        tipo, valor = self.filtro
        f = {"todo": lambda a: True, "area": lambda a: a["area"] == valor,
             "cat": lambda a: a["categoria_principal"] == valor, "fav": lambda a: a["favorito"],
             "estado": lambda a: a["estado"] == valor, "tag": lambda a: valor in a["etiquetas"],
             "nueva": lambda a: bool(a["version_nueva"]), "faltan": lambda a: not a["existe"]}.get(tipo, lambda a: True)
        filas = [a for a in self.todos if f(a)]
        if self.ids_busqueda is not None:
            filas = [a for a in filas if a["id_arxiv"] in self.ids_busqueda]
        return filas

    def actualizar_vista(self, mantener=None):
        if mantener is None and self.detalle.articulo:
            mantener = self.detalle.articulo["id_arxiv"]
        filas = self._filtradas()
        self.modelo.cargar(filas)
        fila = next((i for i, a in enumerate(self.modelo.filas) if a["id_arxiv"] == mantener), 0)
        if self.modelo.filas:
            self._seleccionar_fila(fila)
        else:
            self.detalle.mostrar(None)
            self.previa.mostrar(None, "")
        texto = tr("{t} artículos  ·  mostrando {n}", t=len(self.todos), n=len(filas))
        if self.ids_busqueda is not None:
            texto += "  ·  " + tr("búsqueda: «{q}»", q=self.busqueda.text().strip())
        self.estado_barra.showMessage(texto)

    def _seleccionar_fila(self, fila):
        if self.vistas.currentWidget() is self.tabla:
            self.tabla.selectRow(fila)
            self.tabla.scrollTo(self.modelo.index(fila, 1))
            self.tabla.setCurrentIndex(self.modelo.index(fila, 1))
        else:
            ix = self.portadas_modelo.index(fila)
            self.portadas.setCurrentIndex(ix)
            self.portadas.scrollTo(ix)
        self._mostrar(self.modelo.articulo(fila))

    def cambiar_vista(self, i):
        actual = self.detalle.articulo["id_arxiv"] if self.detalle.articulo else None
        self.vistas.setCurrentIndex(i)
        self.acciones["portadas" if i else "lista"].setChecked(True)
        self.cfg["vista"] = "portadas" if i == 1 else "lista"
        self.guardar_cfg()
        fila = next((k for k, a in enumerate(self.modelo.filas) if a["id_arxiv"] == actual), 0)
        if self.modelo.filas:
            self._seleccionar_fila(fila)

    def seleccionados(self):
        if self.vistas.currentWidget() is self.tabla:
            filas = sorted({ix.row() for ix in self.tabla.selectionModel().selectedRows()})
        else:
            filas = sorted({ix.row() for ix in self.portadas.selectionModel().selectedIndexes()})
        sel = [self.modelo.filas[f] for f in filas if f < len(self.modelo.filas)]
        if not sel and self.detalle.articulo:
            sel = [self.detalle.articulo]
        return sel

    def _clic_tabla(self, ix):
        if ix.column() == 0:
            a = self.modelo.articulo(ix.row())
            self.poner_favorito([a], not a["favorito"])

    def _mostrar(self, a):
        if a is self.detalle.articulo and a is not None:
            return
        self.detalle.mostrar(a)
        self.previa.mostrar(a, self.mini.pedir(a) if a else "")

    def _mini_lista(self, aid):
        if self.previa.articulo and self.previa.articulo["id_arxiv"] == aid and self.previa.pagina == 0:
            self.previa.poner_png(self.mini.png.get(aid, ""))

    def _regenerar_mini(self, a):
        self.mini.olvidar(a["id_arxiv"])
        self.previa.mostrar(a, self.mini.pedir(a))

    # ------------------------------------------------------------------ acciones del artículo
    def accion(self, cual):
        a = self.detalle.articulo
        if not a:
            return
        if cual == "pdf" and a["existe"]:
            abrir_archivo(a["ruta_archivo"])
        elif cual == "arxiv" and a["url_abs"]:
            QDesktopServices.openUrl(QUrl(a["url_abs"]))
        elif cual == "carpeta" and a["existe"]:
            mostrar_en_carpeta(a["ruta_archivo"])
        elif cual == "bibtex":
            self.copiar_bibtex([a])
        elif cual == "version":
            self.descargar_version_de([a])

    def _despues_de_cambio(self, afecta_filtro):
        self.detalle.guardar_nota()
        self._llenar_arbol()
        if afecta_filtro(self.filtro[0]):
            self.actualizar_vista()
        else:
            self.modelo.refrescar()
        if self.detalle.articulo:
            a = self.detalle.articulo
            self.detalle.articulo = None
            self._mostrar(a)

    def poner_favorito(self, sel, valor):
        sel = [a for a in sel if a]
        if not sel:
            return
        self.catalogo.poner_favorito([a["id_arxiv"] for a in sel], valor)
        for a in sel:
            a["favorito"] = bool(valor)
        self._despues_de_cambio(lambda t: t == "fav")

    def alternar_favorito(self):
        sel = self.seleccionados()
        if sel:
            self.poner_favorito(sel, not all(a["favorito"] for a in sel))

    def poner_estado(self, sel, estado):
        sel = [a for a in sel if a]
        if not sel:
            return
        self.catalogo.poner_estado([a["id_arxiv"] for a in sel], estado)
        for a in sel:
            a["estado"] = estado
        self._despues_de_cambio(lambda t: t == "estado")

    def _etiquetas_detalle(self, lista):
        a = self.detalle.articulo
        if a:
            self.catalogo.poner_etiquetas(a["id_arxiv"], lista)
            a["etiquetas"] = lista
            self.detalle.poner_sugerencias(self.catalogo.todas_etiquetas())
            self._despues_de_cambio(lambda t: t == "tag")

    def agregar_etiqueta(self):
        sel = self.seleccionados()
        if not sel:
            return
        etq, ok = QInputDialog.getItem(self, tr("Agregar etiqueta"), tr("Etiqueta para {n} artículo(s):", n=len(sel)),
                                       self.catalogo.todas_etiquetas(), 0, True)
        etq = etq.strip()
        if not ok or not etq:
            return
        self.catalogo.agregar_etiqueta([a["id_arxiv"] for a in sel], etq)
        for a in sel:
            if etq not in a["etiquetas"]:
                a["etiquetas"] = sorted(a["etiquetas"] + [etq], key=sin_tildes)
        self.detalle.poner_sugerencias(self.catalogo.todas_etiquetas())
        self._despues_de_cambio(lambda t: t == "tag")

    def quitar_etiqueta(self, sel, etq):
        self.catalogo.quitar_etiqueta([a["id_arxiv"] for a in sel], etq)
        for a in sel:
            a["etiquetas"] = [e for e in a["etiquetas"] if e != etq]
        self.detalle.poner_sugerencias(self.catalogo.todas_etiquetas())
        self._despues_de_cambio(lambda t: t == "tag")

    def _nota_detalle(self, texto):
        a = self.detalle.articulo
        if a:
            self.catalogo.poner_nota(a["id_arxiv"], texto)
            a["nota"] = texto
            self.estado_barra.showMessage(tr("Nota guardada"), 2000)

    # ------------------------------------------------------------------ BibTeX
    def copiar_bibtex(self, sel=None):
        sel = sel or self.seleccionados()
        if sel:
            QGuiApplication.clipboard().setText(bibtex.exportar(sel))
            self.estado_barra.showMessage(tr("BibTeX de {n} artículo(s) copiado al portapapeles", n=len(sel)), 4000)

    def exportar_bibtex(self, visibles):
        sel = self.modelo.filas if visibles else self.seleccionados()
        if not sel:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, tr("Exportar BibTeX"),
                                              str(Path.home() / "Documents" / "referencias.bib"), "BibTeX (*.bib)")
        if ruta:
            Path(ruta).write_text(bibtex.exportar(sel), encoding="utf-8")
            self.estado_barra.showMessage(tr("{n} referencias exportadas a {r}", n=len(sel), r=ruta), 6000)

    # ------------------------------------------------------------------ trabajos largos
    def correr(self, titulo, fn, al_terminar, padre=None, silencioso=False):
        t = Trabajo(fn)
        self._trabajos.append(t)
        prog = None
        if not silencioso:
            prog = QProgressDialog(titulo, tr("Cancelar"), 0, 100, padre or self)
            prog.setWindowTitle("Biblioteca arXiv")
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(0)
            prog.setMinimumWidth(440)
            prog.setValue(0)
            prog.canceled.connect(t.cancelar)

            def avance(i, n, texto):
                prog.setMaximum(max(n, 1))
                prog.setValue(min(i, max(n, 1)))
                prog.setLabelText(tr(texto))
            t.avance.connect(avance)
        else:
            t.avance.connect(lambda i, n, texto: self.estado_barra.showMessage(texto))

        def fin(res):
            if prog:
                prog.close()
            al_terminar(res)

        def error(msg):
            if prog:
                prog.close()
            if not silencioso:
                QMessageBox.warning(padre or self, tr("No se pudo completar"),
                                    msg.split("\n\n")[0] + "\n\n" + tr("Revisa tu conexión a internet e inténtalo de nuevo."))
        t.listo.connect(fin)
        t.fallo.connect(error)
        t.finished.connect(lambda: t in self._trabajos and self._trabajos.remove(t))
        t.start()

    def registrar_descargados(self, hechos):
        """Guarda en el catálogo los artículos recién descargados."""
        for aid, meta, ruta in hechos:
            self.catalogo.actualizar_articulo(aid, meta, ruta)
            if meta.get("palabras"):
                self.catalogo.guardar_palabras(aid, meta["palabras"], "OpenAlex")
        if hechos:
            self.catalogo.exportar_csv()
            self.recargar()
            self.estado_barra.showMessage(tr("{n} artículo(s) agregados a la biblioteca", n=len(hechos)), 6000)

    # ----- agregar por código -----
    def agregar_por_codigo(self):
        if not self.catalogo:
            return
        d = DialogoAgregar(self)
        if d.exec() != QDialog.Accepted or not d.texto.toPlainText().strip():
            return
        texto, ya = d.texto.toPlainText(), self.catalogo.ids_en_biblioteca()
        biblio, formato = self.catalogo.biblioteca, self.formato_nombre()

        def fin(res):
            self.registrar_descargados(res["descargados"])
            partes = [tr("{n} agregado(s).", n=len(res["descargados"]))]
            if res["ya_estaban"]:
                partes.append(tr("{n} ya estaban en la biblioteca.", n=len(res["ya_estaban"])))
            if res["no_existen"]:
                partes.append(tr("No existen en arXiv: {l}", l=", ".join(res["no_existen"])))
            QMessageBox.information(self, tr("Agregar artículos"), "\n".join(partes))
        self.correr(tr("Agregando artículos…"),
                    lambda av, ca: tareas.agregar_por_codigos(texto, ya, biblio, formato, av, ca), fin)

    # ----- identificar e importar PDFs -----
    def importar_pdfs(self):
        if not self.catalogo:
            return
        m = QMessageBox(self)
        m.setWindowTitle(tr("Importar PDFs"))
        m.setText(tr("¿Qué quieres importar?"))
        m.setInformativeText(tr("La app lee las dos primeras páginas de cada PDF para identificarlo "
                                "(sello o DOI de arXiv, DOI de revista o título) y lo busca en arXiv u OpenAlex."))
        b_arch = m.addButton(tr("Elegir archivos…"), QMessageBox.AcceptRole)
        b_carp = m.addButton(tr("Elegir una carpeta…"), QMessageBox.AcceptRole)
        m.addButton(tr("Cancelar"), QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_arch:
            rutas, _ = QFileDialog.getOpenFileNames(self, tr("PDFs a importar"), str(Path.home()), "PDF (*.pdf)")
        elif m.clickedButton() is b_carp:
            carpeta = QFileDialog.getExistingDirectory(self, tr("Carpeta con PDFs"), str(Path.home()))
            rutas = [str(p) for p in core.listar_pdfs([Path(carpeta)], True)] if carpeta else []
        else:
            return
        rutas = [r for r in rutas if not self._en_catalogo(r)]   # los ya catalogados no se tocan
        if not rutas:
            QMessageBox.information(self, tr("Importar PDFs"), tr("Esos PDFs ya están en el catálogo."))
            return
        self.correr(tr("Identificando {n} PDF(s)…", n=len(rutas)),
                    lambda av, ca: tareas.identificar_pdfs(rutas, av, ca), self._identificados)

    def _en_catalogo(self, ruta):
        import os
        r = os.path.normcase(os.path.abspath(ruta))
        return any(a["ruta_archivo"] and os.path.normcase(os.path.abspath(a["ruta_archivo"])) == r for a in self.todos)

    def _identificados(self, res):
        if not res:
            return
        existentes = {a["id_arxiv"]: a["existe"] for a in self.todos}
        d = DialogoIdentificados(self, res, existentes)
        if d.exec() != QDialog.Accepted:
            return
        mover = d.r_mover.isChecked()
        hechos, errores = [], []
        for r in d.elegidos():
            meta, aid = r["meta"], r["aid"]
            if existentes.get(aid):
                continue
            carpeta = self.catalogo.biblioteca.joinpath(*core.carpeta_categoria(meta["categoria"]))
            nombre = core.limpiar(self.formato_nombre().format(
                id=aid.replace("/", "_"), **{k: v for k, v in meta.items() if k != "id"})) + ".pdf"
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                destino = core.destino_libre(carpeta, nombre)
                (shutil.move if mover else shutil.copy2)(r["ruta"], destino)
                hechos.append((aid, meta, str(destino)))
            except OSError as e:
                errores.append(f"{Path(r['ruta']).name}: {e}")
        self.registrar_descargados(hechos)
        msg = tr("{n} PDF(s) incorporados a la biblioteca.", n=len(hechos))
        if errores:
            msg += "\n\n" + "\n".join(errores)
        QMessageBox.information(self, tr("Importar PDFs"), msg)

    # ----- monitoreo -----
    def abrir_monitor(self):
        if not self.catalogo:
            return
        DialogoMonitor(self).exec()
        self._llenar_arbol()
        self.actualizar_insignia()

    def actualizar_insignia(self):
        n = self.catalogo.total_novedades() if self.catalogo else 0
        a = self.acciones["monitor"]
        a.setText(tr("Monitor") + (f" ({n})" if n else ""))
        a.setIcon(tm.icono("monitor", "leyendo" if n else "icono"))

    def revisar_monitores_al_abrir(self):
        if not self.catalogo:
            return
        pendientes = [m for m in self.catalogo.monitores() if tareas.es_hora(m)]
        if not pendientes:
            return
        self.estado_barra.showMessage(tr("Revisando tus temas en arXiv…"))

        def fin(res):
            n = 0
            for m in pendientes:
                if m["id"] in res:
                    n += self.catalogo.guardar_novedades(m["id"], res[m["id"]])
                    self.catalogo.marcar_revisado(m["id"])
            self.actualizar_insignia()
            self._llenar_arbol()
            self.estado_barra.showMessage(tr("{n} artículo(s) nuevo(s) en tus temas. Abre el Monitor para verlos.", n=n)
                                          if n else tr("Tus temas están al día."), 8000)
        self.correr("", lambda av, ca: tareas.revisar_monitores(pendientes, av, ca), fin, silencioso=True)

    # ----- versiones, palabras, duplicados -----
    def buscar_versiones(self, articulos):
        lista = [a for a in articulos if tareas.es_arxiv(a["id_arxiv"])]
        if not lista:
            return

        def fin(pares):
            for a, m in pares:
                self.catalogo.guardar_version_nueva(a["id_arxiv"], a["version"], m["id_version"])
            if not pares:
                QMessageBox.information(self, tr("Versiones"), tr("Los {n} artículos revisados están al día.", n=len(lista)))
                self.recargar()
                return
            dlg = DialogoVersiones(self, pares)
            descargar = dlg.exec() == QDialog.Accepted and dlg.marcados()
            self.recargar()
            if descargar:
                self.correr(tr("Descargando {n} versiones nuevas…", n=len(descargar)),
                            lambda av, ca: tareas.descargar_versiones(descargar, av, ca), self._versiones_descargadas)
        self.correr(tr("Revisando {n} artículos en arXiv…", n=len(lista)),
                    lambda av, ca: tareas.buscar_versiones(lista, av, ca), fin)

    def descargar_version_de(self, articulos):
        ids = [a["id_arxiv"] for a in articulos]
        por_id = {a["id_arxiv"]: a for a in articulos}

        def fn(av, ca):
            av(0, 1, tr("Consultando arXiv…"))
            meta = core.consultar_arxiv(ids)
            return tareas.descargar_versiones([(por_id[k], m) for k, m in meta.items() if k in por_id], av, ca)
        self.correr(tr("Descargando versión nueva…"), fn, self._versiones_descargadas)

    def _versiones_descargadas(self, hechos):
        for aid, meta, ruta in hechos:
            self.catalogo.actualizar_articulo(aid, meta, ruta)
            self.catalogo.limpiar_version_nueva(aid)
            self.mini.olvidar(aid)
        if hechos:
            self.catalogo.exportar_csv()
        self.detalle.articulo = None
        self.recargar()
        self.estado_barra.showMessage(tr("{n} artículo(s) actualizados a su versión nueva", n=len(hechos)), 6000)

    def obtener_palabras(self, articulos):
        lista = list(articulos)
        if not lista:
            QMessageBox.information(self, tr("Palabras clave"), tr("Todos los artículos ya tienen palabras clave."))
            return

        def fin(res):
            n = 0
            for aid, fuentes in res.items():
                for fuente, palabras in fuentes.items():
                    if palabras:
                        self.catalogo.guardar_palabras(aid, palabras, fuente)
                n += any(fuentes.values())
            self.recargar()
            QMessageBox.information(self, tr("Palabras clave"),
                                    tr("Se encontraron palabras clave para {n} de {t} artículos.", n=n, t=len(lista)))
        self.correr(tr("Buscando palabras clave de {n} artículos…", n=len(lista)),
                    lambda av, ca: tareas.palabras_clave(lista, av, ca), fin)

    def buscar_duplicados(self):
        if not self.catalogo:
            return
        biblio, todos = self.catalogo.biblioteca, list(self.todos)

        def fin(res):
            if not res["titulos"] and not res["sueltos"]:
                QMessageBox.information(self, tr("Duplicados"), tr("No hay duplicados ni archivos sueltos en la biblioteca."))
                return
            dlg = DialogoDuplicados(self, res, biblio)
            dlg.exec()
            if dlg.movidos:
                self.recargar()
        self.correr(tr("Buscando duplicados…"), lambda av, ca: tareas.buscar_duplicados(biblio, todos, av, ca), fin)

    def closeEvent(self, e):
        self.detalle.guardar_nota()
        self.cfg["tam_horizontal"], self.cfg["tam_vertical"] = (d.sizes() for d in self.divisores)
        self.guardar_cfg()
        if self.catalogo:
            self.catalogo.cerrar()
        super().closeEvent(e)


# =============================================================================================
def instalar_registro_errores():
    def gancho(tipo, valor, tb):
        texto = "".join(traceback.format_exception(tipo, valor, tb))
        try:
            with open(APP_DIR / "errores.log", "a", encoding="utf-8") as fh:
                fh.write(texto + "\n")
        except OSError:
            pass
        if QApplication.instance():
            QMessageBox.critical(None, tr("Error inesperado"),
                                 f"{valor}\n\n" + tr("El detalle quedó en errores.log, en la carpeta de la app."))
    sys.excepthook = gancho


def main():
    instalar_registro_errores()
    cfg = leer_config()
    poner_idioma(cfg.get("idioma", "es"))
    app = QApplication(sys.argv)
    app.setApplicationName("Biblioteca arXiv")
    tm.aplicar(app, cfg.get("tema", "oscuro"))
    v = VentanaPrincipal()
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
