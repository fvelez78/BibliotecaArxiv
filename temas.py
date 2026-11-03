"""Temas claro y oscuro (paleta, hoja de estilos y colores usados en el código) e iconos SVG
dibujados a mano (estilo de trazo, se recolorean según el tema)."""
from string import Template

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

OSCURO = dict(
    nombre="oscuro",
    fondo="#1b1c1f", barra="#232428", base="#16171a", alterna="#1f2024", panel="#202125",
    borde="#2f3136", borde2="#3a3c42", texto="#e6e6e6", texto2="#a6a8ae", texto3="#8b8e95",
    tenue="#7d7f86", boton="#2b2d31", boton_hover="#33363b", deshab="#6b6d73",
    acento="#3d6fd8", acento_hover="#4a7be3", acento_suave="#2a3550", seleccion="#2f4a80",
    seleccion_texto="#ffffff", hover="#24262b", link="#7aa7ff", icono="#c9cbd1",
    estrella_off="#4a4c52", dorado="#f2c94c", dorado_borde="#8a7330", dorado_fondo="#2e2a1d",
    aviso_fondo="#1e2b45", aviso_borde="#36589b", aviso_texto="#a9c4ff", aviso_hover="#24345a",
    alerta="#e5a54b", seccion="#7d8088",
    por_leer="#e5a54b", leyendo="#7aa7ff", leido="#6cc08b", mini_vacia="#26272b",
)

CLARO = dict(
    nombre="claro",
    fondo="#f7f7f8", barra="#eceef1", base="#ffffff", alterna="#f2f3f5", panel="#ffffff",
    borde="#d9dce1", borde2="#c6cad1", texto="#1f2328", texto2="#57606a", texto3="#6e7781",
    tenue="#9aa1aa", boton="#ffffff", boton_hover="#f0f2f5", deshab="#a8adb5",
    acento="#2f6bd8", acento_hover="#2559bb", acento_suave="#c9d6f2", seleccion="#d3e1fb",
    seleccion_texto="#0b2a66", hover="#eef1f5", link="#1f5fcf", icono="#3c434d",
    estrella_off="#c3c7ce", dorado="#c99a06", dorado_borde="#d9b54a", dorado_fondo="#fff6d6",
    aviso_fondo="#e8f0fe", aviso_borde="#9ab8f0", aviso_texto="#1d4fae", aviso_hover="#dbe7fd",
    alerta="#b26a00", seccion="#7a828c",
    por_leer="#b26a00", leyendo="#1f5fcf", leido="#1a7f37", mini_vacia="#eceef1",
)

TEMAS = {"oscuro": OSCURO, "claro": CLARO}
T = dict(OSCURO)          # tema activo (se modifica en su lugar al cambiar)


def color(clave):
    return QColor(T[clave])


def color_estado(estado):
    return QColor(T.get({"Por leer": "por_leer", "Leyendo": "leyendo", "Leído": "leido"}.get(estado, ""),
                        T["texto"]))


