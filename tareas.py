"""Trabajos largos (red o disco) que corren fuera de la interfaz: versiones nuevas, descarga de
versiones, palabras clave (PDF + OpenAlex) y búsqueda de duplicados.

Cada función recibe `avance(i, total, texto)` y `cancelado()` y devuelve su resultado; la interfaz
las corre en un hilo aparte (ver app.Trabajo). Ninguna toca la base: devuelven datos y la interfaz
los guarda, para que SQLite solo se use desde el hilo principal."""
import difflib
import json
import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import renombrar_arxiv as core
from i18n import tr

OPENALEX = "https://api.openalex.org/works"


def es_arxiv(aid):
    return not aid.startswith(("doi:", "openalex:"))


def num_version(v):
    m = re.search(r"v(\d+)$", v or "")
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------------- versiones nuevas
def buscar_versiones(articulos, avance, cancelado):
    """Devuelve [(articulo, meta_arxiv)] de los que tienen una versión más reciente en arXiv."""
    articulos = [a for a in articulos if es_arxiv(a["id_arxiv"])]
    ids = [a["id_arxiv"] for a in articulos]
    por_id = {a["id_arxiv"]: a for a in articulos}
    nuevas = []
    for i in range(0, len(ids), 50):
        if cancelado():
            break
        avance(i, len(ids), tr("Consultando arXiv ({a}–{b} de {n})", a=i + 1, b=min(i + 50, len(ids)), n=len(ids)))
        meta = core.consultar_arxiv(ids[i:i + 50])
        for aid, m in meta.items():
            a = por_id.get(aid)
            if a and num_version(m["id_version"]) > num_version(a["version"]):
                nuevas.append((a, m))
        if i + 50 < len(ids):
            time.sleep(3)
    avance(len(ids), len(ids), tr("Listo"))
    return nuevas


def descargar_versiones(pares, avance, cancelado):
    """Descarga la versión nueva sobre el mismo archivo. Devuelve [(aid, meta, ruta)] exitosos."""
    hechos = []
    for i, (a, m) in enumerate(pares):
        if cancelado():
            break
        avance(i, len(pares), tr("Descargando {v}", v=m["id_version"]))
        if i:
            time.sleep(3)
        pdf = core.obtener_bytes(m["url_pdf"].replace("http://", "https://", 1))
        if not pdf or not pdf.startswith(b"%PDF"):
            continue
        destino = Path(a["ruta_archivo"])
        tmp = destino.with_suffix(".part")
        tmp.write_bytes(pdf)
        tmp.replace(destino)
        hechos.append((a["id_arxiv"], m, str(destino)))
    avance(len(pares), len(pares), tr("Listo"))
    return hechos


# ------------------------------------------------------------------------- palabras clave
RE_MARCA = re.compile(r"(?:key\s*-?\s*words?|index\s+terms|palabras\s+clave)\s*[:.—–\-]\s*",
                      re.IGNORECASE)
RE_SELLO_ARXIV = re.compile(r"arXiv:\s*\S+\s*\[[^\]]+\]\s*\d{1,2}\s*[A-Za-z]{3}\s*\d{4}")
RE_FIN = re.compile(r"\n\s*\n|\n\s*(?:1\.?|I\.)\s+[A-Z]|\n\s*(?:Introduction|INTRODUCTION|Abstract)\b|"
                    r"\n\s*(?:PACS|MSC|AMS|JEL|Mathematics Subject)")


def palabras_del_pdf(ruta):
    """Busca la línea 'Keywords:' / 'Index Terms—' en las dos primeras páginas."""
    try:
        import pymupdf
        doc = pymupdf.open(ruta)
        texto = "\n".join(doc.load_page(i).get_text() for i in range(min(2, doc.page_count)))
        doc.close()
    except Exception:
        return []
    texto = RE_SELLO_ARXIV.sub("\n", texto)  # el sello del margen se cuela en el texto
    m = RE_MARCA.search(texto)
    if not m:
        return []
    resto = texto[m.end():m.end() + 500]
    f = RE_FIN.search(resto)
    if f:
        resto = resto[:f.start()]
    resto = re.sub(r"-\n(?=[a-z])", "", resto).replace("\n", " ")
    partes = [p.strip(" .;,·•") for p in re.split(r"[;,·•]|\s[–—]\s", resto)]
    return [p for p in partes if 2 <= len(p) <= 60][:12]


