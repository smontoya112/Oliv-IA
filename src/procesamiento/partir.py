"""Partición de un artículo (o sección) en fragmentos de hasta LIMITE_PALABRAS.

Estrategia jerárquica: párrafo (inciso, numeral, parágrafo) → oración → ';' / ':'.
Nunca se corta a mitad de oración salvo que una sola oración supere el límite; en ese
caso el fragmento se marca como `forzado`. El límite cuenta el texto que se entrega
(encabezado + texto vigente), por eso las palabras se miden sin los tachados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.procesamiento import oraciones
from src.procesamiento.normas import Bloque

LIMITE_PALABRAS = 300
_TACHADO = re.compile(r"~~.*?(?:~~|$)", re.S)


def vigente(texto: str) -> str:
    """Texto sin los apartes tachados (declarados inexequibles o derogados)."""
    texto = _TACHADO.sub("", texto)
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    return re.sub(r" +([.,;:])", r"\1", texto).strip()


def palabras(texto: str) -> int:
    return len(texto.split())


@dataclass
class Pieza:
    inicio: int          # offsets absolutos en el texto limpio del documento
    fin: int
    forzado: bool = False


def _spans_separador(texto: str) -> list[tuple[int, int]]:
    spans, ini = [], 0
    for m in re.finditer(r"[;:]\s+", texto):
        spans.append((ini, m.start() + 1))
        ini = m.end()
    spans.append((ini, len(texto)))
    return [(a, b) for a, b in spans if texto[a:b].strip()]


def _por_palabras(texto: str, presupuesto: int) -> list[tuple[int, int]]:
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", texto)]
    return [(tokens[i][0], tokens[min(i + presupuesto, len(tokens)) - 1][1])
            for i in range(0, len(tokens), presupuesto)]


def piezas(texto_doc: str, bloques: list[Bloque], presupuesto: int) -> list[Pieza]:
    salida: list[Pieza] = []
    for b in bloques:
        if palabras(vigente(b.texto)) <= presupuesto:
            salida.append(Pieza(b.inicio, b.fin))
            continue
        for a, z in oraciones.dividir(b.texto):
            sub = b.texto[a:z]
            if palabras(vigente(sub)) <= presupuesto:
                salida.append(Pieza(b.inicio + a, b.inicio + z))
                continue
            for a2, z2 in _spans_separador(sub):
                sub2 = sub[a2:z2]
                if palabras(vigente(sub2)) <= presupuesto:
                    salida.append(Pieza(b.inicio + a + a2, b.inicio + a + z2, forzado=True))
                else:
                    for a3, z3 in _por_palabras(sub2, presupuesto):
                        salida.append(Pieza(b.inicio + a + a2 + a3, b.inicio + a + a2 + z3,
                                            forzado=True))
    return salida


def agrupar(texto_doc: str, ps: list[Pieza], presupuesto: int) -> list[Pieza]:
    """Une piezas consecutivas de forma codiciosa mientras quepan en el presupuesto."""
    grupos: list[Pieza] = []
    for p in ps:
        if grupos:
            g = grupos[-1]
            if palabras(vigente(texto_doc[g.inicio:p.fin])) <= presupuesto:
                grupos[-1] = Pieza(g.inicio, p.fin, g.forzado or p.forzado)
                continue
        grupos.append(Pieza(p.inicio, p.fin, p.forzado))
    return grupos


def partir(texto_doc: str, bloques: list[Bloque], palabras_encabezado: int) -> list[Pieza]:
    # Margen de 3 palabras para el sufijo "(parte k/n)" del encabezado.
    presupuesto = max(50, LIMITE_PALABRAS - palabras_encabezado - 3)
    return agrupar(texto_doc, piezas(texto_doc, bloques, presupuesto), presupuesto)
