"""corpus_manifest.json: un registro por documento, actualizado en cada descarga."""
from __future__ import annotations

import json
import os
from pathlib import Path

CAMPOS_OBLIGATORIOS = ["doc_id", "titulo", "fuente", "url", "fecha_consulta", "areas"]


class Manifest:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.docs: dict[str, dict] = {}
        if ruta.exists():
            for reg in json.loads(ruta.read_text(encoding="utf-8")):
                self.docs[reg["doc_id"]] = reg

    def get(self, doc_id: str) -> dict | None:
        return self.docs.get(doc_id)

    def actualizar(self, registro: dict) -> None:
        faltan = [c for c in CAMPOS_OBLIGATORIOS if not registro.get(c)]
        if faltan and registro.get("estado") == "ok":
            raise ValueError(f"{registro.get('doc_id')}: faltan campos obligatorios {faltan}")
        self.docs[registro["doc_id"]] = registro
        self.guardar()

    def guardar(self) -> None:
        """Escritura atómica: si el proceso se cae, el manifest anterior queda intacto."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".json.tmp")
        datos = [self.docs[k] for k in sorted(self.docs)]
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.ruta)