def _openalex(filtro, campos="doi,ids,keywords,primary_topic,title"):
    url = OPENALEX + "?" + urllib.parse.urlencode({"filter": filtro, "per-page": 50,
                                                    "select": campos})
    datos = core.obtener_bytes(url)
    if not datos:
        return []
    try:
        return json.loads(datos).get("results", [])
    except ValueError:
        return []


def _extraer(obra):
    kws = [k.get("display_name") for k in (obra.get("keywords") or []) if k.get("display_name")]
    tema = (obra.get("primary_topic") or {}).get("display_name")
    return kws, ([tema] if tema else [])


def palabras_clave(articulos, avance, cancelado):
    """Devuelve {aid: {'autor': [...], 'OpenAlex': [...], 'tema OpenAlex': [...]}}."""
    res = {a["id_arxiv"]: {} for a in articulos}
    total = len(articulos) * 2
    # 1) del propio PDF
    for i, a in enumerate(articulos):
        if cancelado():
            return res
        if i % 5 == 0:
            avance(i, total, tr("Leyendo PDFs ({i} de {n})", i=i + 1, n=len(articulos)))
        if a["existe"]:
            kw = palabras_del_pdf(a["ruta_archivo"])
            if kw:
                res[a["id_arxiv"]]["autor"] = kw
    # 2) OpenAlex por DOI de arXiv (10.48550/arXiv.<id>)
    pend = {f"10.48550/arxiv.{a['id_arxiv'].lower()}": a["id_arxiv"] for a in articulos
            if es_arxiv(a["id_arxiv"])}
    claves = list(pend)
    hechos = set()
    for i in range(0, len(claves), 50):
        if cancelado():
            return res
        avance(len(articulos) + i, total, tr("Consultando OpenAlex"))
        lote = claves[i:i + 50]
        for obra in _openalex("doi:" + "|".join(lote)):
            doi = (obra.get("doi") or "").lower().replace("https://doi.org/", "")
            aid = pend.get(doi)
            if aid:
                kws, tema = _extraer(obra)
                res[aid]["OpenAlex"], res[aid]["tema OpenAlex"] = kws, tema
                hechos.add(aid)
        time.sleep(0.2)
    # 3) los que no aparecieron: por DOI de revista, si lo tienen
    faltan = {a["doi"].lower(): a["id_arxiv"] for a in articulos
              if a["id_arxiv"] not in hechos and a.get("doi")}
    claves = list(faltan)
    for i in range(0, len(claves), 50):
        if cancelado():
            return res
        for obra in _openalex("doi:" + "|".join(claves[i:i + 50])):
            doi = (obra.get("doi") or "").lower().replace("https://doi.org/", "")
            aid = faltan.get(doi)
            if aid:
                kws, tema = _extraer(obra)
                res[aid]["OpenAlex"], res[aid]["tema OpenAlex"] = kws, tema
                hechos.add(aid)
        time.sleep(0.2)
    avance(total, total, tr("Listo"))
    return res


