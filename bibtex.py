"""Genera entradas BibTeX para artículos de arXiv (formato recomendado por arXiv: @misc + eprint)."""
import re
import unicodedata

PALABRAS_VACIAS = {"a", "an", "the", "on", "of", "in", "for", "and", "to", "with", "from", "by",
                   "at", "is", "are", "towards", "toward", "via", "un", "una", "el", "la", "los",
                   "las", "de", "del", "en", "y", "para", "por", "con"}


def ascii_simple(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if ord(c) < 128)


def apellido(nombre):
    partes = nombre.split()
    if re.search(r"collaboration|consortium|team|group", nombre, re.I) and partes:
        return partes[0]
    return partes[-1] if partes else "Anon"


def autor_bibtex(nombre):
    """'Diederik P. Kingma' -> 'Kingma, Diederik P.'; colaboraciones van entre llaves."""
    nombre = " ".join(nombre.split())
    if not nombre:
        return ""
    if re.search(r"collaboration|consortium|team|group", nombre, re.I) or " " not in nombre:
        return "{" + nombre + "}"
    partes = nombre.split()
    # partículas que forman parte del apellido: van der Waals, de la Cruz
    i = len(partes) - 1
    while i > 1 and partes[i - 1].lower() in {"van", "von", "der", "de", "la", "del", "da", "di", "le"}:
        i -= 1
    return f"{' '.join(partes[i:])}, {' '.join(partes[:i])}"


def escapar(texto):
    texto = " ".join((texto or "").split())
    return re.sub(r"(?<!\\)([&%#])", r"\\\1", texto)


def clave(a, usadas):
    ap = re.sub(r"[^A-Za-z]", "", ascii_simple(apellido(a["primer_autor"] or ""))) or "Anon"
    palabras = [w for w in re.findall(r"[A-Za-z]+", ascii_simple(a["titulo"]))
                if w.lower() not in PALABRAS_VACIAS and w.lower() != ap.lower()]
    base = f"{ap}{a['anio'] or ''}{palabras[0].lower() if palabras else ''}"
    k, n = base, 0
    while k in usadas:
        n += 1
        k = base + "abcdefghijklmnopqrstuvwxyz"[n - 1] if n <= 26 else f"{base}{n}"
    usadas.add(k)
    return k


def entrada_otro(a, k, autores):
    """Artículo que no es de arXiv (identificado por DOI / OpenAlex)."""
    campos = [("title", "{" + escapar(a["titulo"]) + "}"), ("author", autores),
              ("year", str(a["anio"] or "")), ("journal", escapar(a.get("journal_ref") or "")),
              ("doi", a.get("doi") or ""), ("url", a.get("url_abs") or "")]
    cuerpo = ",\n".join(f"  {c:<13} = {{{v}}}" for c, v in campos if v)
    return f"@article{{{k},\n{cuerpo}\n}}"


def entrada(a, k):
    autores = " and ".join(autor_bibtex(n) for n in (a["autores"] or "").split("; ") if n.strip())
    if a["id_arxiv"].startswith(("doi:", "openalex:")):
        return entrada_otro(a, k, autores)
    campos = [("title", "{" + escapar(a["titulo"]) + "}"),
              ("author", autores),
              ("year", str(a["anio"] or "")),
              ("eprint", a["id_arxiv"]),
              ("archivePrefix", "arXiv"),
              ("primaryClass", a["categoria_principal"] or "")]
    if a.get("doi"):
        campos.append(("doi", a["doi"]))
    if a.get("journal_ref"):
        campos.append(("note", "Published in " + escapar(a["journal_ref"])))
    campos.append(("url", a["url_abs"] or f"https://arxiv.org/abs/{a['id_arxiv']}"))
    cuerpo = ",\n".join(f"  {c:<13} = {{{v}}}" for c, v in campos if v)
    return f"@misc{{{k},\n{cuerpo}\n}}"


def exportar(articulos):
    usadas = set()
    return "\n\n".join(entrada(a, clave(a, usadas)) for a in articulos) + "\n"
