#!/usr/bin/env python3
r"""
renombrar_arxiv.py — Busca, renombra y clasifica por categoría los PDFs descargados de arXiv.

Uso básico (una carpeta, renombra en el sitio):
    python renombrar_arxiv.py CARPETA                  # simulación: solo muestra qué haría
    python renombrar_arxiv.py CARPETA --aplicar        # renombra de verdad

Biblioteca clasificada (mueve cada artículo a  BIBLIOTECA\Área (código)\subcat - Nombre\):
    python renombrar_arxiv.py C:\Users\PC_FAVR D:\ E:\ --recursivo --biblioteca D:\Biblioteca_arXiv
    python renombrar_arxiv.py C:\Users\PC_FAVR D:\ E:\ --recursivo --biblioteca D:\Biblioteca_arXiv --aplicar
    Ejemplo de destino:  D:\Biblioteca_arXiv\Computer Science (cs)\cs.LG - Machine Learning\...pdf

Catálogo de metadata (se crea/actualiza solo al usar --biblioteca ... --aplicar):
    BIBLIOTECA\catalogo_arxiv.sqlite  -> base para consultas SQL (tablas: articulos, autores,
                                         categorias y busqueda = texto completo título/resumen/autores)
    BIBLIOTECA\catalogo_arxiv.csv     -> la tabla 'articulos' para Excel (separador ';')
    Para catalogar lo que YA está en la biblioteca (no mueve ni renombra nada):
    python renombrar_arxiv.py --reconstruir-catalogo --biblioteca D:\Biblioteca_arXiv

Descargar desde un listado de códigos (a la biblioteca, clasificados y catalogados):
    python renombrar_arxiv.py --biblioteca D:\Biblioteca_arXiv --descargar 1706.03762 2410.05229
    python renombrar_arxiv.py --biblioteca D:\Biblioteca_arXiv --descargar lista.txt --aplicar
    (el listado puede tener un código por línea, URLs de arXiv o venir en un CSV; los que ya
     están en el catálogo se omiten)

Actualizar la base a la versión nueva y regenerar el CSV (sin consultar arXiv):
    python renombrar_arxiv.py --exportar-csv --biblioteca D:\Biblioteca_arXiv

Opciones:
    --catalogo RUTA Usar otra ubicación para la base SQLite.
    --copiar       Con --biblioteca: copia en vez de mover (los originales quedan intactos).
    --niveles 1     Solo carpeta de área (Computer Science (cs)), sin subcategoría.
    --formato "{año} - {autor} - {titulo}"   Campos: {titulo} {autor} {año} {id} {categoria}
    --leer-pdf      Busca además el sello de arXiv dentro del PDF (pip install pypdf). Más lento.
    --inventario archivo.csv   Lista de lo encontrado (ruta, ID, categoría, autor, año, título).

Seguridad:
  * Por nombre, solo reconoce archivos cuyo nombre ES el ID de arXiv (2410.12345v2.pdf,
    2410.12345v2 (1).pdf, hep-th_9901001.pdf, arXiv_2410.12345.pdf). "Factura 2023.1234.pdf" no se toca.
  * Con --leer-pdf solo acepta el sello del margen, no IDs citados en el texto.
  * Nunca sobrescribe ni borra. Si un artículo ya está en la biblioteca, el duplicado se deja
    donde estaba y se reporta. Registro de cambios en 'renombrados_arxiv.csv'.
  * Lo que ya está dentro de la biblioteca no se vuelve a procesar.
"""
import argparse
import csv
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}

ID_NUEVO = r"\d{4}\.\d{4,5}"
ID_ANTIGUO = r"[a-z\-]+(?:\.[A-Z]{2})?[_/]\d{7}"
RE_NOMBRE = re.compile(
    rf"^(?:arxiv[ _\-:]?)?({ID_NUEVO}|{ID_ANTIGUO})(?:v\d+)?(?:\s*\(\d+\))?$", re.I)
RE_SELLO = re.compile(
    rf"arXiv:\s*({ID_NUEVO}|{ID_ANTIGUO})(?:v\d+)?\s*\[[^\]]+\]\s*\d{{1,2}}\s*[A-Za-z]{{3}}\s*\d{{4}}",
    re.I)

NS_ARXIV = {"x": "http://arxiv.org/schemas/atom"}

