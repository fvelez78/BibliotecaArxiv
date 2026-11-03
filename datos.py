"""Acceso al catálogo: metadata de arXiv (tabla articulos, la escribe el script) + datos personales
(favoritos, estado de lectura, notas, etiquetas, palabras clave, versiones nuevas) en tablas aparte,
para que el script nunca los borre al actualizar un artículo."""
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

import renombrar_arxiv as core

NOMBRE_CATALOGO = "catalogo_arxiv.sqlite"
ESTADOS = ["Por leer", "Leyendo", "Leído"]

ESQUEMA_PERSONAL = """
CREATE TABLE IF NOT EXISTS personal (
    id_arxiv   TEXT PRIMARY KEY,
    favorito   INTEGER DEFAULT 0,
    estado     TEXT DEFAULT '',          -- '', 'Por leer', 'Leyendo', 'Leído'
    nota       TEXT DEFAULT '',
    modificado TEXT
);
CREATE TABLE IF NOT EXISTS etiquetas (
    id_arxiv TEXT,
    etiqueta TEXT,
    PRIMARY KEY (id_arxiv, etiqueta)
);
CREATE TABLE IF NOT EXISTS palabras_clave (
    id_arxiv TEXT,
    palabra  TEXT,
    fuente   TEXT,                       -- 'autor' (del PDF), 'OpenAlex', 'tema OpenAlex'
    PRIMARY KEY (id_arxiv, palabra, fuente)
);
CREATE TABLE IF NOT EXISTS versiones_nuevas (
    id_arxiv       TEXT PRIMARY KEY,
    version_local  TEXT,
    version_arxiv  TEXT,
    revisado       TEXT
);
CREATE INDEX IF NOT EXISTS ix_etq ON etiquetas(etiqueta);
CREATE TABLE IF NOT EXISTS monitores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT,
    palabras        TEXT,                -- frases separadas por coma (se buscan en título y resumen)
    categorias      TEXT,                -- códigos arXiv separados por coma (opcional)
    autores         TEXT,                -- apellidos separados por coma (opcional)
    frecuencia      TEXT DEFAULT 'semanal',   -- 'diaria' | 'semanal'
    activo          INTEGER DEFAULT 1,
    ultima_revision TEXT,
    creado          TEXT
);
CREATE TABLE IF NOT EXISTS novedades (
    id_arxiv    TEXT,
    monitor_id  INTEGER,
    titulo      TEXT,
    autores     TEXT,
    publicado   TEXT,
    categoria   TEXT,
    resumen     TEXT,
    url_abs     TEXT,
    meta_json   TEXT,                    -- metadata completa para descargar sin volver a consultar
    estado      TEXT DEFAULT 'nuevo',    -- 'nuevo' | 'visto' | 'descartado' | 'descargado'
    encontrado  TEXT,
    PRIMARY KEY (id_arxiv, monitor_id)
);
"""

FRECUENCIA_DIAS = {"diaria": 1, "semanal": 7}


def sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").lower()


def ahora():
    return datetime.now().isoformat(timespec="seconds")


