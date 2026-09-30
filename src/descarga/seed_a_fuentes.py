"""Convierte data/seed_targets.json en archivos de fuentes para el descargador.

    uv run python -m src.descarga.seed_a_fuentes

Genera:
    data/fuentes_seed.json        entradas con URL directa, listas para descargar
    data/fuentes_pendientes.json  entradas que necesitan URL manual (Corte Suprema,
                                  decretos sin copia en el Senado, citas sospechosas)

Los donde_buscar del seed son URL de búsqueda (?q=...), no del documento; por eso
aquí se construye la URL directa según el patrón de cada fuente. No editen
fuentes_seed.json a mano: se regenera. Las correcciones van en fuentes_propias.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SENADO = "http://www.secretariasenado.gov.co/senado/basedoc/"
RELATORIA_CC = "https://www.corteconstitucional.gov.co/relatoria/"

AREAS = {
    "Derecho constitucional": "constitucional",
    "Derecho administrativo": "administrativo",
    "Derecho penal": "penal",
    "Derecho procesal": "procesal",
    "Derecho comercial y sociedades": "comercial",
    "Derecho civil": "civil",
    "Derecho de familia": "familia",
    "Derecho tributario": "tributario",
    "Derecho laboral": "laboral",
}

# Códigos que el seed identifica por nombre: URL directa conocida.
CODIGOS = {
    "constitucion": ("Constitución Política de Colombia de 1991", SENADO + "constitucion_politica_1991.html",
                     "constitucion", None, 1991, "Asamblea Nacional Constituyente"),
    "codigo_general_proceso": ("Código General del Proceso (Ley 1564 de 2012)", SENADO + "ley_1564_2012.html",
                               "ley", "1564", 2012, "Congreso de la República"),
    "codigo_sustantivo_trabajo": ("Código Sustantivo del Trabajo (Decretos 2663 y 3743 de 1950)",
                                  SENADO + "codigo_sustantivo_trabajo.html",
                                  "codigo", None, 1950, "Presidencia de la República"),
    "estatuto_tributario": ("Estatuto Tributario (Decreto 624 de 1989)", SENADO + "estatuto_tributario.html",
                            "decreto", "624", 1989, "Presidencia de la República"),
    "estatuto_consumidor": ("Estatuto del Consumidor (Ley 1480 de 2011)", SENADO + "ley_1480_2011.html",
                            "ley", "1480", 2011, "Congreso de la República"),
    "codigo_infancia": ("Código de la Infancia y la Adolescencia (Ley 1098 de 2006)", SENADO + "ley_1098_2006.html",
                        "ley", "1098", 2006, "Congreso de la República"),
    "codigo_disciplinario": ("Código General Disciplinario (Ley 1952 de 2019)", SENADO + "ley_1952_2019.html",
                             "ley", "1952", 2019, "Congreso de la República"),
    "codigo_nacional_policia": ("Código Nacional de Seguridad y Convivencia Ciudadana (Ley 1801 de 2016)",
                                SENADO + "ley_1801_2016.html", "ley", "1801", 2016, "Congreso de la República"),
    "decision_andina_486": ("Decisión Andina 486 de 2000 - Régimen Común sobre Propiedad Industrial",
                            "https://www.comunidadandina.org/StaticFiles/DocOf/DEC486.pdf",
                            "decision", "486", 2000, "Comisión de la Comunidad Andina"),
}

# Citas del seed que no parecen normas reales: probablemente errores de digitación en el
# fundamento de referencia. No se descargan; quedan en pendientes para revisión humana.
SOSPECHOSAS = {
    ("ley", "11500", "2007"): "No existe; probablemente Ley 1150 de 2007 (ya incluida).",
    ("ley", "1150", "2005"): "La Ley 1150 es de 2007 (ya incluida).",
    ("ley", "116", "2006"): "Probablemente Ley 1116 de 2006 (ya incluida).",
    ("ley", "2737", "1989"): "Probablemente Decreto 2737 de 1989 (antiguo Código del Menor).",
    ("jurisprudencia", "SU-6", "1991"): "La Corte Constitucional empezó a fallar en 1992; revisen el radicado.",
}

CORTE_SUPREMA = {"SL": "Sala de Casación Laboral", "SP": "Sala de Casación Penal",
                 "SC": "Sala de Casación Civil"}


def _areas(lista: list[str]) -> list[str]:
    salida = []
    for a in lista:
        clave = "mercados" if a.startswith("Derecho de los mercados") else AREAS.get(a)
        if clave and clave not in salida:
            salida.append(clave)
    return salida


def _urls_sentencia(tipo: str, numero: int, anio: int) -> list[str]:
    """La relatoría usa C-355-06 y T-760-08, pero SU355-22 (sin guion) en años recientes."""
    yy = f"{anio % 100:02d}"
    con_guion = f"{RELATORIA_CC}{anio}/{tipo}-{numero:03d}-{yy}.htm"
    sin_guion = f"{RELATORIA_CC}{anio}/{tipo}{numero:03d}-{yy}.htm"
    sin_relleno = f"{RELATORIA_CC}{anio}/{tipo}-{numero}-{yy}.htm"
    orden = [sin_guion, con_guion] if tipo == "SU" else [con_guion, sin_guion]
    return list(dict.fromkeys(orden + [sin_relleno]))


def convertir(seed: dict) -> tuple[list[dict], list[dict]]:
    listas, pendientes = [], []
    for d in seed["documentos"]:
        clave, numero, anio = d["canonico"]
        base = {"canonico": d["canonico"], "items_del_banco": d["items_del_banco"],
                "areas": _areas(d["areas"])}

        if tuple(d["canonico"]) in SOSPECHOSAS:
            pendientes.append({"norma": d["norma"], **base, "motivo": SOSPECHOSAS[tuple(d["canonico"])]})
            continue

        if clave in CODIGOS:
            titulo, url, tipo_norma, num, an, organo = CODIGOS[clave]
            listas.append({"doc_id": clave, "titulo": titulo,
                           "fuente": "Comunidad Andina" if "comunidadandina" in url
                           else "Secretaría General del Senado",
                           "url": url, "tipo_norma": tipo_norma, "numero": num, "anio": an,
                           "organo_emisor": organo, **base})

        elif clave == "ley":
            listas.append({"doc_id": f"ley_{int(numero)}_{anio}", "titulo": f"Ley {int(numero)} de {anio}",
                           "fuente": "Secretaría General del Senado",
                           "url": f"{SENADO}ley_{int(numero):04d}_{anio}.html",
                           "tipo_norma": "ley", "numero": str(int(numero)), "anio": int(anio),
                           "organo_emisor": "Congreso de la República", **base})

        elif clave == "decreto":
            # El Senado publica solo algunos decretos; si falla, buscarlo en SUIN o en el
            # sitio de la entidad y ponerlo en fuentes_propias.json.
            listas.append({"doc_id": f"decreto_{int(numero)}_{anio}", "titulo": f"Decreto {int(numero)} de {anio}",
                           "fuente": "Secretaría General del Senado",
                           "url": f"{SENADO}decreto_{int(numero):04d}_{anio}.html",
                           "tipo_norma": "decreto", "numero": str(int(numero)), "anio": int(anio),
                           **base, "nota": "Si da 404, buscar en SUIN-Juriscol: " + d["donde_buscar"]})

        elif clave == "jurisprudencia":
            tipo, num = numero.split("-")
            if tipo in CORTE_SUPREMA:
                pendientes.append({"norma": d["norma"], **base,
                                   "motivo": f"Es de la Corte Suprema ({CORTE_SUPREMA[tipo]}), no de la "
                                             "Corte Constitucional. Buscar el radicado "
                                             f"{tipo}{num}-{anio} en la relatoría de la Corte Suprema."})
                continue
            urls = _urls_sentencia(tipo, int(num), int(anio))
            listas.append({"doc_id": f"sentencia_{tipo.lower()}-{int(num)}_{anio}",
                           "titulo": f"Sentencia {tipo}-{int(num):03d} de {anio}",
                           "fuente": "Relatoría de la Corte Constitucional",
                           "url": urls[0], "urls_alternativas": urls[1:], "tipo": "html",
                           "seguir_paginas": False, "tipo_norma": "sentencia", "anio": int(anio),
                           "organo_emisor": "Corte Constitucional", **base})

        else:
            pendientes.append({"norma": d["norma"], **base, "donde_buscar": d["donde_buscar"],
                               "motivo": f"Tipo '{clave}' sin patrón de URL conocido; buscar a mano."})
    return listas, pendientes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=Path, default=Path("data/seed_targets.json"))
    ap.add_argument("--salida", type=Path, default=Path("data/fuentes_seed.json"))
    ap.add_argument("--pendientes", type=Path, default=Path("data/fuentes_pendientes.json"))
    args = ap.parse_args()

    listas, pendientes = convertir(json.loads(args.seed.read_text(encoding="utf-8")))
    # JSON no admite comentarios: los archivos generados se identifican por su nombre.
    args.salida.write_text(json.dumps(listas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.pendientes.write_text(json.dumps(pendientes, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    items = sum(o["items_del_banco"] for o in listas)
    items_p = sum(o["items_del_banco"] for o in pendientes)
    print(f"{len(listas)} documentos listos en {args.salida} (cubren {items} ítems del banco)")
    print(f"{len(pendientes)} pendientes en {args.pendientes} (cubren {items_p} ítems)")


if __name__ == "__main__":
    main()