# --- Taxonomía de arXiv para nombrar carpetas ---------------------------------------------
ARCHIVOS = {
    "cs": "Computer Science", "stat": "Statistics", "math": "Mathematics",
    "astro-ph": "Astrophysics", "physics": "Physics", "cond-mat": "Condensed Matter",
    "eess": "Electrical Engineering and Systems Science", "q-bio": "Quantitative Biology",
    "q-fin": "Quantitative Finance", "econ": "Economics", "nlin": "Nonlinear Sciences",
    "hep": "High Energy Physics", "nucl": "Nuclear Physics",
    "gr-qc": "General Relativity and Quantum Cosmology", "quant-ph": "Quantum Physics",
    "math-ph": "Mathematical Physics",
}
SUBCATEGORIAS = {
    # Computer Science
    "cs.AI": "Artificial Intelligence", "cs.AR": "Hardware Architecture",
    "cs.CC": "Computational Complexity", "cs.CE": "Computational Engineering, Finance, and Science",
    "cs.CG": "Computational Geometry", "cs.CL": "Computation and Language",
    "cs.CR": "Cryptography and Security", "cs.CV": "Computer Vision and Pattern Recognition",
    "cs.CY": "Computers and Society", "cs.DB": "Databases",
    "cs.DC": "Distributed, Parallel, and Cluster Computing", "cs.DL": "Digital Libraries",
    "cs.DM": "Discrete Mathematics", "cs.DS": "Data Structures and Algorithms",
    "cs.ET": "Emerging Technologies", "cs.FL": "Formal Languages and Automata Theory",
    "cs.GL": "General Literature", "cs.GR": "Graphics", "cs.GT": "Computer Science and Game Theory",
    "cs.HC": "Human-Computer Interaction", "cs.IR": "Information Retrieval",
    "cs.IT": "Information Theory", "cs.LG": "Machine Learning", "cs.LO": "Logic in Computer Science",
    "cs.MA": "Multiagent Systems", "cs.MM": "Multimedia", "cs.MS": "Mathematical Software",
    "cs.NA": "Numerical Analysis", "cs.NE": "Neural and Evolutionary Computing",
    "cs.NI": "Networking and Internet Architecture", "cs.OH": "Other Computer Science",
    "cs.OS": "Operating Systems", "cs.PF": "Performance", "cs.PL": "Programming Languages",
    "cs.RO": "Robotics", "cs.SC": "Symbolic Computation", "cs.SD": "Sound",
    "cs.SE": "Software Engineering", "cs.SI": "Social and Information Networks",
    "cs.SY": "Systems and Control",
    # Statistics
    "stat.AP": "Applications", "stat.CO": "Computation", "stat.ME": "Methodology",
    "stat.ML": "Machine Learning", "stat.OT": "Other Statistics", "stat.TH": "Statistics Theory",
    # Astrophysics
    "astro-ph.CO": "Cosmology and Nongalactic Astrophysics",
    "astro-ph.EP": "Earth and Planetary Astrophysics", "astro-ph.GA": "Astrophysics of Galaxies",
    "astro-ph.HE": "High Energy Astrophysical Phenomena",
    "astro-ph.IM": "Instrumentation and Methods for Astrophysics",
    "astro-ph.SR": "Solar and Stellar Astrophysics",
    # EESS
    "eess.AS": "Audio and Speech Processing", "eess.IV": "Image and Video Processing",
    "eess.SP": "Signal Processing", "eess.SY": "Systems and Control",
    # Mathematics
    "math.AC": "Commutative Algebra", "math.AG": "Algebraic Geometry", "math.AP": "Analysis of PDEs",
    "math.AT": "Algebraic Topology", "math.CA": "Classical Analysis and ODEs",
    "math.CO": "Combinatorics", "math.CT": "Category Theory", "math.CV": "Complex Variables",
    "math.DG": "Differential Geometry", "math.DS": "Dynamical Systems",
    "math.FA": "Functional Analysis", "math.GM": "General Mathematics", "math.GN": "General Topology",
    "math.GR": "Group Theory", "math.GT": "Geometric Topology", "math.HO": "History and Overview",
    "math.IT": "Information Theory", "math.KT": "K-Theory and Homology", "math.LO": "Logic",
    "math.MG": "Metric Geometry", "math.MP": "Mathematical Physics", "math.NA": "Numerical Analysis",
    "math.NT": "Number Theory", "math.OA": "Operator Algebras", "math.OC": "Optimization and Control",
    "math.PR": "Probability", "math.QA": "Quantum Algebra", "math.RA": "Rings and Algebras",
    "math.RT": "Representation Theory", "math.SG": "Symplectic Geometry",
    "math.SP": "Spectral Theory", "math.ST": "Statistics Theory",
    # Physics
    "physics.acc-ph": "Accelerator Physics", "physics.ao-ph": "Atmospheric and Oceanic Physics",
    "physics.app-ph": "Applied Physics", "physics.atm-clus": "Atomic and Molecular Clusters",
    "physics.atom-ph": "Atomic Physics", "physics.bio-ph": "Biological Physics",
    "physics.chem-ph": "Chemical Physics", "physics.class-ph": "Classical Physics",
    "physics.comp-ph": "Computational Physics",
    "physics.data-an": "Data Analysis, Statistics and Probability",
    "physics.ed-ph": "Physics Education", "physics.flu-dyn": "Fluid Dynamics",
    "physics.gen-ph": "General Physics", "physics.geo-ph": "Geophysics",
    "physics.hist-ph": "History and Philosophy of Physics",
    "physics.ins-det": "Instrumentation and Detectors", "physics.med-ph": "Medical Physics",
    "physics.optics": "Optics", "physics.plasm-ph": "Plasma Physics",
    "physics.pop-ph": "Popular Physics", "physics.soc-ph": "Physics and Society",
    "physics.space-ph": "Space Physics",
    # Condensed Matter
    "cond-mat.dis-nn": "Disordered Systems and Neural Networks",
    "cond-mat.mes-hall": "Mesoscale and Nanoscale Physics", "cond-mat.mtrl-sci": "Materials Science",
    "cond-mat.other": "Other Condensed Matter", "cond-mat.quant-gas": "Quantum Gases",
    "cond-mat.soft": "Soft Condensed Matter", "cond-mat.stat-mech": "Statistical Mechanics",
    "cond-mat.str-el": "Strongly Correlated Electrons", "cond-mat.supr-con": "Superconductivity",
    # Quantitative Biology
    "q-bio.BM": "Biomolecules", "q-bio.CB": "Cell Behavior", "q-bio.GN": "Genomics",
    "q-bio.MN": "Molecular Networks", "q-bio.NC": "Neurons and Cognition",
    "q-bio.OT": "Other Quantitative Biology", "q-bio.PE": "Populations and Evolution",
    "q-bio.QM": "Quantitative Methods", "q-bio.SC": "Subcellular Processes",
    "q-bio.TO": "Tissues and Organs",
    # Quantitative Finance
    "q-fin.CP": "Computational Finance", "q-fin.EC": "Economics", "q-fin.GN": "General Finance",
    "q-fin.MF": "Mathematical Finance", "q-fin.PM": "Portfolio Management",
    "q-fin.PR": "Pricing of Securities", "q-fin.RM": "Risk Management",
    "q-fin.ST": "Statistical Finance", "q-fin.TR": "Trading and Market Microstructure",
    # Economics
    "econ.EM": "Econometrics", "econ.GN": "General Economics", "econ.TH": "Theoretical Economics",
    # Nonlinear Sciences
    "nlin.AO": "Adaptation and Self-Organizing Systems", "nlin.CD": "Chaotic Dynamics",
    "nlin.CG": "Cellular Automata and Lattice Gases",
    "nlin.PS": "Pattern Formation and Solitons",
    "nlin.SI": "Exactly Solvable and Integrable Systems",
    # Archivos sin subdivisión con punto
    "hep-th": "Theory", "hep-ph": "Phenomenology", "hep-ex": "Experiment", "hep-lat": "Lattice",
    "nucl-th": "Theory", "nucl-ex": "Experiment",
}


