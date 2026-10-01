"""Lógica pura de selección (sin modelos): de los rankings de BM25 y denso a los candidatos
del reranker y, con los puntajes, a los 10 pasajes finales. Separada del pipeline para poder
probarla sin GPU ni índices."""
from __future__ import annotations

from src.indice.fusion import rrf

from . import area, cerradas, normas_pregunta
from .catalogo import Catalogo
from .config import Config

PREMIO_DIRECTO = 1.0     # sin reranker, los directos van primero (RRF nunca llega a 0,04)


def candidatos(item: dict, cat: Catalogo, cfg: Config,
               rankings: list[tuple[list, list]]) -> tuple[dict[int, dict], dict]:
    """Candidatos al reranker: {fila: {via, opcion, fusion, q}} y la información de
    normas/áreas. `rankings[0]` es la consulta base; el resto, una por opción (cerradas)."""
    base_txt = cerradas.consulta_base(item)
    por_op = cerradas.consultas_por_opcion(item)
    rl, rd = rankings[0]
    fusion = rrf(rl, rd, k=cfg.k_area)
    filtrado, fallback = area.filtrar(fusion, cat, area.areas_item(item), cfg.min_en_area,
                                      cfg.area_modo)

    # 6.1: las normas del enunciado (se calcula siempre para las señales; solo se promueve si cfg.directos)
    dirs, info = normas_pregunta.directos(item.get("pregunta") or "", cat, fusion, cfg.n_directos)
    if not cfg.directos:
        dirs = []

    cand: dict[int, dict] = {}
    vistos: set[str] = set()
    sha1 = cat.cols["sha1_texto"]

    def poner(i: int, **datos) -> bool:
        if i in cand or sha1[i] in vistos:
            return False
        vistos.add(sha1[i])
        cand[i] = datos
        return True

    for i in dirs:
        poner(i, via="directo", opcion=None, fusion=0.0, q=base_txt)
    reserva = cfg.extra_por_opcion * len(por_op)
    for i, s in filtrado[: max(cfg.k_fusion - reserva, 0)]:
        poner(i, via="hibrido", opcion=None, fusion=s, q=base_txt)
    for (letra, texto), (rlo, rdo) in zip(por_op, rankings[1:]):     # 6.6
        n = 0
        for i, s in rrf(rlo, rdo, k=20):
            if poner(i, via="opcion", opcion=letra, fusion=s, q=texto):
                n += 1
                if n >= cfg.extra_por_opcion:
                    break
    info["area_fallback"] = fallback
    return cand, info


def elegir(cand: dict[int, dict], puntaje: dict[int, float], cfg: Config) -> list[int]:
    """Los `top_final` mejores por puntaje; los directos (hasta n_directos) entran siempre."""
    orden = sorted(cand, key=lambda i: (-puntaje[i], i))
    directos = [i for i in orden if cand[i]["via"] == "directo"][: cfg.n_directos]
    resto = [i for i in orden if i not in directos]
    final = directos + resto[: max(cfg.top_final - len(directos), 0)]
    return sorted(final, key=lambda i: (-puntaje[i], i))


def senales(final: list[int], cand: dict[int, dict], puntaje: dict[int, float], cat: Catalogo,
            info: dict, reranker: bool) -> dict:
    """Entradas para la política de abstención (paso 8.4)."""
    nombradas = {x.split("#")[0] for x in info["nombradas"]}
    presentes = {cat.base(i) for i in final}
    return {
        "score_top1": round(max((puntaje[i] for i in final), default=0.0), 4),
        "score_top10": round(min((puntaje[i] for i in final), default=0.0), 4),
        "con_reranker": reranker,
        "n_directos": sum(cand[i]["via"] == "directo" for i in final),
        "normas_nombradas": len(nombradas),
        "normas_nombradas_fuera_del_corpus": len({x.split("#")[0] for x in info["sin_corpus"]}),
        "cobertura_normas_pregunta": (round(len(nombradas & presentes) / len(nombradas), 3)
                                      if nombradas else None),
        "area_fallback": info["area_fallback"],
    }