# ------------------------------------------------------------------------- duplicados
def normalizar_titulo(t):
    t = core.limpiar(t or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", core.unicodedata.normalize("NFKD", t)).strip()


def buscar_duplicados(biblioteca, articulos, avance, cancelado):
    """Devuelve dict con:
       'titulos': [[art, art, ...], ...]   artículos distintos con el mismo título
       'sueltos': [(ruta, id_o_None, art_del_catalogo_o_None)]  PDFs en la biblioteca que el
                  catálogo no referencia (copias sobrantes o archivos sin catalogar)."""
    grupos = {}
    for a in articulos:
        grupos.setdefault(normalizar_titulo(a["titulo"]), []).append(a)
    titulos = [g for g in grupos.values() if len(g) > 1]

    referenciados = {os.path.normcase(os.path.abspath(a["ruta_archivo"]))
                     for a in articulos if a["ruta_archivo"]}
    por_id = {a["id_arxiv"]: a for a in articulos}
    sueltos = []
    biblio = Path(biblioteca)
    archivos = [p for p in core.listar_pdfs([biblio], True)
                if ".miniaturas" not in p.parts and "_duplicados" not in p.parts]
    for i, p in enumerate(archivos):
        if cancelado():
            break
        if i % 50 == 0:
            avance(i, len(archivos), tr("Revisando archivos de la biblioteca"))
        if os.path.normcase(os.path.abspath(p)) in referenciados:
            continue
        aid = core.id_desde_nombre(p) or core.id_desde_pdf(p)
        sueltos.append((str(p), aid, por_id.get(aid)))
    avance(len(archivos), len(archivos), tr("Listo"))
    return {"titulos": titulos, "sueltos": sueltos}


# ------------------------------------------------------------------------- monitoreo de temas
def _lista(texto):
    return [p.strip() for p in re.split(r"[,\n;]", texto or "") if p.strip()]


def construir_consulta(m, desde=None, hasta=None):
    """Arma la consulta de la API de arXiv para un tema.
    palabras: se busca cada frase en título o resumen (cualquiera de ellas).
    categorias / autores: opcionales, restringen el resultado."""
    partes = []
    frases = []
    for f in _lista(m.get("palabras")):
        f = f.replace('"', "")
        q = f'"{f}"' if " " in f else f
        frases.append(f"ti:{q} OR abs:{q}")
    if frases:
        partes.append("(" + " OR ".join(frases) + ")")
    cats = [c for c in _lista(m.get("categorias"))]
    if cats:
        partes.append("(" + " OR ".join(f"cat:{c}" for c in cats) + ")")
    auts = [a.replace('"', "") for a in _lista(m.get("autores"))]
    if auts:
        partes.append("(" + " OR ".join(f'au:"{a}"' if " " in a else f"au:{a}" for a in auts) + ")")
    if desde:
        hasta = hasta or datetime.now()
        partes.append(f"submittedDate:[{desde:%Y%m%d}0000 TO {hasta:%Y%m%d}2359]")
    return " AND ".join(partes)


def es_hora(m, ahora=None):
    if not m.get("activo", 1):
        return False
    if not m.get("ultima_revision"):
        return True
    ahora = ahora or datetime.now()
    dias = {"diaria": 1, "semanal": 7}.get(m.get("frecuencia"), 7)
    return ahora - datetime.fromisoformat(m["ultima_revision"]) >= timedelta(days=dias, hours=-2)


def ventana_busqueda(m, ahora=None):
    """Desde cuándo buscar: un día antes de la última revisión (para no perder nada),
    o 14 días atrás si es la primera vez."""
    ahora = ahora or datetime.now()
    if m.get("ultima_revision"):
        return datetime.fromisoformat(m["ultima_revision"]) - timedelta(days=1)
    return ahora - timedelta(days=14)


def revisar_monitores(monitores, avance, cancelado, maximo=100):
    """Devuelve {monitor_id: [metadata, ...]} con los artículos que cumplen cada tema."""
    res = {}
    for i, m in enumerate(monitores):
        if cancelado():
            break
        avance(i, len(monitores), tr("Buscando «{t}» en arXiv", t=m["nombre"]))
        if i:
            time.sleep(3)
        consulta = construir_consulta(m, ventana_busqueda(m))
        res[m["id"]] = core.buscar_arxiv(consulta, maximo) if consulta else []
    avance(len(monitores), len(monitores), tr("Listo"))
    return res


# ------------------------------------------------------------------------- agregar por código
def descargar_a_biblioteca(metas, biblioteca, formato, avance, cancelado, niveles=2):
    """Descarga PDFs de arXiv a su carpeta por categoría. Devuelve [(aid, meta, ruta)]."""
    hechos = []
    for i, m in enumerate(metas):
        if cancelado():
            break
        avance(i, len(metas), tr("Descargando {v}  ({i} de {n})", v=m["id_version"], i=i + 1, n=len(metas)))
        if i:
            time.sleep(3)
        carpeta = Path(biblioteca).joinpath(*core.carpeta_categoria(m["categoria"], niveles))
        aid = m.get("id_arxiv") or re.sub(r"v\d+$", "", m["id_version"])
        nombre = core.limpiar(formato.format(id=aid.replace("/", "_"),
                                             **{k: v for k, v in m.items() if k != "id"})) + ".pdf"
        pdf = core.obtener_bytes(m["url_pdf"].replace("http://", "https://", 1))
        if not pdf or not pdf.startswith(b"%PDF"):
            continue
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = core.destino_libre(carpeta, nombre)
        tmp = destino.with_suffix(".part")
        tmp.write_bytes(pdf)
        tmp.replace(destino)
        hechos.append((aid, m, str(destino)))
    avance(len(metas), len(metas), tr("Listo"))
    return hechos


def agregar_por_codigos(texto, ya_estan, biblioteca, formato, avance, cancelado):
    """texto: códigos o enlaces de arXiv en cualquier formato. Devuelve dict con
    'descargados' [(aid, meta, ruta)], 'ya_estaban' [aid], 'no_existen' [aid]."""
    ids = core.leer_lista_ids([texto]) if texto else []
    pendientes = [i for i in ids if i not in ya_estan]
    avance(0, 1, tr("Consultando {n} códigos en arXiv", n=len(pendientes)))
    meta = core.consultar_arxiv(pendientes) if pendientes else {}
    metas = [dict(meta[i], id_arxiv=i) for i in pendientes if i in meta]
    hechos = descargar_a_biblioteca(metas, biblioteca, formato, avance, cancelado)
    return {"descargados": hechos, "ya_estaban": [i for i in ids if i in ya_estan],
            "no_existen": [i for i in pendientes if i not in meta]}


# ------------------------------------------------------------------------- identificar PDFs
RE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>()\[\]{}]+)", re.I)