ARCHIVOS_ES = {
    "cs": "Ciencias de la Computación", "stat": "Estadística", "math": "Matemáticas",
    "astro-ph": "Astrofísica", "physics": "Física", "cond-mat": "Materia Condensada",
    "eess": "Ingeniería Eléctrica y Ciencias de Sistemas", "q-bio": "Biología Cuantitativa",
    "q-fin": "Finanzas Cuantitativas", "econ": "Economía", "nlin": "Ciencias No Lineales",
    "hep": "Física de Altas Energías", "nucl": "Física Nuclear",
    "gr-qc": "Relatividad General y Cosmología Cuántica", "quant-ph": "Física Cuántica",
    "math-ph": "Física Matemática",
}
SUBCAT_ES = {
    # Ciencias de la Computación
    "cs.AI": "Inteligencia Artificial", "cs.AR": "Arquitectura de Hardware",
    "cs.CC": "Complejidad Computacional", "cs.CE": "Ingeniería, Finanzas y Ciencia Computacional",
    "cs.CG": "Geometría Computacional", "cs.CL": "Computación y Lenguaje (PLN)",
    "cs.CR": "Criptografía y Seguridad", "cs.CV": "Visión por Computador y Reconocimiento de Patrones",
    "cs.CY": "Computación y Sociedad", "cs.DB": "Bases de Datos",
    "cs.DC": "Computación Distribuida, Paralela y en Clúster", "cs.DL": "Bibliotecas Digitales",
    "cs.DM": "Matemáticas Discretas", "cs.DS": "Estructuras de Datos y Algoritmos",
    "cs.ET": "Tecnologías Emergentes", "cs.FL": "Lenguajes Formales y Teoría de Autómatas",
    "cs.GL": "Literatura General", "cs.GR": "Gráficos por Computador",
    "cs.GT": "Teoría de Juegos en Computación", "cs.HC": "Interacción Humano-Computador",
    "cs.IR": "Recuperación de Información", "cs.IT": "Teoría de la Información",
    "cs.LG": "Aprendizaje Automático", "cs.LO": "Lógica en Computación",
    "cs.MA": "Sistemas Multiagente", "cs.MM": "Multimedia", "cs.MS": "Software Matemático",
    "cs.NA": "Análisis Numérico", "cs.NE": "Computación Neuronal y Evolutiva",
    "cs.NI": "Redes y Arquitectura de Internet", "cs.OH": "Otras Ciencias de la Computación",
    "cs.OS": "Sistemas Operativos", "cs.PF": "Rendimiento", "cs.PL": "Lenguajes de Programación",
    "cs.RO": "Robótica", "cs.SC": "Computación Simbólica", "cs.SD": "Sonido",
    "cs.SE": "Ingeniería de Software", "cs.SI": "Redes Sociales y de Información",
    "cs.SY": "Sistemas y Control",
    # Estadística
    "stat.AP": "Aplicaciones", "stat.CO": "Estadística Computacional", "stat.ME": "Metodología",
    "stat.ML": "Aprendizaje Automático (Estadística)", "stat.OT": "Otros Temas de Estadística",
    "stat.TH": "Teoría Estadística",
    # Astrofísica
    "astro-ph.CO": "Cosmología y Astrofísica Extragaláctica",
    "astro-ph.EP": "Astrofísica Terrestre y Planetaria", "astro-ph.GA": "Astrofísica de Galaxias",
    "astro-ph.HE": "Fenómenos Astrofísicos de Altas Energías",
    "astro-ph.IM": "Instrumentación y Métodos para Astrofísica",
    "astro-ph.SR": "Astrofísica Solar y Estelar",
    # Ingeniería Eléctrica
    "eess.AS": "Procesamiento de Audio y Voz", "eess.IV": "Procesamiento de Imagen y Video",
    "eess.SP": "Procesamiento de Señales", "eess.SY": "Sistemas y Control",
    # Matemáticas
    "math.AC": "Álgebra Conmutativa", "math.AG": "Geometría Algebraica",
    "math.AP": "Análisis de EDP", "math.AT": "Topología Algebraica",
    "math.CA": "Análisis Clásico y EDO", "math.CO": "Combinatoria", "math.CT": "Teoría de Categorías",
    "math.CV": "Variable Compleja", "math.DG": "Geometría Diferencial",
    "math.DS": "Sistemas Dinámicos", "math.FA": "Análisis Funcional",
    "math.GM": "Matemáticas Generales", "math.GN": "Topología General",
    "math.GR": "Teoría de Grupos", "math.GT": "Topología Geométrica",
    "math.HO": "Historia y Panorama", "math.IT": "Teoría de la Información",
    "math.KT": "K-Teoría y Homología", "math.LO": "Lógica", "math.MG": "Geometría Métrica",
    "math.MP": "Física Matemática", "math.NA": "Análisis Numérico", "math.NT": "Teoría de Números",
    "math.OA": "Álgebras de Operadores", "math.OC": "Optimización y Control",
    "math.PR": "Probabilidad", "math.QA": "Álgebra Cuántica", "math.RA": "Anillos y Álgebras",
    "math.RT": "Teoría de Representaciones", "math.SG": "Geometría Simpléctica",
    "math.SP": "Teoría Espectral", "math.ST": "Teoría Estadística",
    # Física
    "physics.acc-ph": "Física de Aceleradores", "physics.ao-ph": "Física Atmosférica y Oceánica",
    "physics.app-ph": "Física Aplicada", "physics.atm-clus": "Cúmulos Atómicos y Moleculares",
    "physics.atom-ph": "Física Atómica", "physics.bio-ph": "Biofísica",
    "physics.chem-ph": "Física Química", "physics.class-ph": "Física Clásica",
    "physics.comp-ph": "Física Computacional",
    "physics.data-an": "Análisis de Datos, Estadística y Probabilidad",
    "physics.ed-ph": "Enseñanza de la Física", "physics.flu-dyn": "Dinámica de Fluidos",
    "physics.gen-ph": "Física General", "physics.geo-ph": "Geofísica",
    "physics.hist-ph": "Historia y Filosofía de la Física",
    "physics.ins-det": "Instrumentación y Detectores", "physics.med-ph": "Física Médica",
    "physics.optics": "Óptica", "physics.plasm-ph": "Física de Plasmas",
    "physics.pop-ph": "Divulgación de la Física", "physics.soc-ph": "Física y Sociedad",
    "physics.space-ph": "Física Espacial",
    # Materia Condensada
    "cond-mat.dis-nn": "Sistemas Desordenados y Redes Neuronales",
    "cond-mat.mes-hall": "Física Mesoscópica y Nanoescala", "cond-mat.mtrl-sci": "Ciencia de Materiales",
    "cond-mat.other": "Otros Temas de Materia Condensada", "cond-mat.quant-gas": "Gases Cuánticos",
    "cond-mat.soft": "Materia Condensada Blanda", "cond-mat.stat-mech": "Mecánica Estadística",
    "cond-mat.str-el": "Electrones Fuertemente Correlacionados", "cond-mat.supr-con": "Superconductividad",
    # Biología Cuantitativa
    "q-bio.BM": "Biomoléculas", "q-bio.CB": "Comportamiento Celular", "q-bio.GN": "Genómica",
    "q-bio.MN": "Redes Moleculares", "q-bio.NC": "Neuronas y Cognición",
    "q-bio.OT": "Otros Temas de Biología Cuantitativa", "q-bio.PE": "Poblaciones y Evolución",
    "q-bio.QM": "Métodos Cuantitativos", "q-bio.SC": "Procesos Subcelulares",
    "q-bio.TO": "Tejidos y Órganos",
    # Finanzas Cuantitativas
    "q-fin.CP": "Finanzas Computacionales", "q-fin.EC": "Economía", "q-fin.GN": "Finanzas Generales",
    "q-fin.MF": "Finanzas Matemáticas", "q-fin.PM": "Gestión de Portafolios",
    "q-fin.PR": "Valoración de Activos", "q-fin.RM": "Gestión de Riesgos",
    "q-fin.ST": "Finanzas Estadísticas", "q-fin.TR": "Trading y Microestructura de Mercado",
    # Economía
    "econ.EM": "Econometría", "econ.GN": "Economía General", "econ.TH": "Teoría Económica",
    # Ciencias No Lineales
    "nlin.AO": "Sistemas Adaptativos y Autoorganizados", "nlin.CD": "Dinámica Caótica",
    "nlin.CG": "Autómatas Celulares y Gases en Red", "nlin.PS": "Formación de Patrones y Solitones",
    "nlin.SI": "Sistemas Exactamente Solubles e Integrables",
    # Archivos sin subdivisión
    "hep-th": "Física de Altas Energías – Teoría", "hep-ph": "Física de Altas Energías – Fenomenología",
    "hep-ex": "Física de Altas Energías – Experimental", "hep-lat": "Física de Altas Energías – Red (Lattice)",
    "nucl-th": "Física Nuclear – Teoría", "nucl-ex": "Física Nuclear – Experimental",
    "gr-qc": "Relatividad General y Cosmología Cuántica", "quant-ph": "Física Cuántica",
    "math-ph": "Física Matemática",
}


