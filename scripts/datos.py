"""Datos compartidos del proyecto (corpus, chunks e índice) en Hugging Face Hub.

git no puede llevar data/ (cientos de MB, miles de archivos), así que vive en un dataset
privado de HF y data/DATA_VERSION (esto sí va a git) fija el commit exacto del dataset: todos
bajan los mismos bytes.

    python -m scripts.datos subir            # sube TODO data/ (menos cachés y data/lote) y escribe data/DATA_VERSION
    python -m scripts.datos bajar            # baja exactamente la versión de data/DATA_VERSION
    python -m scripts.datos bajar --sin-indice   # sin data/index (faiss/embeddings/bm25)
    python -m scripts.datos bajar --sin-raw      # sin data/raw, data/descartados ni data/proximidad
    python -m scripts.datos estado           # qué hay en data/ frente a la versión fijada

El token va en HF_TOKEN (variable de entorno o .env en la raíz): escritura para `subir`,
lectura para `bajar`. Nunca se imprime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = os.environ.get("OLIVIA_DATOS_REPO", "smontoya05/oliv-ia-corpus")
RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
VERSION = DATA / "DATA_VERSION"

# Se sube todo data/ salvo esto: cachés de HF, la corrida del sábado y el archivo de preguntas.
SIEMPRE_FUERA = [".cache/**", "lote/**", "test_992.jsonl", "**/__pycache__/**", "**/.DS_Store"]
INDICE = ["index/**"]
CRUDO = ["raw/**", "descartados/**", "proximidad/**"]


def _ignorar(args) -> list[str]:
    return (SIEMPRE_FUERA + (INDICE if getattr(args, "sin_indice", False) else [])
            + (CRUDO if getattr(args, "sin_raw", False) else []))


def _token() -> str:
    t = os.environ.get("HF_TOKEN", "").strip()
    env = RAIZ / ".env"
    if not t and env.exists():
        for linea in env.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = linea.partition("=")
            if k.strip() == "HF_TOKEN":
                t = v.strip().strip("\"'")
    if not t:
        sys.exit("Falta HF_TOKEN (variable de entorno o línea HF_TOKEN=... en .env).")
    return t


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=_token())


def subir(args) -> None:
    api = _api()
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    ign = _ignorar(args)
    print(f"subiendo {DATA} a {REPO} (ignora: {', '.join(ign)}). Reanudable: si se corta, repetir.")
    api.upload_large_folder(repo_id=REPO, repo_type="dataset", folder_path=str(DATA),
                            ignore_patterns=ign, num_workers=4)
    sha = api.dataset_info(REPO).sha
    VERSION.write_text(sha + "\n", encoding="utf-8")
    print(f"listo. versión {sha[:12]} escrita en {VERSION.relative_to(RAIZ)}: commit de git de ese archivo.")


def bajar(args) -> None:
    from huggingface_hub import snapshot_download
    if args.version:
        rev = args.version
    elif VERSION.exists():
        rev = VERSION.read_text(encoding="utf-8").strip()
    else:
        sys.exit("No hay data/DATA_VERSION: haga git pull o pase --version <commit>.")
    DATA.mkdir(exist_ok=True)
    snapshot_download(REPO, repo_type="dataset", revision=rev, local_dir=str(DATA),
                      ignore_patterns=_ignorar(args), token=_token(), max_workers=8)
    print(f"data/ en la versión {rev[:12]} ({REPO})")


def _sha(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def estado(args) -> None:
    print("versión fijada:", VERSION.read_text().strip()[:12] if VERSION.exists() else "(ninguna)")
    n_md = len([p for p in (DATA / "md").glob("*.md")]) if (DATA / "md").exists() else 0
    print("documentos md:", n_md)
    cfg = DATA / "index" / "index_config.json"
    if cfg.exists():
        c = json.loads(cfg.read_text(encoding="utf-8"))
        print("índice:", c.get("n_chunks"), "chunks,", c.get("n_docs"), "docs")
        ch = DATA / "processed" / "chunks.parquet"
        if ch.exists():
            ok = _sha(ch) == c.get("sha256_chunks")
            print("chunks.parquet coincide con el índice:", "sí" if ok else "NO (rehacer índice)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre, f in (("subir", subir), ("bajar", bajar), ("estado", estado)):
        p = sub.add_parser(nombre)
        p.set_defaults(f=f)
        if nombre != "estado":
            p.add_argument("--sin-indice", action="store_true", help="no tocar data/index")
            p.add_argument("--sin-raw", action="store_true", help="no tocar raw/, descartados/ ni proximidad/")
        if nombre == "bajar":
            p.add_argument("--version", help="commit del dataset (por defecto data/DATA_VERSION)")
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