def similitud(a, b):
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", (t or "").lower())).strip()  # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _texto_y_titulo(ruta):
    """Texto de las dos primeras páginas y el título probable (metadata o letra más grande)."""
    import pymupdf
    doc = pymupdf.open(ruta)
    texto = "\n".join(doc.load_page(i).get_text() for i in range(min(2, doc.page_count)))
    titulo = (doc.metadata or {}).get("title", "") or ""
    if len(titulo) < 15 or re.search(r"microsoft|untitled|\.docx?|\.tex|^title$|arxiv", titulo, re.I):
        titulo = ""
    if not titulo and doc.page_count:
        bloques = doc.load_page(0).get_text("dict")["blocks"]
        tramos = [(round(sp["size"], 1), sp["text"].strip(), ln["bbox"][1])
                  for b in bloques for ln in b.get("lines", []) for sp in ln["spans"]
                  if sp["text"].strip() and ln["bbox"][1] < doc.load_page(0).rect.height * 0.5]
        if tramos:
            mayor = max(t[0] for t in tramos)
            titulo = " ".join(t[1] for t in tramos if t[0] >= mayor - 0.5)
    doc.close()
    return texto, " ".join(titulo.split())[:300]


def _arxiv_en_openalex(obra):
    for loc in (obra.get("locations") or []) + [obra.get("primary_location") or {}]:
        for url in (loc.get("landing_page_url") or "", loc.get("pdf_url") or ""):
            m = re.search(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})", url, re.I)
            if m:
                return m.group(1)
    doi = (obra.get("doi") or "").lower()
    m = re.search(r"10\.48550/arxiv\.(.+)$", doi)
    return m.group(1) if m else None


def _resumen_openalex(indice):
    if not indice:
        return ""
    pos = sorted((p, w) for w, ps in indice.items() for p in ps)
    return " ".join(w for _, w in pos)