CATEGORIA_OTROS = "otros"   # artículos que no son de arXiv (identificados por DOI/OpenAlex)
ARCHIVOS["otros"] = "Other (not arXiv)"
ARCHIVOS_ES["otros"] = "Otros (no arXiv)"


def nombre_en(cat):
    """'cs.LG' -> 'Machine Learning' (nombres originales de arXiv)."""
    if cat in ("hep-th", "hep-ph", "hep-ex", "hep-lat", "nucl-th", "nucl-ex"):
        return f"{ARCHIVOS[cat.split('-')[0]]} – {SUBCATEGORIAS[cat]}"
    return SUBCATEGORIAS.get(cat) or ARCHIVOS.get(cat) or cat


def area_de(cat):
    if not cat:
        return ""
    if "." in cat:
        return cat.split(".")[0]
    if cat.startswith(("hep-", "nucl-")):
        return cat.split("-")[0]
    return cat


def nombre_es(cat):
    """'cs.LG' -> 'Aprendizaje Automático'; si no está en la tabla, devuelve el código."""
    return SUBCAT_ES.get(cat) or ARCHIVOS_ES.get(cat) or cat


def carpeta_categoria(cat, niveles=2):
    """'cs.LG' -> ['Computer Science (cs)', 'cs.LG - Machine Learning']"""
    if not cat:
        return ["Sin categoría"]
    if cat == CATEGORIA_OTROS:
        return [ARCHIVOS_ES[CATEGORIA_OTROS]]
    if "." in cat:
        archivo = cat.split(".")[0]
    elif cat.startswith(("hep-", "nucl-")):
        archivo = cat.split("-")[0]
    else:
        archivo = cat
    nivel1 = f"{ARCHIVOS[archivo]} ({archivo})" if archivo in ARCHIVOS else archivo
    if niveles == 1 or archivo == cat:
        return [limpiar(nivel1)]
    nombre = SUBCATEGORIAS.get(cat)
    nivel2 = f"{cat} - {nombre}" if nombre else cat
    return [limpiar(nivel1), limpiar(nivel2)]


CARPETAS_OMITIDAS = {"$recycle.bin", "system volume information", "windows", "program files",
                     "program files (x86)", "programdata", "appdata", "node_modules", ".git",
                     "site-packages", "__pycache__"}


def normalizar_id(aid):
    return aid.replace("_", "/") if not re.match(ID_NUEVO, aid) else aid


def id_desde_nombre(ruta):
    m = RE_NOMBRE.match(ruta.stem.strip())
    return normalizar_id(m.group(1)) if m else None


def id_desde_pdf(ruta):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        texto = PdfReader(str(ruta)).pages[0].extract_text() or ""
    except Exception:
        return None
    m = RE_SELLO.search(texto)
    return normalizar_id(m.group(1)) if m else None


def listar_pdfs(raices, recursivo):
    for raiz in raices:
        raiz = Path(raiz)
        if raiz.is_file() and raiz.suffix.lower() == ".pdf":
            yield raiz
            continue
        if not recursivo:
            yield from (p for p in raiz.glob("*") if p.suffix.lower() == ".pdf" and p.is_file())
            continue
        for dirpath, dirnames, filenames in os.walk(raiz, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in CARPETAS_OMITIDAS and not d.startswith(".")]
            for f in filenames:
                if f.lower().endswith(".pdf"):
                    yield Path(dirpath) / f


def descargar(url, intentos=6):
    """Consulta la API y devuelve el XML parseado (o None si arXiv no responde)."""
    datos = obtener_bytes(url, intentos)
    return ET.fromstring(datos) if datos is not None else None


