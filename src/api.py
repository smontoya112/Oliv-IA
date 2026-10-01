"""Servidor de la interfaz (paso 11.1): POST /api/consulta + la página en /.

    python -m src.api [--host 0.0.0.0] [--port 8000]          # en un nodo con GPU (jobs/servir.sh)
    uvicorn src.api:app                                        # equivalente

La interfaz (interfaz/index.html) envía {pregunta} y lee `respuesta`; además recibe los pasajes
recuperados, las normas citadas y la bandera de abstención. Los modelos se cargan al arrancar y
las consultas se atienden de a una (hay un solo decoder en la GPU).
"""
from __future__ import annotations

import argparse
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.responder import Responder, cargar_config

RAIZ = Path(__file__).resolve().parents[1]
MAX_CARACTERES_PASAJE = 4000
log = logging.getLogger("api")


class Consulta(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=6000)
    formato: Literal["multiple_choice", "semi_open", "open_ended"] | None = None
    opciones: dict[str, str] | None = None


def _pasaje(p: dict) -> dict:
    return {"doc_id": p["doc_id"], "texto": (p.get("texto") or "")[:MAX_CARACTERES_PASAJE],
            "score": p.get("score"), "via": p.get("via"), "opcion": p.get("opcion"),
            "norma_id": p.get("norma_id")}


def crear_app(responder: Responder | None = None) -> FastAPI:
    """`responder` se inyecta en las pruebas; en producción se crea y se carga al arrancar."""
    candado = threading.Lock()
    estado: dict = {"responder": responder}

    @asynccontextmanager
    async def vida(_: FastAPI):
        if estado["responder"] is None:
            log.info("cargando modelos (recuperación + decoder)...")
            estado["responder"] = Responder(cargar_config()).cargar()
            log.info("listo")
        yield

    app = FastAPI(title="Oliv-IA", lifespan=vida)

    @app.get("/api/salud")
    def salud() -> dict:
        r = estado["responder"]
        return {"estado": "ok" if r is not None else "cargando",
                "modelo": getattr(r, "cfg", {}).get("modelo") if r else None}

    @app.post("/api/consulta")
    def consulta(c: Consulta) -> dict:
        r = estado["responder"]
        if r is None:
            raise HTTPException(503, "El servidor todavía está cargando los modelos")
        if not c.pregunta.strip():
            raise HTTPException(422, "La pregunta está vacía")
        try:
            with candado:
                res = r.responder(c.pregunta, formato=c.formato, opciones=c.opciones)
        except ValueError as e:                       # entrada inválida (p. ej. cerrada sin opciones)
            raise HTTPException(422, str(e)) from e
        return {"respuesta": res["respuesta"], "formato": res["formato"],
                "abstencion": res["abstencion"], "normas_citadas": res["normas_citadas"],
                "pasajes": [_pasaje(p) for p in res["pasajes"]], "senales": res["senales"],
                "latencia_ms": res["latencia_ms"]}

    @app.get("/", include_in_schema=False)
    def pagina() -> FileResponse:
        return FileResponse(RAIZ / "interfaz" / "index.html")

    return app


app = crear_app()


# Avance de uvicorn -> stdout; solo los ERROR -> stderr (convención de los jobs).
class _SoloMenosQueError(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


LOG_CONFIG = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"f": {"format": "%(asctime)s %(levelname)s %(message)s"}},
    "filters": {"menor_que_error": {"()": "src.api._SoloMenosQueError"}},
    "handlers": {
        "out": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "f",
                "filters": ["menor_que_error"]},
        "err": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "f",
                "level": "ERROR"},
    },
    "loggers": {"uvicorn": {"handlers": ["out", "err"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["out"], "level": "INFO", "propagate": False},
                "api": {"handlers": ["out", "err"], "level": "INFO", "propagate": False}},
}


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_config=LOG_CONFIG)


if __name__ == "__main__":
    main()
