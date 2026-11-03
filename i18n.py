"""Idioma de la interfaz. Los textos se escriben en español en el código y tr() los traduce
al inglés cuando corresponde. Las categorías de arXiv usan sus nombres originales en inglés."""
import renombrar_arxiv as core

IDIOMA = {"actual": "es"}


def poner_idioma(codigo):
    IDIOMA["actual"] = "en" if codigo == "en" else "es"


def en_ingles():
    return IDIOMA["actual"] == "en"


def tr(texto, **kw):
    if en_ingles():
        texto = EN.get(texto, texto)
    return texto.format(**kw) if kw else texto


def nombre_categoria(codigo, nombre_es=None):
    if en_ingles():
        return core.nombre_en(codigo) if codigo else ""
    return nombre_es or core.nombre_es(codigo)


def nombre_area(codigo, nombre_es=None):
    if en_ingles():
        return core.ARCHIVOS.get(codigo, codigo)
    return nombre_es or core.ARCHIVOS_ES.get(codigo, codigo)


EN = {}  # se completa en i18n_en.py

try:
    from i18n_en import EN as _EN
    EN.update(_EN)
except ImportError:
    pass