def meta_desde_openalex(obra):
    """Metadata en el formato del catálogo para un artículo que no es de arXiv."""
    doi = (obra.get("doi") or "").lower().replace("https://doi.org/", "")
    oid = (obra.get("id") or "").rsplit("/", 1)[-1]
    aid = f"doi:{doi}" if doi else f"openalex:{oid}"
    autores = []
    for au in obra.get("authorships") or []:
        nombre = (au.get("author") or {}).get("display_name") or ""
        inst = "; ".join(i.get("display_name", "") for i in au.get("institutions") or [] if i.get("display_name"))
        if nombre:
            autores.append((nombre, inst))
    apellido = autores[0][0].split()[-1] if autores else "SinAutor"
    if len(autores) > 1:
        apellido += " et al"
    fuente = ((obra.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    bib = obra.get("biblio") or {}
    ref = fuente
    if bib.get("volume"):
        ref += f" {bib['volume']}"
    if bib.get("first_page"):
        ref += f", {bib['first_page']}" + (f"-{bib['last_page']}" if bib.get("last_page") else "")
    if obra.get("publication_year"):
        ref += f" ({obra['publication_year']})"
    titulo = " ".join((obra.get("title") or obra.get("display_name") or "").split())
    return {
        "id_arxiv": aid, "titulo": titulo, "autor": apellido, "año": str(obra.get("publication_year") or ""),
        "categoria": core.CATEGORIA_OTROS, "id_version": aid,
        "resumen": _resumen_openalex(obra.get("abstract_inverted_index")), "autores": autores,
        "categorias": [core.CATEGORIA_OTROS], "publicado": obra.get("publication_date") or "",
        "actualizado": obra.get("updated_date") or "", "comentario": obra.get("type") or "",
        "journal_ref": ref.strip(), "doi": doi,
        "url_abs": f"https://doi.org/{doi}" if doi else (obra.get("id") or ""), "url_pdf": "",
        "palabras": [k.get("display_name") for k in obra.get("keywords") or [] if k.get("display_name")],
    }


def _openalex_get(url):
    datos = core.obtener_bytes(url)
    try:
        return json.loads(datos) if datos else None
    except ValueError:
        return None


def _openalex_por_doi(doi):
    return _openalex_get(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}")


def _openalex_por_titulo(titulo):
    r = _openalex_get(OPENALEX + "?" + urllib.parse.urlencode({"search": titulo, "per-page": 3}))
    mejor = max((r or {}).get("results", []), key=lambda o: similitud(o.get("title"), titulo), default=None)
    return mejor if mejor and similitud(mejor.get("title"), titulo) >= 0.9 else None


def _arxiv_por_titulo(titulo):
    limpio = re.sub(r"[^\w\s\-]", " ", titulo)
    for m in core.buscar_arxiv(f'ti:"{limpio}"', 5, orden="relevance"):
        if similitud(m["titulo"], titulo) >= 0.9:
            return m
    return None


def identificar_pdfs(rutas, avance, cancelado):
    """Intenta identificar cada PDF. Devuelve una lista de dicts:
       {ruta, metodo, aid, meta, tipo ('arxiv' | 'otro' | None), titulo_leido}."""
    res, pend_arxiv = [], {}
    for i, ruta in enumerate(rutas):
        if cancelado():
            break
        avance(i, len(rutas), tr("Leyendo {f}  ({i} de {n})", f=Path(ruta).name[:60], i=i + 1, n=len(rutas)))
        r = {"ruta": str(ruta), "metodo": "", "aid": None, "meta": None, "tipo": None, "titulo_leido": ""}
        res.append(r)
        aid = core.id_desde_nombre(Path(ruta))
        if aid:
            r.update(metodo="nombre del archivo", aid=aid, tipo="arxiv")
        else:
            aid = core.id_desde_pdf(Path(ruta))
            if aid:
                r.update(metodo="sello de arXiv en el PDF", aid=aid, tipo="arxiv")
        if not r["aid"]:
            try:
                texto, titulo = _texto_y_titulo(ruta)
            except Exception:
                r["metodo"] = "no se pudo leer el PDF"
                continue
            r["titulo_leido"] = titulo
            doi = None
            m = RE_DOI.search(texto)
            if m:
                doi = m.group(1).rstrip(".,;:").lower()
            if doi and doi.startswith("10.48550/arxiv."):
                r.update(metodo="DOI de arXiv en el PDF", aid=doi.split("arxiv.", 1)[1], tipo="arxiv")
            elif doi:
                obra = _openalex_por_doi(doi)
                if obra:
                    ax = _arxiv_en_openalex(obra)
                    if ax:
                        r.update(metodo="DOI → OpenAlex → arXiv", aid=ax, tipo="arxiv")
                    else:
                        meta = meta_desde_openalex(obra)
                        r.update(metodo="DOI → OpenAlex", aid=meta["id_arxiv"], meta=meta, tipo="otro")
                time.sleep(0.2)
            if not r["aid"] and titulo:
                m = _arxiv_por_titulo(titulo)
                time.sleep(3)
                if m:
                    r.update(metodo="título → arXiv", aid=m["id_arxiv"], meta=m, tipo="arxiv")
                else:
                    obra = _openalex_por_titulo(titulo)
                    if obra:
                        ax = _arxiv_en_openalex(obra)
                        if ax:
                            r.update(metodo="título → OpenAlex → arXiv", aid=ax, tipo="arxiv")
                        else:
                            meta = meta_desde_openalex(obra)
                            r.update(metodo="título → OpenAlex", aid=meta["id_arxiv"], meta=meta, tipo="otro")
            if not r["aid"]:
                r["metodo"] = "no identificado"
        if r["tipo"] == "arxiv" and not r["meta"]:
            pend_arxiv.setdefault(r["aid"], []).append(r)
    if pend_arxiv and not cancelado():
        avance(len(rutas), len(rutas) + 1, tr("Consultando metadata en arXiv"))
        meta = core.consultar_arxiv(list(pend_arxiv))
        for aid, rs in pend_arxiv.items():
            for r in rs:
                if aid in meta:
                    r["meta"] = dict(meta[aid], id_arxiv=aid)
                else:
                    r.update(tipo=None, metodo=r["metodo"] + " (pero no existe en arXiv)")
    avance(1, 1, tr("Listo"))
    return res