ESTILO = Template("""
QWidget { font-size: 10pt; color: $texto; }
QMainWindow, QStackedWidget, QDialog { background: $fondo; }
#barra { background: $barra; border-bottom: 1px solid $borde; }
QToolBar { background: $barra; border: none; border-bottom: 1px solid $borde; padding: 4px 8px; spacing: 2px; }
QToolBar QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px;
            padding: 4px 6px; color: $texto; min-width: 58px; }
QToolBar QToolButton:hover { background: $hover; border-color: $borde; }
QToolBar QToolButton:checked { background: $seleccion; color: $seleccion_texto; }
QToolBar::separator { background: $borde; width: 1px; margin: 6px 6px; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: $base; border: 1px solid $borde2;
            border-radius: 6px; padding: 6px 10px; color: $texto; selection-background-color: $acento;
            selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: $acento; }
QComboBox QAbstractItemView { background: $base; color: $texto; selection-background-color: $seleccion;
            selection-color: $seleccion_texto; }
QPushButton { background: $boton; border: 1px solid $borde2; border-radius: 6px; padding: 6px 12px; color: $texto; }
QPushButton:hover { background: $boton_hover; }
QPushButton:disabled { color: $deshab; border-color: $borde; }
QPushButton#primario { background: $acento; border-color: $acento; color: white; }
QPushButton#primario:hover { background: $acento_hover; }
QPushButton#primario:disabled { background: $acento_suave; border-color: $acento_suave; color: $deshab; }
QPushButton#favorito:checked { color: $dorado; border-color: $dorado_borde; background: $dorado_fondo; }
QPushButton#aviso { background: $aviso_fondo; border: 1px solid $aviso_borde; color: $aviso_texto; text-align: left; }
QPushButton#aviso:hover { background: $aviso_hover; }
QTreeWidget, QTableView, QListView, QTableWidget { background: $fondo; border: none; outline: 0; }
QTreeWidget::item { padding: 4px 2px; }
QTreeWidget::item:selected, QTableView::item:selected, QListView::item:selected, QTableWidget::item:selected {
            background: $seleccion; color: $seleccion_texto; }
QListView::item { border-radius: 6px; padding: 4px; }
QListView::item:hover { background: $hover; }
QTableView { alternate-background-color: $alterna; }
QTableView::item { padding: 0 6px; }
QHeaderView::section { background: $barra; color: $texto2; border: none; border-bottom: 1px solid $borde; padding: 6px 6px; }
QSplitter::handle { background: $borde; }
QScrollArea { background: $panel; }
QScrollArea > QWidget > QWidget { background: $panel; }
#miniatura { background: $base; border: 1px solid $borde; border-radius: 8px; color: $deshab; }
#secundario { color: $texto2; }
#etiqueta { color: $texto3; font-size: 9pt; }
#tarjeta { background: $panel; border: 1px solid $borde; border-radius: 8px; }
QStatusBar { background: $barra; color: $texto2; border-top: 1px solid $borde; }
QMenuBar { background: $barra; color: $texto; }
QMenuBar::item:selected, QMenu::item:selected { background: $seleccion; color: $seleccion_texto; }
QMenu { background: $base; color: $texto; border: 1px solid $borde2; padding: 4px; }
QMenu::item { padding: 5px 22px; }
QMenu::separator { height: 1px; background: $borde; margin: 4px 8px; }
QCheckBox, QRadioButton, QLabel { background: transparent; }
QCheckBox::indicator, QTableView::indicator, QTreeView::indicator, QListView::indicator {
            width: 15px; height: 15px; border: 1px solid $borde2; border-radius: 4px; background: $base; }
QCheckBox::indicator:checked, QTableView::indicator:checked, QTreeView::indicator:checked,
QListView::indicator:checked { background: $acento; border-color: $acento; image: url(CHECK); }
QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid $borde2; border-radius: 8px; background: $base; }
QRadioButton::indicator:checked { background: $acento; border: 3px solid $base; outline: 1px solid $acento; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: $borde2; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: $borde2; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QToolTip { background: $base; color: $texto; border: 1px solid $borde2; }
QProgressBar { background: $base; border: 1px solid $borde2; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: $acento; border-radius: 3px; }
""")


def aplicar(app, nombre):
    T.clear()
    T.update(TEMAS.get(nombre, OSCURO))
    app.setStyle("Fusion")
    p = QPalette()
    for rol, clave in ((QPalette.Window, "fondo"), (QPalette.Base, "base"), (QPalette.AlternateBase, "alterna"),
                       (QPalette.Button, "boton"), (QPalette.Highlight, "seleccion"), (QPalette.Link, "link"),
                       (QPalette.ToolTipBase, "base"), (QPalette.PlaceholderText, "deshab"),
                       (QPalette.WindowText, "texto"), (QPalette.Text, "texto"), (QPalette.ButtonText, "texto"),
                       (QPalette.ToolTipText, "texto"), (QPalette.HighlightedText, "seleccion_texto")):
        p.setColor(rol, QColor(T[clave]))
    app.setPalette(p)
    app.setStyleSheet(ESTILO.substitute(T).replace("url(CHECK)", f"url({_check_png()})"))


