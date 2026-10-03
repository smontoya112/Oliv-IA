"""Genera informe/INFORME_TECNICO.pdf desde informe/INFORME_TECNICO.md y comprueba que tenga <= 3 páginas.

Necesita el paquete `markdown` (pip install markdown) y Microsoft Edge o Google Chrome instalado (se usa en modo
headless para imprimir a PDF). Desde la raíz del repo:

    python informe/construir_pdf.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import markdown

AQUI = Path(__file__).resolve().parent
FUENTE = AQUI / "INFORME_TECNICO.md"
SALIDA = AQUI / "INFORME_TECNICO.pdf"
MAX_PAGINAS = 3

CSS = """
@page { size: A4; margin: 1.35cm 1.5cm; }
body { font-family: 'Segoe UI', Calibri, Arial, sans-serif; font-size: 9.3pt; line-height: 1.3; color: #111; }
h1 { font-size: 15pt; margin: 0 0 2px 0; }
h2 { font-size: 10.6pt; margin: 8px 0 3px 0; border-bottom: 1px solid #999; padding-bottom: 1px; }
p { margin: 3px 0; text-align: justify; }
ol, ul { margin: 3px 0 3px 16px; padding: 0; }
li { margin: 1px 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 4px 0; font-size: 8.6pt; }
th, td { border: 1px solid #888; padding: 2px 4px; vertical-align: top; }
th { background: #e9ecef; text-align: left; }
code { font-family: Consolas, monospace; font-size: 7.9pt; background: #f1f3f5; padding: 0 1px; }
"""


def navegador() -> str:
    candidatos = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge") or "", shutil.which("google-chrome") or "", shutil.which("chromium") or "",
    ]
    for c in candidatos:
        if c and Path(c).exists():
            return c
    sys.exit("No encuentro Edge ni Chrome para imprimir a PDF")


def main() -> int:
    cuerpo = markdown.markdown(FUENTE.read_text(encoding="utf-8"), extensions=["tables"])
    html = f"<!doctype html><html lang='es'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{cuerpo}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        ruta_html = Path(tmp) / "informe.html"
        ruta_html.write_text(html, encoding="utf-8")
        ruta_pdf = Path(tmp) / "informe.pdf"          # se imprime en una carpeta temporal y luego se copia
        subprocess.run([navegador(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={ruta_pdf}", ruta_html.as_uri()], check=True, capture_output=True, timeout=120)
        for _ in range(40):                           # el navegador puede devolver el control antes de terminar de escribir
            if ruta_pdf.exists() and ruta_pdf.stat().st_size > 0:
                break
            time.sleep(0.5)
        shutil.copyfile(ruta_pdf, SALIDA)
    paginas = len(re.findall(rb"/Type\s*/Page(?!s)", SALIDA.read_bytes()))
    print(f"{SALIDA} · {paginas} páginas")
    if paginas > MAX_PAGINAS:
        print(f"ERROR: el informe debe tener como máximo {MAX_PAGINAS} páginas", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
