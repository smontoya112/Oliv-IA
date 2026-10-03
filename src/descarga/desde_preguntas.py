"""Enriquecimiento del corpus desde las preguntas: qué normas nombran y cuáles faltan.

Para cada pregunta toma las oraciones del enunciado que mencionan una norma ("ley", "decreto",
"sentencia", "código"...), extrae las citas con el parser oficial (citations.extract, el mismo del
evaluador y de la recuperación) y las compara con lo descargado en data/corpus_manifest.json.
Las que faltan se convierten en objetivos de descarga con las reglas de seed_a_fuentes (URL del
Senado o de la relatoría de la Corte Constitucional); las que no tienen patrón de URL (Corte
Suprema, Consejo de Estado, resoluciones...) van a pendientes para buscarlas a mano.

    python -m src.descarga.desde_preguntas --preguntas data/test_992.jsonl \
        --salida data/enriquecimiento/test_992

Salidas en --salida:
    normas.json       cada norma nombrada: en qué preguntas, si está en el corpus, qué se hará
    fragmentos.jsonl  por pregunta, las oraciones con menciones normativas y las citas extraídas;
                      `sin_reconocer` son oraciones con "ley", "decreto"... de las que el parser no
                      sacó ninguna cita (revisarlas a mano: "la Ley 1564" sin año, etc.)
    fuentes.json      objetivos para src.descarga.run --fuentes (solo normas que faltan)
    pendientes.json   normas que faltan y no tienen URL automática

Por defecto solo se lee el enunciado: en las cerradas las opciones suelen nombrar normas
inventadas o ajenas como distractores (ver src/recuperacion/normas_pregunta.py). --con-opciones
las incluye.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import citations  # noqa: E402  (scripts/citations.py, parser oficial)

from src.procesamiento.oraciones import dividir  # noqa: E402

from .claves import clave_canonico, claves_registro  # noqa: E402
from .seed_a_fuentes import convertir  # noqa: E402

MENCION = re.compile(
    r"\b(leyes|ley|decretos?(?:[\s-]ley)?|sentencias?|c[oó]digos?|constituci[oó]n|"
    r"acto\s+legislativo|resoluci[oó]n|circular|acuerdo|estatuto|decisi[oó]n\s+andina)\b", re.I)
# Búsqueda (lleva ?q=): seed_a_fuentes no la toma como URL del documento, solo como pista.
SUIN = "https://www.suin-juriscol.gov.co/?q="


def textos_de(item: dict, con_opciones: bool) -> str:
    partes = [item.get("pregunta") or ""]
    if con_opciones:
        partes += [str(v) for v in (item.get("opciones") or {}).values()]
    return " ".join(" ".join(p.split()) for p in partes if p)


def fragmentos(texto: str) -> list[dict]:
    """Oraciones con alguna mención normativa y las citas (cuerpos) que el parser saca de ellas."""
    res = []
    for a, b in dividir(texto):
        oracion = texto[a:b].strip()
        if MENCION.search(oracion):
            res.append({"texto": oracion,
                        "citas": sorted(map(list, citations.bodies(citations.extract(oracion))),
                                        key=str)})
    return res


def etiqueta(cuerpo: tuple) -> str:
    from src.verificacion.citas import nombre_cuerpo   # "Código Civil", "Ley 472 de 1998"...
    if nombre := nombre_cuerpo(cuerpo):
        return nombre
    tipo, num, anio = cuerpo
    if tipo == "jurisprudencia":
        return f"Sentencia {num} de {anio}"
    if num and anio:
        return f"{tipo.replace('_', ' ').capitalize()} {num} de {anio}"
    return tipo.replace("_", " ").capitalize()


def claves_en_corpus(manifest: Path) -> set[str]:
    """Claves (src.descarga.claves) de todo lo descargado con estado ok."""
    if not manifest.exists():
        return set()
    claves: set[str] = set()
    for r in json.loads(manifest.read_text(encoding="utf-8")):
        if r.get("estado") == "ok":
            claves |= claves_registro(r)
    return claves


def analizar(items: list[dict], en_corpus: set[str], con_opciones: bool = False,
             origen: str = "preguntas") -> dict:
    """{normas, fragmentos, fuentes, pendientes} (ver el docstring del módulo)."""
    preguntas_por: dict[tuple, list[int]] = defaultdict(list)
    areas_por: dict[tuple, list[str]] = defaultdict(list)
    por_item = []
    for it in items:
        texto = textos_de(it, con_opciones)
        frags = fragmentos(texto)
        cuerpos = citations.bodies(citations.extract(texto))
        for c in cuerpos:
            preguntas_por[c].append(it["id"])
            if it.get("area") and it["area"] not in areas_por[c]:
                areas_por[c].append(it["area"])
        por_item.append({"id": it["id"], "fragmentos": frags,
                         "sin_reconocer": [f["texto"] for f in frags if not f["citas"]]})

    faltan = [c for c in preguntas_por if clave_canonico(list(c)) not in en_corpus]
    seed = {"documentos": [{"norma": etiqueta(c), "canonico": list(c),
                            "items_del_banco": len(preguntas_por[c]), "areas": areas_por[c],
                            "donde_buscar": SUIN + etiqueta(c).replace(" ", "+")} for c in faltan]}
    fuentes, pendientes = convertir(seed)
    for f in fuentes:
        f["origen"] = origen
    destino = {tuple(f["canonico"]): f["doc_id"] for f in fuentes}

    normas = []
    for c, ids in sorted(preguntas_por.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
        presente = c not in faltan
        normas.append({"norma": etiqueta(c), "canonico": list(c), "clave": clave_canonico(list(c)),
                       "n_preguntas": len(ids), "preguntas": ids, "en_corpus": presente,
                       "accion": "ya en el corpus" if presente else
                       (f"descargar como {destino[c]}" if c in destino else "buscar a mano")})
    return {"normas": normas, "fragmentos": por_item, "fuentes": fuentes, "pendientes": pendientes}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preguntas", type=Path, required=True, help="JSONL de preguntas (p. ej. data/test_992.jsonl)")
    ap.add_argument("--salida", type=Path, required=True, help="carpeta de salida")
    ap.add_argument("--manifest", type=Path, default=Path("data/corpus_manifest.json"))
    ap.add_argument("--con-opciones", action="store_true",
                    help="también extraer normas de las opciones de las cerradas")
    args = ap.parse_args()
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")

    items = [json.loads(l) for l in args.preguntas.read_text(encoding="utf-8").splitlines() if l.strip()]
    res = analizar(items, claves_en_corpus(args.manifest), args.con_opciones,
                   origen=f"preguntas_{args.preguntas.stem}")
    args.salida.mkdir(parents=True, exist_ok=True)
    for nombre in ("normas", "fuentes", "pendientes"):
        (args.salida / f"{nombre}.json").write_text(
            json.dumps(res[nombre], ensure_ascii=False, indent=1), encoding="utf-8")
    with (args.salida / "fragmentos.jsonl").open("w", encoding="utf-8") as f:
        for r in res["fragmentos"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (args.salida / "ids_a_descargar.txt").write_text(
        "\n".join(f["doc_id"] for f in res["fuentes"]) + ("\n" if res["fuentes"] else ""),
        encoding="utf-8")

    normas = res["normas"]
    con_mencion = sum(1 for r in res["fragmentos"] if r["fragmentos"])
    sin_rec = sum(len(r["sin_reconocer"]) for r in res["fragmentos"])
    print(f"RESULTADO preguntas: {len(items)} · con mención normativa: {con_mencion} · "
          f"normas distintas: {len(normas)} · ya en el corpus: {sum(n['en_corpus'] for n in normas)} · "
          f"a descargar: {len(res['fuentes'])} · a buscar a mano: {len(res['pendientes'])} · "
          f"oraciones sin cita reconocida: {sin_rec}")
    for n in normas:
        if not n["en_corpus"]:
            print(f"  falta {n['norma']} ({n['n_preguntas']} preguntas): {n['accion']}")


if __name__ == "__main__":
    main()