# ------------------------------------------------------------------------------------------ iconos
_TRAZOS = {
    "agregar": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    "importar": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M5 13V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2h-5.5"/>'
                '<path d="M2 19h7M6 16l3 3l-3 3"/>',
    "monitor": '<path d="M10 5a2 2 0 1 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3H4a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6"/>'
               '<path d="M9 17v1a3 3 0 0 0 6 0v-1"/>',
    "pdf": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>'
           '<path d="M9 13h6M9 17h4"/>',
    "favorito": '<path d="M12 17.75l-6.172 3.245l1.179-6.873l-5-4.867l6.9-1l3.086-6.253l3.086 6.253l6.9 1l-5 4.867'
                'l1.179 6.873z"/>',
    "etiqueta": '<circle cx="7.5" cy="7.5" r="1"/><path d="M3 6v5.172a2 2 0 0 0 .586 1.414l7.71 7.71a2.41 2.41 0 0 0'
                ' 3.408 0l5.592-5.592a2.41 2.41 0 0 0 0-3.408l-7.71-7.71A2 2 0 0 0 11.172 3H6a3 3 0 0 0-3 3z"/>',
    "bibtex": '<path d="M7 4a2 2 0 0 0-2 2v3a2 3 0 0 1-2 3a2 3 0 0 1 2 3v3a2 2 0 0 0 2 2"/>'
              '<path d="M17 4a2 2 0 0 1 2 2v3a2 3 0 0 0 2 3a2 3 0 0 0-2 3v3a2 2 0 0 1-2 2"/>',
    "versiones": '<path d="M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4"/><path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"/>',
    "palabras": '<circle cx="15" cy="15" r="4"/><path d="M18.5 18.5L21 21M4 6h13M4 12h4M4 18h4"/>',
    "duplicados": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8'
                  'a2 2 0 0 0 2 2h2"/>',
    "lista": '<path d="M9 6h11M9 12h11M9 18h11M5 6v.01M5 12v.01M5 18v.01"/>',
    "portadas": '<rect x="4" y="4" width="6" height="7" rx="1"/><rect x="14" y="4" width="6" height="7" rx="1"/>'
                '<rect x="4" y="14" width="6" height="7" rx="1"/><rect x="14" y="14" width="6" height="7" rx="1"/>',
    "sol": '<circle cx="12" cy="12" r="4"/><path d="M3 12h1m8-9v1m8 8h1m-9 8v1M5.6 5.6l.7.7m12.1-.7l-.7.7m0 11.4'
           'l.7.7m-12.1-.7l-.7.7"/>',
    "luna": '<path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1-8.313-12.454z"/>',
    "recargar": '<path d="M19.95 11a8 8 0 1 0-.5 4m.5 5v-5h-5"/>',
    "carpeta": '<path d="M5 4h4l3 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2"/>',
    "ordenar": '<path d="M4 4h16v6H4z"/><path d="M4 14h7v6H4zM15 14h5v6h-5z"/>',
}


def icono(nombre, clave_color="icono", relleno=False, tam=24):
    col = T.get(clave_color, clave_color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{col if relleno else "none"}" '
           f'stroke="{col}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
           f'{_TRAZOS[nombre]}</svg>')
    rend = QSvgRenderer(QByteArray(svg.encode()))
    ico = QIcon()
    for escala in (1, 2):
        pm = QPixmap(tam * escala, tam * escala)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        rend.render(p, QRectF(0, 0, tam * escala, tam * escala))
        p.end()
        pm.setDevicePixelRatio(escala)
        ico.addPixmap(pm)
    return ico


def _check_png():
    """Dibuja (una vez) la marca blanca de las casillas y devuelve su ruta para la hoja de estilos."""
    import tempfile
    from pathlib import Path
    ruta = Path(tempfile.gettempdir()) / "biblioteca_arxiv_check.png"
    if not ruta.exists():
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" '
               'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5l10 -10"/></svg>')
        rend = QSvgRenderer(QByteArray(svg.encode()))
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        rend.render(p, QRectF(2, 2, 28, 28))
        p.end()
        pm.save(str(ruta))
    return ruta.as_posix()
