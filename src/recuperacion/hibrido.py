"""Paso 6.4: búsqueda híbrida (BM25 + denso bge-m3) sobre los índices de la fase 5.

Las consultas se hacen por lotes: una pasada de BM25 y una de FAISS para todas las consultas
de un ítem (la base y, en cerradas, una por opción). Los textos repetidos se colapsan por
sha1 antes de cortar el top-k, igual que en src.indice.evaluar.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.indice.fusion import colapsar, rrf

from .catalogo import Catalogo
from .config import Config

__all__ = ["Hibrido", "rrf"]


class Hibrido:
    def __init__(self, cat: Catalogo, dir_indice: Path = Path("data/index"),
                 device: str | None = None):
        from src.indice import denso, lexico
        from src.indice.encoder import Encoder
        self.cat = cat
        self.cfg_indice = json.loads((dir_indice / "index_config.json").read_text(encoding="utf-8"))
        ids = cat.cols["chunk_id"]
        self._denso, self._lexico = denso, lexico
        self.bm25 = lexico.cargar(dir_indice, ids)          # falla si el índice es de otro chunks.parquet
        self.faiss = denso.cargar(dir_indice, ids)
        self.stemmer = lexico.crear_stemmer(bool(self.cfg_indice["lexico"].get("stemmer")))
        d = self.cfg_indice["denso"]
        self.encoder = Encoder(modelo=d["modelo"], revision=d["revision"], device=device)

    def buscar_varias(self, consultas: list[tuple[str, str]], cfg: Config
                      ) -> list[tuple[list, list]]:
        """consultas = [(texto_lexico, texto_denso)]. Devuelve [(ranking_bm25, ranking_denso)]
        en el mismo orden; cada ranking es [(fila, score)] sin textos repetidos."""
        sha1 = self.cat.cols["sha1_texto"]
        n = len(sha1)
        k_lex, k_den = min(n, 3 * cfg.k_lexico), min(n, 3 * cfg.k_denso)
        sc_l, id_l = self._lexico.buscar(self.bm25, [c[0] for c in consultas], k_lex, self.stemmer)
        sc_d, id_d = self._denso.buscar(self.faiss, self.encoder.consultas([c[1] for c in consultas]),
                                        k_den)
        return [(colapsar(sc_l[j], id_l[j], sha1, cfg.k_lexico, True),
                 colapsar(sc_d[j], id_d[j], sha1, cfg.k_denso, False))
                for j in range(len(consultas))]