class Catalogo:
    COLUMNAS = ("id_arxiv, version, titulo, resumen, autores, primer_autor, n_autores, anio, "
                "publicado, actualizado, categoria_principal, area, categorias, area_es, "
                "categoria_es, categorias_es, comentario, journal_ref, doi, url_abs, url_pdf, "
                "ruta_archivo, nombre_archivo")

    def __init__(self, biblioteca):
        self.biblioteca = Path(biblioteca)
        self.ruta = self.biblioteca / NOMBRE_CATALOGO
        con = core.abrir_catalogo(self.ruta)  # migra columnas nuevas si hace falta
        con.close()
        self.con = sqlite3.connect(str(self.ruta))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA_PERSONAL)
        self.con.commit()
        self.tiene_fts = bool(self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='busqueda'").fetchone())

    # ------------------------------------------------------------------ lectura
    def articulos(self):
        filas = self.con.execute(f"SELECT {self.COLUMNAS} FROM articulos").fetchall()
        pers = {r["id_arxiv"]: r for r in self.con.execute("SELECT * FROM personal")}
        etq, pal, ver = {}, {}, {}
        for r in self.con.execute("SELECT id_arxiv, etiqueta FROM etiquetas ORDER BY etiqueta"):
            etq.setdefault(r[0], []).append(r[1])
        for r in self.con.execute("SELECT id_arxiv, palabra, fuente FROM palabras_clave"):
            pal.setdefault(r[0], []).append((r[1], r[2]))
        for r in self.con.execute("SELECT id_arxiv, version_arxiv FROM versiones_nuevas"):
            ver[r[0]] = r[1]
        res = []
        for f in filas:
            a = dict(f)
            p = pers.get(a["id_arxiv"])
            a["favorito"] = bool(p["favorito"]) if p else False
            a["estado"] = (p["estado"] or "") if p else ""
            a["nota"] = (p["nota"] or "") if p else ""
            a["etiquetas"] = etq.get(a["id_arxiv"], [])
            a["palabras"] = pal.get(a["id_arxiv"], [])
            a["version_nueva"] = ver.get(a["id_arxiv"], "")
            a["existe"] = bool(a["ruta_archivo"]) and Path(a["ruta_archivo"]).exists()
            res.append(a)
        return res

    def todas_etiquetas(self):
        return [r[0] for r in self.con.execute(
            "SELECT DISTINCT etiqueta FROM etiquetas ORDER BY etiqueta COLLATE NOCASE")]

    def buscar(self, texto, articulos):
        """IDs que coinciden con todas las palabras en título/resumen/autores (texto completo)
        o en etiquetas, notas y palabras clave."""
        palabras = re.findall(r"\w+", texto, flags=re.UNICODE)
        if not palabras:
            return None
        ids = set()
        if self.tiene_fts:
            consulta = " ".join(f'"{p}"*' for p in palabras)
            try:
                ids |= {r[0] for r in self.con.execute(
                    "SELECT id_arxiv FROM busqueda WHERE busqueda MATCH ?", (consulta,))}
            except sqlite3.Error:
                pass
        objetivo = [sin_tildes(p) for p in palabras]
        for a in articulos:
            extra = " ".join(a["etiquetas"] + [a["nota"]] + [p for p, _ in a["palabras"]])
            base = "" if self.tiene_fts else " ".join([a["titulo"] or "", a["resumen"] or "",
                                                         a["autores"] or ""])
            t = sin_tildes(base + " " + extra)
            if all(p in t for p in objetivo):
                ids.add(a["id_arxiv"])
        return ids

    # ------------------------------------------------------------------ escritura personal
    def _asegurar(self, aid):
        self.con.execute("INSERT OR IGNORE INTO personal (id_arxiv, modificado) VALUES (?, ?)",
                         (aid, ahora()))

    def poner_favorito(self, ids, valor):
        for aid in ids:
            self._asegurar(aid)
            self.con.execute("UPDATE personal SET favorito=?, modificado=? WHERE id_arxiv=?",
                             (int(valor), ahora(), aid))
        self.con.commit()

    def poner_estado(self, ids, estado):
        for aid in ids:
            self._asegurar(aid)
            self.con.execute("UPDATE personal SET estado=?, modificado=? WHERE id_arxiv=?",
                             (estado, ahora(), aid))
        self.con.commit()

    def poner_nota(self, aid, nota):
        self._asegurar(aid)
        self.con.execute("UPDATE personal SET nota=?, modificado=? WHERE id_arxiv=?",
                         (nota, ahora(), aid))
        self.con.commit()

    def poner_etiquetas(self, aid, etiquetas):
        self.con.execute("DELETE FROM etiquetas WHERE id_arxiv=?", (aid,))
        self.con.executemany("INSERT OR IGNORE INTO etiquetas VALUES (?, ?)",
                             [(aid, e) for e in etiquetas])
        self.con.commit()

    def agregar_etiqueta(self, ids, etiqueta):
        self.con.executemany("INSERT OR IGNORE INTO etiquetas VALUES (?, ?)",
                             [(aid, etiqueta) for aid in ids])
        self.con.commit()

    def quitar_etiqueta(self, ids, etiqueta):
        self.con.executemany("DELETE FROM etiquetas WHERE id_arxiv=? AND etiqueta=?",
                             [(aid, etiqueta) for aid in ids])
        self.con.commit()

    def guardar_palabras(self, aid, palabras, fuente):
        self.con.execute("DELETE FROM palabras_clave WHERE id_arxiv=? AND fuente=?", (aid, fuente))
        self.con.executemany("INSERT OR IGNORE INTO palabras_clave VALUES (?, ?, ?)",
                             [(aid, p, fuente) for p in palabras])
        self.con.commit()

    def guardar_version_nueva(self, aid, local, remota):
        self.con.execute("INSERT OR REPLACE INTO versiones_nuevas VALUES (?, ?, ?, ?)",
                         (aid, local, remota, ahora()))
        self.con.commit()

    def limpiar_version_nueva(self, aid):
        self.con.execute("DELETE FROM versiones_nuevas WHERE id_arxiv=?", (aid,))
        self.con.commit()

    def actualizar_articulo(self, aid, meta, ruta_pdf):
        """Reescribe la metadata de arXiv (tras descargar una versión nueva)."""
        core.guardar_en_catalogo(self.con, aid, meta, ruta_pdf)
        self.con.commit()

    # ------------------------------------------------------------------ monitoreo de temas
    def monitores(self):
        filas = [dict(r) for r in self.con.execute("SELECT * FROM monitores ORDER BY nombre COLLATE NOCASE")]
        nuevos = dict(self.con.execute(
            "SELECT monitor_id, COUNT(*) FROM novedades WHERE estado='nuevo' GROUP BY monitor_id").fetchall())
        for m in filas:
            m["nuevos"] = nuevos.get(m["id"], 0)
        return filas

    def guardar_monitor(self, m):
        campos = (m["nombre"], m.get("palabras", ""), m.get("categorias", ""), m.get("autores", ""),
                  m.get("frecuencia", "semanal"), int(m.get("activo", 1)))
        if m.get("id"):
            self.con.execute("UPDATE monitores SET nombre=?, palabras=?, categorias=?, autores=?, "
                             "frecuencia=?, activo=? WHERE id=?", campos + (m["id"],))
            mid = m["id"]
        else:
            mid = self.con.execute("INSERT INTO monitores (nombre, palabras, categorias, autores, frecuencia, "
                                   "activo, creado) VALUES (?,?,?,?,?,?,?)", campos + (ahora(),)).lastrowid
        self.con.commit()
        return mid

    def borrar_monitor(self, mid):
        self.con.execute("DELETE FROM monitores WHERE id=?", (mid,))
        self.con.execute("DELETE FROM novedades WHERE monitor_id=?", (mid,))
        self.con.commit()

    def marcar_revisado(self, mid):
        self.con.execute("UPDATE monitores SET ultima_revision=? WHERE id=?", (ahora(), mid))
        self.con.commit()

    def guardar_novedades(self, mid, metas):
        """Agrega los artículos encontrados que aún no estaban; devuelve cuántos son nuevos."""
        import json
        en_biblioteca = {r[0] for r in self.con.execute("SELECT id_arxiv FROM articulos")}
        n = 0
        for m in metas:
            estado = "descargado" if m["id_arxiv"] in en_biblioteca else "nuevo"
            cur = self.con.execute(
                "INSERT OR IGNORE INTO novedades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (m["id_arxiv"], mid, m["titulo"], "; ".join(a for a, _ in m["autores"]), m["publicado"],
                 m["categoria"], m["resumen"], m["url_abs"], json.dumps(m, ensure_ascii=False), estado, ahora()))
            n += cur.rowcount if estado == "nuevo" else 0
        self.con.commit()
        return n

    def novedades(self, mid=None, ocultar_descartados=True):
        sql = "SELECT * FROM novedades"
        cond, args = [], []
        if mid is not None:
            cond.append("monitor_id=?")
            args.append(mid)
        if ocultar_descartados:
            cond.append("estado <> 'descartado'")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY (estado='nuevo') DESC, publicado DESC"
        vistos, res = set(), []
        for r in self.con.execute(sql, args):
            if r["id_arxiv"] not in vistos:     # un artículo puede aparecer en varios temas
                vistos.add(r["id_arxiv"])
                res.append(dict(r))
        return res

    def marcar_novedades(self, ids, estado):
        self.con.executemany("UPDATE novedades SET estado=? WHERE id_arxiv=?", [(estado, i) for i in ids])
        self.con.commit()

    def total_novedades(self):
        return self.con.execute("SELECT COUNT(DISTINCT id_arxiv) FROM novedades WHERE estado='nuevo'").fetchone()[0]

    def ids_en_biblioteca(self):
        return {r[0] for r in self.con.execute("SELECT id_arxiv FROM articulos")}

    def exportar_csv(self):
        core.exportar_csv(self.con, self.ruta.with_suffix(".csv"))

    def cerrar(self):
        self.con.close()