def obtener_bytes(url, intentos=6):
    """Pide la URL reintentando ante 503/429/errores de red (arXiv los da con frecuencia)."""
    espera = 5
    motivo = ""
    for i in range(1, intentos + 1):
        for base in (url, url.replace("https://", "http://", 1)):
            try:
                req = urllib.request.Request(base, headers={"User-Agent": "renombrar_arxiv/1.2"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code not in (429, 500, 502, 503, 504):
                    raise
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.isdigit():
                    espera = max(espera, int(ra))
                motivo = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError) as e:
                motivo = str(getattr(e, "reason", e))
        if i < intentos:
            print(f"   arXiv ocupado ({motivo}). Reintento {i}/{intentos - 1} en {espera} s...")
            time.sleep(espera)
            espera = min(espera * 2, 60)
    return None


def parsear_entradas(raiz):
    """Convierte la respuesta Atom de la API de arXiv en {id_sin_version: metadata}."""
    resultados = {}
    for e in raiz.findall("a:entry", NS):
        id_url = e.findtext("a:id", "", NS)
        titulo = e.findtext("a:title", "", NS)
        if not titulo or "/abs/" not in id_url or titulo.strip().lower() == "error":
            continue
        id_version = id_url.split("/abs/")[1]
        aid = re.sub(r"v\d+$", "", id_version)
        autores = []
        for a in e.findall("a:author", NS):
            afil = "; ".join(x.text.strip() for x in a.findall("x:affiliation", NS_ARXIV) if x.text)
            autores.append((" ".join(a.findtext("a:name", "", NS).split()), afil))
        apellido = autores[0][0].split()[-1] if autores else "SinAutor"
        if len(autores) > 1:
            apellido += " et al"
        categorias = [c.get("term", "") for c in e.findall("a:category", NS) if c.get("term")]
        pc = e.find("x:primary_category", NS_ARXIV)
        cat = pc.get("term", "") if pc is not None else ""
        if not cat and categorias:
            cat = categorias[0]
        url_pdf = next((l.get("href") for l in e.findall("a:link", NS)
                        if l.get("title") == "pdf"), "")
        texto = lambda tag, ns=NS_ARXIV, e=e: " ".join((e.findtext(tag, "", ns) or "").split())
        resultados[aid] = {
            "titulo": " ".join(titulo.split()),
            "autor": apellido,
            "año": e.findtext("a:published", "", NS)[:4],
            "categoria": cat,
            # --- metadata completa para el catálogo ---
            "id_version": id_version,
            "resumen": texto("a:summary", NS),
            "autores": autores,
            "categorias": categorias,
            "publicado": e.findtext("a:published", "", NS),
            "actualizado": e.findtext("a:updated", "", NS),
            "comentario": texto("x:comment"),
            "journal_ref": texto("x:journal_ref"),
            "doi": texto("x:doi"),
            "url_abs": f"https://arxiv.org/abs/{aid}",
            "url_pdf": url_pdf or f"https://arxiv.org/pdf/{id_version}",
        }
    return resultados


def consultar_arxiv(ids):
    """Devuelve {id_sin_version: metadata} para una lista de IDs."""
    resultados = {}
    lotes = [ids[i:i + 50] for i in range(0, len(ids), 50)]
    for n, lote in enumerate(lotes):
        if n:
            time.sleep(3)  # pausa recomendada por arXiv
        if len(lotes) > 1:
            print(f"   lote {n + 1}/{len(lotes)}")
        url = API + "?" + urllib.parse.urlencode(
            {"id_list": ",".join(lote), "max_results": len(lote)})
        raiz = descargar(url)
        if raiz is None:
            print(f"[aviso] arXiv no respondió para el lote {n + 1}; esos archivos se omiten.")
            continue
        resultados.update(parsear_entradas(raiz))
    return resultados


def buscar_arxiv(consulta, maximo=50, orden="submittedDate"):
    """Búsqueda libre en arXiv (sintaxis de la API: ti:, abs:, au:, cat:, AND, OR...).
    Devuelve una lista de metadata, en el orden que da arXiv (más recientes primero)."""
    url = API + "?" + urllib.parse.urlencode(
        {"search_query": consulta, "start": 0, "max_results": maximo,
         "sortBy": orden, "sortOrder": "descending"})
    raiz = descargar(url)
    if raiz is None:
        return []
    return [dict(m, id_arxiv=k) for k, m in parsear_entradas(raiz).items()]


# --- Catálogo SQLite ------------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE IF NOT EXISTS articulos (
    id_arxiv            TEXT PRIMARY KEY,   -- 2410.05229 / hep-th/9711200
    version             TEXT,               -- 2410.05229v2
    titulo              TEXT,
    resumen             TEXT,               -- abstract
    autores             TEXT,               -- 'Nombre 1; Nombre 2; ...'
    primer_autor        TEXT,
    n_autores           INTEGER,
    anio                INTEGER,            -- año de la primera versión
    publicado           TEXT,               -- fecha v1 (ISO)
    actualizado         TEXT,               -- fecha última versión (ISO)
    categoria_principal TEXT,               -- cs.LG
    area                TEXT,               -- cs
    categorias          TEXT,               -- 'cs.LG; stat.ML'
    area_es             TEXT,               -- 'Ciencias de la Computación'
    categoria_es        TEXT,               -- 'Aprendizaje Automático'
    categorias_es       TEXT,               -- 'Aprendizaje Automático; Aprendizaje Automático (Estadística)'
    comentario          TEXT,               -- p.ej. '12 pages, accepted at NeurIPS'
    journal_ref         TEXT,               -- revista donde se publicó, si el autor lo indicó
    doi                 TEXT,
    url_abs             TEXT,
    url_pdf             TEXT,
    ruta_archivo        TEXT,               -- dónde está el PDF en tu disco
    nombre_archivo      TEXT,
    fecha_catalogado    TEXT
);
CREATE TABLE IF NOT EXISTS autores (
    id_arxiv   TEXT,
    orden      INTEGER,
    nombre     TEXT,
    afiliacion TEXT,
    PRIMARY KEY (id_arxiv, orden)
);
CREATE TABLE IF NOT EXISTS categorias (
    id_arxiv  TEXT,
    categoria TEXT,
    principal INTEGER,
    nombre_es TEXT,
    PRIMARY KEY (id_arxiv, categoria)
);
CREATE INDEX IF NOT EXISTS ix_aut_nombre ON autores(nombre);
CREATE INDEX IF NOT EXISTS ix_cat ON categorias(categoria);
"""


def abrir_catalogo(ruta):
    import sqlite3
    con = sqlite3.connect(str(ruta))
    con.executescript(ESQUEMA)
    migrar_catalogo(con)
    try:  # búsqueda de texto completo (título, resumen, autores), insensible a tildes
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS busqueda USING fts5("
                    "id_arxiv UNINDEXED, titulo, resumen, autores, "
                    "tokenize='unicode61 remove_diacritics 2')")
    except Exception:
        pass  # SQLite sin FTS5: el resto funciona igual
    return con


def migrar_catalogo(con):
    """Agrega columnas nuevas a catálogos creados con versiones anteriores y las completa."""
    for tabla, cols in (("articulos", ("area_es", "categoria_es", "categorias_es")),
                        ("categorias", ("nombre_es",))):
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}
        for c in cols:
            if c not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {c} TEXT")
    filas = con.execute("SELECT id_arxiv, categoria_principal, area, categorias FROM articulos "
                        "WHERE categoria_es IS NULL OR area_es IS NULL").fetchall()
    for aid, cat, area, cats in filas:
        lista = [c.strip() for c in (cats or "").split(";") if c.strip()]
        con.execute("UPDATE articulos SET area=?, area_es=?, categoria_es=?, categorias_es=? "
                    "WHERE id_arxiv=?", (area_de(cat), nombre_es(area_de(cat)), nombre_es(cat),
                                         "; ".join(nombre_es(c) for c in lista), aid))
    for cat, in con.execute("SELECT DISTINCT categoria FROM categorias WHERE nombre_es IS NULL").fetchall():
        con.execute("UPDATE categorias SET nombre_es=? WHERE categoria=?", (nombre_es(cat), cat))
    con.commit()


def guardar_en_catalogo(con, aid, d, ruta_pdf):
    from datetime import datetime
    nombres = [n for n, _ in d["autores"]]
    area = area_de(d["categoria"])
    fila = {
        "id_arxiv": aid, "version": d["id_version"], "titulo": d["titulo"], "resumen": d["resumen"],
        "autores": "; ".join(nombres), "primer_autor": nombres[0] if nombres else "",
        "n_autores": len(nombres), "anio": int(d["año"]) if d["año"] else None,
        "publicado": d["publicado"], "actualizado": d["actualizado"],
        "categoria_principal": d["categoria"], "area": area, "categorias": "; ".join(d["categorias"]),
        "area_es": nombre_es(area), "categoria_es": nombre_es(d["categoria"]),
        "categorias_es": "; ".join(nombre_es(c) for c in d["categorias"]),
        "comentario": d["comentario"], "journal_ref": d["journal_ref"], "doi": d["doi"],
        "url_abs": d["url_abs"], "url_pdf": d["url_pdf"], "ruta_archivo": str(ruta_pdf),
        "nombre_archivo": Path(ruta_pdf).name,
        "fecha_catalogado": datetime.now().isoformat(timespec="seconds"),
    }
    con.execute(f"INSERT OR REPLACE INTO articulos ({', '.join(fila)}) "
                f"VALUES ({', '.join('?' * len(fila))})", list(fila.values()))
    con.execute("DELETE FROM autores WHERE id_arxiv=?", (aid,))
    con.executemany("INSERT INTO autores VALUES (?,?,?,?)",
                    [(aid, i + 1, n, a) for i, (n, a) in enumerate(d["autores"])])
    con.execute("DELETE FROM categorias WHERE id_arxiv=?", (aid,))
    con.executemany("INSERT OR IGNORE INTO categorias (id_arxiv, categoria, principal, nombre_es) "
                    "VALUES (?,?,?,?)",
                    [(aid, c, int(c == d["categoria"]), nombre_es(c)) for c in d["categorias"]])
    try:
        con.execute("DELETE FROM busqueda WHERE id_arxiv=?", (aid,))
        con.execute("INSERT INTO busqueda VALUES (?,?,?,?)",
                    (aid, d["titulo"], d["resumen"], "; ".join(nombres)))
    except Exception:
        pass


def exportar_csv(con, ruta_csv):
    """CSV separado por ';' (lo abre bien Excel en español) con codificación UTF-8 con BOM."""
    cur = con.execute(
        "SELECT id_arxiv, titulo, primer_autor, autores, n_autores, anio, area_es, categoria_es, "
        "categorias_es, area, categoria_principal, categorias, resumen, comentario, journal_ref, doi, "
        "publicado, actualizado, version, url_abs, url_pdf, ruta_archivo, nombre_archivo, "
        "fecha_catalogado FROM articulos ORDER BY area_es, categoria_es, anio DESC, titulo")
    cols = [c[0] for c in cur.description]
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols)
        w.writerows(cur)


def ids_desde_registro(biblio):
    """Lee renombrados_arxiv.csv: ruta nueva -> ID (sacado del nombre original del archivo)."""
    mapa = {}
    log = biblio / "renombrados_arxiv.csv"
    if not log.exists():
        return mapa
    with open(log, encoding="utf-8-sig", newline="") as fh:
        for fila in csv.reader(fh):
            viejo, nuevo = (fila[1], fila[2]) if len(fila) >= 3 else (fila[0], fila[1]) if len(fila) == 2 else (None, None)
            if viejo:
                aid = id_desde_nombre(Path(viejo))
                if aid:
                    mapa[os.path.normcase(os.path.abspath(nuevo))] = aid
    return mapa


def limpiar(nombre, max_len=180):
    nombre = unicodedata.normalize("NFC", nombre)
    nombre = re.sub(r"\$([^$]*)\$", r"\1", nombre)          # quita $...$ de LaTeX
    nombre = re.sub(r"\\[a-zA-Z]+\s*", "", nombre)           # quita comandos \alpha, \mathrm
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f{}^]', "", nombre)  # caracteres prohibidos
    nombre = re.sub(r"\s+", " ", nombre).strip(" .")
    return nombre[:max_len].rstrip(" .")


def destino_libre(carpeta, nombre):
    destino = carpeta / nombre
    k = 2
    while destino.exists():
        destino = carpeta / f"{Path(nombre).stem} ({k}).pdf"
        k += 1
    return destino


def main():
    p = argparse.ArgumentParser(description="Busca, renombra y clasifica PDFs de arXiv.")
    p.add_argument("carpetas", nargs="*", type=Path, help="una o varias carpetas o discos")
    p.add_argument("--aplicar", action="store_true", help="hacer los cambios (sin esto, solo simula)")
    p.add_argument("--recursivo", action="store_true", help="incluir subcarpetas")
    p.add_argument("--formato", default="{autor} {año} - {titulo}")
    p.add_argument("--leer-pdf", action="store_true", help="buscar el sello de arXiv dentro del PDF")
    p.add_argument("--biblioteca", type=Path,
                   help="carpeta biblioteca: mueve cada artículo a su subcarpeta por categoría")
    p.add_argument("--copiar", action="store_true",
                   help="con --biblioteca: copiar en vez de mover (deja los originales)")
    p.add_argument("--niveles", type=int, choices=[1, 2], default=2,
                   help="1 = solo área (Computer Science); 2 = área y subcategoría (cs.LG)")
    p.add_argument("--inventario", type=Path, help="guardar en CSV la lista de artículos encontrados")
    p.add_argument("--catalogo", type=Path,
                   help="base SQLite con la metadata (por defecto BIBLIOTECA\\catalogo_arxiv.sqlite)")
    p.add_argument("--reconstruir-catalogo", action="store_true",
                   help="cataloga los PDFs que ya están en la biblioteca (no mueve ni renombra nada)")
    p.add_argument("--descargar", nargs="+", metavar="ID_O_ARCHIVO",
                   help="códigos de arXiv, URLs o archivos .txt/.csv con el listado, para descargar "
                        "a la biblioteca y catalogar")
    p.add_argument("--exportar-csv", action="store_true",
                   help="solo actualiza el catálogo existente (columnas nuevas) y regenera el CSV")
    args = p.parse_args()

    if args.exportar_csv:
        if not (args.catalogo or args.biblioteca):
            sys.exit("--exportar-csv necesita --biblioteca CARPETA (o --catalogo RUTA)")
        ruta_cat = args.catalogo or args.biblioteca.resolve() / "catalogo_arxiv.sqlite"
        if not Path(ruta_cat).exists():
            sys.exit(f"No existe {ruta_cat}")
        con = abrir_catalogo(ruta_cat)
        exportar_csv(con, Path(ruta_cat).with_suffix(".csv"))
        n = con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0]
        con.close()
        return print(f"Catálogo actualizado ({n} artículos) y CSV regenerado: "
                     f"{Path(ruta_cat).with_suffix('.csv')}")
    if args.descargar:
        return procesar_descargas(args)
    if args.reconstruir_catalogo:
        return reconstruir_catalogo(args)
    if not args.carpetas:
        p.error("indica al menos una carpeta o disco")

    if args.copiar and not args.biblioteca:
        sys.exit("--copiar solo tiene sentido junto con --biblioteca.")
    if args.leer_pdf:
        try:
            import pypdf  # noqa: F401
        except ImportError:
            sys.exit("--leer-pdf necesita pypdf. Instálalo con:  pip install pypdf")

    biblio = args.biblioteca.resolve() if args.biblioteca else None
    ruta_cat = args.catalogo or (biblio / "catalogo_arxiv.sqlite" if biblio else None)
    print("Buscando PDFs...")
    archivo_id, total, revisados = {}, 0, 0
    for f in listar_pdfs(args.carpetas, args.recursivo):
        if biblio and biblio in f.resolve().parents:
            # Dentro de la biblioteca solo se procesan descargas nuevas (nombre = ID de arXiv);
            # lo ya renombrado y clasificado no se toca.
            aid = id_desde_nombre(f)
            if aid:
                total += 1
                archivo_id[f] = aid
            continue
        total += 1
        aid = id_desde_nombre(f)
        if not aid and args.leer_pdf:
            revisados += 1
            if revisados % 100 == 0:
                print(f"   ...{revisados} PDFs leídos por dentro")
            aid = id_desde_pdf(f)
        if aid:
            archivo_id[f] = aid

    print(f"{total} PDFs revisados; {len(archivo_id)} son de arXiv "
          f"({len(set(archivo_id.values()))} artículos distintos).")
    if not archivo_id:
        sys.exit("No encontré archivos con nombre o sello de arXiv.")

    print("Consultando arXiv...")
    meta = consultar_arxiv(sorted(set(archivo_id.values())))

    if args.inventario:
        with open(args.inventario, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["ruta", "id_arxiv", "categoria", "autor", "año", "titulo"])
            for f, aid in sorted(archivo_id.items()):
                d = meta.get(aid, {})
                w.writerow([str(f), aid, d.get("categoria", ""), d.get("autor", ""),
                            d.get("año", ""), d.get("titulo", "")])
        print(f"Inventario guardado en {args.inventario}")

    accion = "copia" if args.copiar else "mueve"
    registro, ubicados, duplicados = [], set(), []
    con = None
    if ruta_cat and args.aplicar:
        if biblio:
            biblio.mkdir(parents=True, exist_ok=True)
        con = abrir_catalogo(ruta_cat)
    print()
    for f, aid in sorted(archivo_id.items()):
        datos = meta.get(aid)
        if not datos:
            print(f"[no hallado] {f}  (ID {aid})")
            continue
        nombre = limpiar(args.formato.format(id=aid.replace("/", "_"), **datos)) + ".pdf"

        if biblio:
            carpeta = biblio.joinpath(*carpeta_categoria(datos["categoria"], args.niveles))
            if aid in ubicados or (carpeta / nombre).exists():
                duplicados.append(f)
                continue  # el artículo ya está en la biblioteca: no se duplica
            ubicados.add(aid)
            destino = destino_libre(carpeta, nombre)
            print(f"{f}\n   {accion} -> {destino.relative_to(biblio)}")
            if args.aplicar:
                try:
                    carpeta.mkdir(parents=True, exist_ok=True)
                    if args.copiar:
                        shutil.copy2(f, destino)
                    else:
                        shutil.move(str(f), str(destino))
                    registro.append([accion, str(f), str(destino)])
                    if con:
                        guardar_en_catalogo(con, aid, datos, destino)
                except OSError as e:
                    print(f"   [error] {e}")
        else:
            if f.name == nombre:
                continue
            destino = destino_libre(f.parent, nombre)
            print(f"{f}\n   -> {destino.name}")
            if args.aplicar:
                try:
                    f.rename(destino)
                    registro.append(["renombra", str(f), str(destino)])
                    if con:
                        guardar_en_catalogo(con, aid, datos, destino)
                except OSError as e:
                    print(f"   [error] no se pudo renombrar: {e}")

    if duplicados:
        print(f"\n{len(duplicados)} archivos son copias de artículos que ya están en la biblioteca; "
              "se dejaron donde estaban:")
        for f in duplicados:
            print(f"   {f}")

    if args.aplicar and registro:
        log = (biblio or Path(".")) / "renombrados_arxiv.csv"
        with open(log, "a", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows(registro)
        print(f"\n{len(registro)} archivos procesados. Registro de acciones en {log}")
    if con:
        con.commit()
        exportar_csv(con, Path(ruta_cat).with_suffix(".csv"))
        n = con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0]
        con.close()
        print(f"Catálogo actualizado: {n} artículos en {ruta_cat} (y copia en .csv)")
    elif not args.aplicar:
        print("\n(Simulación. Agrega --aplicar para hacer los cambios.)")


RE_ID_TEXTO = re.compile(
    r"(?<![\w.])(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?![\w])", re.I)


def leer_lista_ids(entradas):
    """Acepta IDs, URLs de arXiv o rutas a archivos .txt/.csv con IDs; devuelve IDs sin versión."""
    texto = []
    for e in entradas:
        ruta = Path(e)
        if ruta.is_file():
            texto.append(ruta.read_text(encoding="utf-8-sig", errors="ignore"))
        else:
            texto.append(e)
    vistos, ids = set(), []
    for m in RE_ID_TEXTO.finditer("\n".join(texto)):
        aid = m.group(1)
        if aid not in vistos:
            vistos.add(aid)
            ids.append(aid)
    return ids


def procesar_descargas(args):
    if not args.biblioteca:
        sys.exit("--descargar necesita --biblioteca CARPETA")
    biblio = args.biblioteca.resolve()
    ruta_cat = args.catalogo or biblio / "catalogo_arxiv.sqlite"

    ids = leer_lista_ids(args.descargar)
    if not ids:
        sys.exit("No encontré códigos de arXiv en lo que indicaste.")
    print(f"{len(ids)} códigos recibidos.")

    # Omitir los que ya están en el catálogo (y cuyo PDF sigue existiendo)
    ya = {}
    if Path(ruta_cat).exists():
        con = abrir_catalogo(ruta_cat)
        ya = dict(con.execute("SELECT id_arxiv, ruta_archivo FROM articulos"))
        con.close()
    pendientes = []
    for aid in ids:
        if aid in ya and ya[aid] and Path(ya[aid]).exists():
            print(f"[ya en biblioteca] {aid}  ->  {ya[aid]}")
        else:
            pendientes.append(aid)
    if not pendientes:
        print("Nada nuevo por descargar.")
        return

    print(f"Consultando metadata de {len(pendientes)} artículos...")
    meta = consultar_arxiv(pendientes)

    con = abrir_catalogo(ruta_cat) if args.aplicar else None
    registro, n_ok = [], 0
    print()
    for i, aid in enumerate(pendientes):
        datos = meta.get(aid)
        if not datos:
            print(f"[no existe en arXiv] {aid}")
            continue
        carpeta = biblio.joinpath(*carpeta_categoria(datos["categoria"], args.niveles))
        nombre = limpiar(args.formato.format(id=aid.replace("/", "_"), **datos)) + ".pdf"
        destino = destino_libre(carpeta, nombre)
        print(f"{aid}\n   descarga -> {destino.relative_to(biblio)}")
        if not args.aplicar:
            continue
        if n_ok:
            time.sleep(3)  # pausa entre descargas que pide arXiv
        pdf = obtener_bytes(datos["url_pdf"].replace("http://", "https://", 1))
        if not pdf or not pdf.startswith(b"%PDF"):
            print("   [error] no se pudo descargar el PDF (puede que arXiv no tenga PDF para este artículo)")
            continue
        carpeta.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".part")
        tmp.write_bytes(pdf)
        tmp.replace(destino)
        guardar_en_catalogo(con, aid, datos, destino)
        con.commit()
        registro.append(["descarga", datos["url_pdf"], str(destino)])
        n_ok += 1

    if con:
        exportar_csv(con, Path(ruta_cat).with_suffix(".csv"))
        n = con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0]
        con.close()
        if registro:
            with open(biblio / "renombrados_arxiv.csv", "a", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerows(registro)
        print(f"\n{n_ok} artículos descargados y catalogados. Total en el catálogo: {n}.")
    else:
        print("\n(Simulación. Agrega --aplicar para descargar.)")


def reconstruir_catalogo(args):
    if not args.biblioteca:
        sys.exit("--reconstruir-catalogo necesita --biblioteca CARPETA")
    biblio = args.biblioteca.resolve()
    ruta_cat = args.catalogo or biblio / "catalogo_arxiv.sqlite"
    try:
        import pypdf  # noqa: F401
        con_pypdf = True
    except ImportError:
        con_pypdf = False
        print("[aviso] pypdf no está instalado: solo se usará el registro de movimientos. "
              "Para leer el sello de los PDFs:  pip install pypdf")

    mapa = ids_desde_registro(biblio)
    print(f"Revisando PDFs en {biblio}...")
    archivo_id, sin_id = {}, []
    for f in listar_pdfs([biblio], True):
        aid = (id_desde_nombre(f) or mapa.get(os.path.normcase(os.path.abspath(f)))
               or (id_desde_pdf(f) if con_pypdf else None))
        if aid:
            archivo_id[f] = aid
        else:
            sin_id.append(f)
    print(f"{len(archivo_id)} PDFs identificados; {len(sin_id)} sin ID de arXiv.")
    if not archivo_id:
        sys.exit("Nada que catalogar.")

    print("Consultando arXiv...")
    meta = consultar_arxiv(sorted(set(archivo_id.values())))
    con = abrir_catalogo(ruta_cat)
    n_ok = 0
    for f, aid in sorted(archivo_id.items()):
        if aid in meta:
            guardar_en_catalogo(con, aid, meta[aid], f)
            n_ok += 1
        else:
            print(f"[no hallado] {f}  (ID {aid})")
    con.commit()
    exportar_csv(con, Path(ruta_cat).with_suffix(".csv"))
    n = con.execute("SELECT COUNT(*) FROM articulos").fetchone()[0]
    con.close()
    for f in sin_id:
        print(f"[sin ID] {f}")
    print(f"\n{n_ok} artículos catalogados. Total en el catálogo: {n}.\n"
          f"Base: {ruta_cat}\nCSV:  {Path(ruta_cat).with_suffix('.csv')}")


if __name__ == "__main__":
    main()
