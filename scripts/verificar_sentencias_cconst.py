"""
Verifica y corrige, para las sentencias de Corte Constitucional (C-, T-, SU-)
en data/seed_targets.json, si existe un enlace directo real en el patron
legado:

    https://www.corteconstitucional.gov.co/relatoria/{anio}/{radicado}-{aa}.htm

Importante: el sitio nuevo de la Corte es una SPA en Angular. Navegado desde
un navegador real, cualquier ruta bajo /relatoria/ que no coincida con sus
rutas internas cae al shell generico de la aplicacion (misma pantalla de
inicio, ~8.6 KB, <title>CORTE CONSTITUCIONAL DE COLOMBIA</title>). Pero una
peticion HTTP simple (curl, requests, lo que use el pipeline de ingesta) SI
recibe el HTML crudo de la sentencia real cuando el radicado y el anio de la
carpeta coinciden exactamente -- son paginas de decenas a cientos de KB con
el texto integro. Por eso una comprobacion visual en el navegador da un falso
"esta roto" que este script corrige verificando el cuerpo de la respuesta,
no solo el codigo HTTP (que es 200 en ambos casos).

Marca como verificada una URL solo si:
  - HTTP 200
  - tamano de respuesta > UMBRAL_BYTES (el shell generico siempre es ~8.6 KB)
  - no contiene el marcador del shell Angular

Actualiza donde_buscar solo para las entradas confirmadas; para las demas deja
intacto lo que ya tuvieran (p. ej. el fallback al buscador de jurisprudencia).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "seed_targets.json"

UMBRAL_BYTES = 20_000
MARCADOR_SHELL = "data-beasties-container"
PREFIJOS_CORTE_CONSTITUCIONAL = {"C", "T", "SU"}


import re

RE_RADICADO = re.compile(r"^([A-Z]+)-(\d+)$")


def construir_url(radicado: str, anio: str, pad: int = 1) -> str:
    aa = anio[-2:]
    m = RE_RADICADO.match(radicado)
    prefijo, numero = (m.group(1), m.group(2)) if m else (radicado, "")
    numero_fmt = numero.zfill(pad) if pad > 1 else numero
    # Las sentencias SU- se nombran sin guion tras "SU" (SU455-20.htm); las
    # C- y T- si lo llevan (C-355-06.htm, T-256-25.htm). El numero de
    # radicado con menos de 3 cifras va con ceros a la izquierda
    # (C-055-22, SU011-20, T-004-26). Descubierto por tanteo comparando
    # tamanos de respuesta reales.
    if prefijo == "SU":
        radicado_archivo = f"SU{numero_fmt}"
    else:
        radicado_archivo = f"{prefijo}-{numero_fmt}"
    return f"https://www.corteconstitucional.gov.co/relatoria/{anio}/{radicado_archivo}-{aa}.htm"


def verificar(url: str) -> bool:
    try:
        proc = subprocess.run(
            ["curl", "-s", "-L", "--max-time", "15", url],
            capture_output=True, timeout=20,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    body = proc.stdout
    if len(body) < UMBRAL_BYTES:
        return False
    if MARCADOR_SHELL.encode() in body:
        return False
    return True


def main():
    with SEED_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    docs = data["documentos"]

    verificadas = 0
    no_verificadas = []
    for d in docs:
        tipo, radicado, anio = d["canonico"]
        if tipo != "jurisprudencia" or not radicado or not anio:
            continue
        prefijo = radicado.split("-")[0]
        if prefijo not in PREFIJOS_CORTE_CONSTITUCIONAL:
            continue  # SL/SP/SC son Corte Suprema, no aplica este patron

        url = construir_url(radicado, anio, pad=1)
        ok = verificar(url)
        time.sleep(0.25)
        if not ok:
            url = construir_url(radicado, anio, pad=3)
            ok = verificar(url)
            time.sleep(0.25)
        if ok:
            d["donde_buscar"] = url
            d.pop("nota_enlace", None)
            verificadas += 1
            print(f"OK   {d['norma']:<40s} {url}")
        else:
            no_verificadas.append(d["norma"])
            print(f"--   {d['norma']:<40s} (sin enlace directo verificable)")

    with SEED_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print()
    print(f"Verificadas y corregidas: {verificadas}")
    print(f"Sin enlace directo verificable: {len(no_verificadas)}")
    for n in no_verificadas:
        print("  -", n)


if __name__ == "__main__":
    main()
