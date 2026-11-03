"""
Revisión automática de los temas monitoreados, sin abrir la app.

La app puede programarlo en el Programador de tareas de Windows (una vez al día); cada tema
se revisa solo cuando le toca según su frecuencia (diaria o semanal). Si aparecen artículos
nuevos, muestra una notificación de Windows.

Uso manual:
    pythonw monitor.py            revisa los temas a los que les toca
    python  monitor.py --todos    revisa todos los temas activos ya mismo
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import tareas  # noqa: E402
from datos import Catalogo  # noqa: E402

LOG = APP_DIR / "monitor.log"


def registrar(texto):
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M}  {texto}\n")
    except OSError:
        pass


def notificar(titulo, texto):
    """Notificación de Windows usando el ícono de bandeja de Qt (no necesita nada extra)."""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon
        app = QApplication.instance() or QApplication(sys.argv)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icono = QSystemTrayIcon(app.style().standardIcon(QStyle.SP_FileDialogInfoView))
        icono.setToolTip("Biblioteca arXiv")
        icono.show()
        icono.showMessage(titulo, texto, QSystemTrayIcon.Information, 10000)
        QTimer.singleShot(12000, app.quit)
        app.exec()
        icono.hide()
    except Exception:  # noqa: BLE001
        registrar("no se pudo mostrar la notificación: " + traceback.format_exc(limit=1))


def main(todos=False):
    try:
        cfg = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
        biblioteca = cfg.get("biblioteca", r"D:\Biblioteca_arXiv")
        cat = Catalogo(biblioteca)
    except Exception as e:  # noqa: BLE001
        registrar(f"no se pudo abrir la biblioteca: {e}")
        return 1
    monitores = [m for m in cat.monitores() if m["activo"] and (todos or tareas.es_hora(m))]
    if not monitores:
        registrar("ningún tema para revisar hoy")
        cat.cerrar()
        return 0
    res = tareas.revisar_monitores(monitores, lambda *a: None, lambda: False)
    total, detalle = 0, []
    for m in monitores:
        n = cat.guardar_novedades(m["id"], res.get(m["id"], []))
        cat.marcar_revisado(m["id"])
        total += n
        if n:
            detalle.append(f"{m['nombre']}: {n}")
        registrar(f"«{m['nombre']}»: {len(res.get(m['id'], []))} resultados, {n} nuevos")
    cat.cerrar()
    if total:
        notificar(f"Biblioteca arXiv: {total} artículo(s) nuevo(s)",
                  " · ".join(detalle) + "\nÁbrela para revisarlos y descargarlos.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--todos" in sys.argv))
