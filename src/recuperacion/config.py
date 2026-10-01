"""Hiperparámetros de la recuperación. Se guardan en retrieval_config.json en cada corrida."""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Normas que casi cualquier pregunta puede necesitar sin importar su área: el filtro de área
# (paso 6.3) nunca las descarta. Ids de la fase 4 (scripts/normalizacion.to_canonical_id).
TRANSVERSALES = frozenset({"constitucion", "decreto_2591_1991"})


@dataclass
class Config:
    k_denso: int = 100          # candidatos por recuperador, antes de fusionar
    k_lexico: int = 100
    k_area: int = 200           # tamaño del ranking fusionado sobre el que se filtra por área
    k_fusion: int = 50          # candidatos que entran al reranker
    top_final: int = 10         # pasajes que se devuelven (solo cuentan los 10 primeros)
    area_modo: str = "filtro"   # "filtro" | "ninguno"
    min_en_area: int = 20       # si quedan menos candidatos en el área, se usa todo el corpus
    directos: bool = True       # 6.1 inclusión directa de normas nombradas en el enunciado
    n_directos: int = 4
    alias: bool = True          # 6.2 expansión de consultas con el diccionario de alias
    reranker: bool = True       # 6.5
    extra_por_opcion: int = 2   # 6.6 pasajes de evidencia por opción en preguntas cerradas
    lote_reranker: int = 16
    max_tokens_reranker: int = 512

    def dict(self) -> dict:
        return asdict(self)
