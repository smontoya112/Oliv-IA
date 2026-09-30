"""Configuración de la descarga. Ajusten user_agent con un correo real del equipo."""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    raiz: Path = Path("data")
    user_agent: str = (
        "OlivIA-Hackathon2026/0.1 (Universidad de los Andes; "
        "contacto: CAMBIAR@uniandes.edu.co)"
    )
    intervalo_por_host: float = 1.5   # segundos mínimos entre peticiones al mismo host
    timeout: float = 60.0
    reintentos: int = 4
    max_paginas: int = 300            # tope de páginas _prNNN por documento
    respetar_robots: bool = True
    ocr_idioma: str = "es"           # código de EasyOCR (Docling)

    @property
    def dir_raw(self) -> Path:
        return self.raiz / "raw"

    @property
    def dir_md(self) -> Path:
        return self.raiz / "md"

    @property
    def ruta_manifest(self) -> Path:
        return self.raiz / "corpus_manifest.json"

    @property
    def ruta_log(self) -> Path:
        return self.raiz / "descarga_log.jsonl"

    @property
    def ruta_descubiertos(self) -> Path:
        return self.raiz / "descubiertos.csv"
