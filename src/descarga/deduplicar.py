"""Quita del corpus los documentos repetidos (la misma norma descargada varias veces).

    uv run python -m src.descarga.deduplicar             # SOLO informa: qué grupos hay y qué se conservaría
    uv run python -m src.descarga.deduplicar --aplicar   # mueve las copias a data/descartados/

Dos documentos son la misma norma si comparten alguna clave (src.descarga.claves: la norma a la que
apuntan sus URLs o su `canonico`, sin importar host, ruta o ceros a la izquierda) o si su texto es
idéntico. Por grupo se conserva UN documento, en este orden de preferencia: descargado bien, con
`canonico` en el manifest, de la lista inicial (no de una ronda de proximidad), del Senado, con más artículos detectados, con más
texto, con el doc_id más corto. Las copias NO se borran: sus carpetas de data/raw, sus .md y .notas.md
pasan a data/descartados/ y salen del manifest (reversible: se pueden devolver a mano).
Al aplicar se escribe data/duplicados.json (qué se conservó y qué se descartó) y se recalcula
data/descubiertos.csv. Después hay que repetir jobs/chunking.sh y jobs/indice.sh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from .claves import claves_registro
from .config import Config
from .manifest import Manifest

MIN_CARACTERES_TEXTO = 500       # por debajo de esto, "mismo texto" no es evidencia de nada


# ------------------------------------------------------------------ agrupar
def _cuerpo_md(ruta: Path) -> str:
    """Texto del .md sin el front matter."""
    texto = ruta.read_text(encoding="utf-8")
    if texto.startswith("---\n"):
        fin = texto.find("\n---\n", 4)
        if fin != -1:
            texto = texto[fin + 5:]
    return texto


def huella_texto(ruta: Path) -> str | None:
    if not ruta.exists():
        return None
    cuerpo = re.sub(r"<!--.*?-->", "", _cuerpo_md(ruta), flags=re.S)
    cuerpo = " ".join(cuerpo.lower().split())
    if len(cuerpo) < MIN_CARACTERES_TEXTO:
        return None
    return hashlib.sha1(cuerpo.encode("utf-8")).hexdigest()


class _Union:
    def __init__(self, nodos):
        self.p = {n: n for n in nodos}

    def hallar(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def unir(self, a, b):
        self.p[self.hallar(a)] = self.hallar(b)


def agrupar(registros: dict[str, dict], dir_md: Path | None = None) -> list[list[str]]:
    """Grupos (de más de un doc_id) que son la misma norma."""
    u = _Union(registros)
    por_clave: dict[str, list[str]] = defaultdict(list)
    for doc_id, r in registros.items():
        for k in claves_registro(r):
            por_clave[k].append(doc_id)
    for ids in por_clave.values():
        for otro in ids[1:]:
            u.unir(ids[0], otro)
    if dir_md is not None:
        por_huella: dict[str, list[str]] = defaultdict(list)
        for doc_id, r in registros.items():
            if r.get("estado") == "ok" and (h := huella_texto(dir_md / f"{doc_id}.md")):
                por_huella[h].append(doc_id)
        for ids in por_huella.values():
            for otro in ids[1:]:
                u.unir(ids[0], otro)
    grupos: dict[str, list[str]] = defaultdict(list)
    for doc_id in registros:
        grupos[u.hallar(doc_id)].append(doc_id)
    return [sorted(g) for g in grupos.values() if len(g) > 1]


def _orden(r: dict) -> tuple:
    url = (r.get("url") or "").lower()
    return (r.get("estado") != "ok",
            not r.get("canonico"),                          # el que trae su metadata de norma (para el id canónico)
            bool(r.get("origen")),                          # las rondas de proximidad pierden contra la lista inicial
            "secretariasenado.gov.co" not in url,
            -(r.get("n_articulos_detectados") or 0),
            -(r.get("n_caracteres") or 0),
            len(r["doc_id"]), r["doc_id"])


def elegir(registros: dict[str, dict], grupo: list[str]) -> str:
    return min(grupo, key=lambda d: _orden(registros[d]))


CRITERIOS = ("la otra copia no se descargó bien", "la otra copia no trae canonico",
             "la otra copia viene de una ronda de proximidad", "la otra copia no es del Senado",
             "la otra copia tiene menos artículos detectados", "la otra copia tiene menos texto")


def motivo(registros: dict[str, dict], grupo: list[str], conservado: str) -> str | None:
    """Por qué se conserva `conservado` y no la copia de id más corto (la que uno esperaría).
    None si es la misma, es decir, si no hay nada raro que explicar."""
    esperada = min(grupo, key=lambda d: (len(d), d))
    if esperada == conservado:
        return None
    a, b = _orden(registros[conservado]), _orden(registros[esperada])
    for i, nombre in enumerate(CRITERIOS):
        if a[i] != b[i]:
            return nombre
    return "desempate por id"


def _fila(r: dict) -> str:
    host = re.sub(r"^https?://(www\.)?", "", r.get("url") or "").split("/")[0]
    return (f"{r['doc_id']:<30} estado={r.get('estado'):<6} origen={r.get('origen') or 'inicial':<14} "
            f"artículos={r.get('n_articulos_detectados') or 0:<5} caracteres={r.get('n_caracteres') or 0:<8} {host}")


# ------------------------------------------------------------------ aplicar
def _mover(origen: Path, destino: Path) -> bool:
    if not origen.exists():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        shutil.rmtree(destino) if destino.is_dir() else destino.unlink()
    shutil.move(str(origen), str(destino))
    return True


def aplicar(cfg: Config, manifest: Manifest, grupos: list[list[str]], dir_descartados: Path) -> list[dict]:
    informe = []
    for grupo in grupos:
        guardar = elegir(manifest.docs, grupo)
        for doc_id in grupo:
            if doc_id == guardar:
                continue
            _mover(cfg.dir_raw / doc_id, dir_descartados / "raw" / doc_id)
            _mover(cfg.dir_md / f"{doc_id}.md", dir_descartados / "md" / f"{doc_id}.md")
            _mover(cfg.dir_md / f"{doc_id}.notas.md", dir_descartados / "md" / f"{doc_id}.notas.md")
            manifest.docs.pop(doc_id, None)
        informe.append({"conservado": guardar,
                        "descartados": [d for d in grupo if d != guardar]})
    manifest.guardar()
    return informe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raiz", type=Path, default=Path("data"))
    ap.add_argument("--aplicar", action="store_true", help="mover las copias (sin esto solo se informa)")
    ap.add_argument("--sin-texto", action="store_true", help="no agrupar por texto idéntico, solo por clave")
    ap.add_argument("--descartados", type=Path, help="por defecto <raiz>/descartados")
    ap.add_argument("--explicar", type=int, nargs="?", const=15, default=0, metavar="N",
                    help="muestra N ejemplos (15 por defecto) de grupos donde NO se conserva la copia de id "
                         "más corto, con los datos de cada copia")
    args = ap.parse_args()

    cfg = Config(raiz=args.raiz)
    manifest = Manifest(cfg.ruta_manifest)
    grupos = agrupar(manifest.docs, None if args.sin_texto else cfg.dir_md)
    sobran = sum(len(g) - 1 for g in grupos)
    print(f"documentos en el manifest: {len(manifest.docs)} · grupos con copias: {len(grupos)} · "
          f"copias que sobran: {sobran}")
    for grupo in sorted(grupos, key=len, reverse=True)[:25]:
        k = elegir(manifest.docs, grupo)
        print(f"  se conserva {k:<34} se descartan {', '.join(d for d in grupo if d != k)}")
    if len(grupos) > 25:
        print(f"  ... y {len(grupos) - 25} grupos más")

    # ¿en cuántos grupos se conserva una copia que no es la de id más corto, y por qué?
    razones: dict[str, list[list[str]]] = defaultdict(list)
    for grupo in grupos:
        if m := motivo(manifest.docs, grupo, elegir(manifest.docs, grupo)):
            razones[m].append(grupo)
    if razones:
        print(f"\nEn {sum(len(v) for v in razones.values())} grupos se conserva una copia que NO es la de id "
              "más corto. Motivo decisivo:")
        for m, gs in sorted(razones.items(), key=lambda x: -len(x[1])):
            print(f"  {len(gs):>5}  {m}")
    if args.explicar:
        mostrados = 0
        for m, gs in sorted(razones.items(), key=lambda x: -len(x[1])):
            for grupo in gs[: max(1, args.explicar // max(len(razones), 1))]:
                k = elegir(manifest.docs, grupo)
                print(f"\n[{m}]")
                for d in sorted(grupo):
                    print(("  → " if d == k else "    ") + _fila(manifest.docs[d]))
                mostrados += 1
    if not args.aplicar:
        print("\n(solo informe: agreguen --aplicar para mover las copias a data/descartados/)")
        return 0

    informe = aplicar(cfg, manifest, grupos, args.descartados or cfg.raiz / "descartados")
    (cfg.raiz / "duplicados.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    from .run import actualizar_descubiertos
    n = actualizar_descubiertos(cfg, [], manifest)
    print(f"\nmovidas {sobran} copias a {args.descartados or cfg.raiz / 'descartados'} · "
          f"documentos ahora: {len(manifest.docs)} · descubiertos recalculado ({n}) · informe en "
          f"{cfg.raiz / 'duplicados.json'}")
    print("Falta repetir jobs/chunking.sh y jobs/indice.sh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
