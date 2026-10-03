"""Fase 11: responder una pregunta de punta a punta (recuperación + generación).

    python -m src.responder --id 512                      # busca el id en test_992 / sample_50
    python -m src.responder --id 51 --comparar submissions.jsonl     # prueba de la verificación en vivo
    python -m src.responder --pregunta "¿Qué es la acción de tutela?"
    python -m src.responder --id 51 --solo-recuperar      # sin cargar el decoder (depuración)

Usa EXACTAMENTE el mismo camino que la corrida por lotes (src.recuperacion.Recuperador y
src.generacion.pipeline.generar): mismos prompts, misma recuperación, misma gramática, temperatura
0 y semilla fija. Por eso lo que se regenera en vivo coincide con lo entregado. El modelo del
decoder sale de config/responder.json (o de la variable OLIVIA_MODELO).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import src.recuperacion  # noqa: F401  (agrega scripts/ al path)
import normalizacion

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = RAIZ / "config" / "responder.json"
PREGUNTAS_POR_DEFECTO = [Path("data/test_992.jsonl"), Path("data/sample_50.jsonl")]
FORMATOS = ("multiple_choice", "semi_open", "open_ended")
MENSAJE_ABSTENCION = ("No encuentro fundamento suficiente en mi corpus para responder esta "
                      "pregunta con seguridad.")

log = logging.getLogger("responder")


# ------------------------------------------------------------------ configuración
def cargar_config() -> dict:
    cfg = {"modelo": "qwen3-8b", "indice": "data/index", "n_ctx": 8192,
           "max_caracteres_pregunta": 6000, "palabras_caso_largo": 120}
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    if os.environ.get("OLIVIA_MODELO"):
        cfg["modelo"] = os.environ["OLIVIA_MODELO"]
    return cfg


# ------------------------------------------------------------------ entrada libre -> ítem
_OPCION_LINEA = re.compile(r"^\s*\(?([A-Da-d])[\)\.\-:]\s+(\S.*)$")
_OPCION_EN_LINEA = re.compile(r"(?:^|\s)\(?([A-Da-d])[\)\.]\s+")


def extraer_opciones(texto: str) -> tuple[str, dict[str, str]]:
    """Separa "enunciado + opciones A) B) C) D)". Devuelve (enunciado, opciones) o (texto, {})
    si no hay al menos tres opciones consecutivas desde la A."""
    enunciado, opciones, ultima = [], {}, None
    for linea in texto.splitlines():
        m = _OPCION_LINEA.match(linea)
        if m and m.group(1).upper() not in opciones:
            ultima = m.group(1).upper()
            opciones[ultima] = m.group(2).strip()
        elif opciones and linea.strip() and ultima:        # continuación de la opción anterior
            opciones[ultima] += " " + linea.strip()
        elif not opciones:
            enunciado.append(linea)
    if not _validas(opciones):                              # opciones en una sola línea: A) … B) …
        marcas = [(m.group(1).upper(), m.start(), m.end()) for m in _OPCION_EN_LINEA.finditer(texto)]
        letras = [l for l, _, _ in marcas]
        if letras[:3] == ["A", "B", "C"] and letras == sorted(letras):
            opciones = {l: texto[e:(marcas[k + 1][1] if k + 1 < len(marcas) else len(texto))].strip()
                        for k, (l, _, e) in enumerate(marcas)}
            enunciado = [texto[: marcas[0][1]]]
    if not _validas(opciones):
        return texto.strip(), {}
    return "\n".join(enunciado).strip(), opciones


def _validas(opciones: dict) -> bool:
    return all(l in opciones for l in "ABC") and all(opciones.values())


def preparar_item(entrada, formato: str | None = None, opciones: dict | None = None,
                  palabras_caso_largo: int = 120) -> dict:
    """Texto libre o dict -> ítem con la forma de data/*.jsonl (id, formato, pregunta, opciones).
    El formato explícito manda; si no, se deduce: con opciones es cerrada, un caso largo es
    abierta y el resto semiabierta."""
    if isinstance(entrada, dict):
        item = dict(entrada)
        formato = formato or item.get("formato")
        opciones = opciones or item.get("opciones")
        texto = item.get("pregunta") or ""
    else:
        item, texto = {}, str(entrada or "")
    texto = texto.strip()
    if not texto:
        raise ValueError("la pregunta está vacía")
    if not opciones and formato in (None, "multiple_choice"):
        texto, opciones = extraer_opciones(texto)
    if formato not in FORMATOS:
        formato = ("multiple_choice" if opciones
                   else "open_ended" if len(texto.split()) > palabras_caso_largo else "semi_open")
    if formato == "multiple_choice" and not opciones:
        raise ValueError("una pregunta de opción múltiple necesita opciones A), B), C)")
    item.update({"id": item.get("id", 0), "formato": formato, "pregunta": texto})
    if formato == "multiple_choice":
        item["opciones"] = {k.upper(): v for k, v in opciones.items()}
    else:
        item.pop("opciones", None)
    return item


# ------------------------------------------------------------------ salida
def texto_respuesta(sub: dict, item: dict | None = None) -> str:
    """Texto legible de una respuesta (lo que muestra la interfaz)."""
    if sub.get("abstencion"):
        return MENSAJE_ABSTENCION
    f = sub["formato"]
    if f == "multiple_choice":
        letra = sub.get("respuesta_correcta") or ""
        opcion = ((item or {}).get("opciones") or {}).get(letra, "")
        partes = [f"Respuesta: {letra}. {opcion}".strip(), sub.get("justificacion") or ""]
        if sub.get("descarte_opciones"):
            partes.append("Por qué no las demás:\n" + "\n".join(
                f"{k}: {v}" for k, v in sorted(sub["descarte_opciones"].items())))
        return "\n\n".join(p for p in partes if p)
    if f == "semi_open":
        claves = ", ".join(sub.get("palabras_clave") or [])
        return "\n\n".join(p for p in (
            sub.get("respuesta"), f"Referencia legal: {sub['referencia_legal']}"
            if sub.get("referencia_legal") else "", f"Palabras clave: {claves}" if claves else "") if p)
    return "\n\n".join(f"{etq}: {sub[k]}" for etq, k in (
        ("Marco normativo", "marco_normativo"), ("Análisis", "analisis"),
        ("Jurisprudencia", "jurisprudencia"), ("Conclusión", "conclusion")) if sub.get(k))


def texto_citable(sub: dict) -> str:
    """Texto del que se extraen las citas (el mismo criterio que scripts/evaluate.answer_text)."""
    f = sub.get("formato")
    if f == "multiple_choice":
        return sub.get("justificacion") or ""
    if f == "semi_open":
        return " ".join(str(sub.get(k) or "") for k in ("respuesta", "referencia_legal"))
    return " ".join(str(sub.get(k) or "") for k in
                    ("marco_normativo", "analisis", "jurisprudencia", "conclusion"))


def normas_citadas(sub: dict, pasajes: list[dict]) -> list[dict]:
    """[{norma, respaldada}]: normas (ids de la fase 4) citadas en la respuesta y si alguno de
    los 10 primeros pasajes trae esa norma (a nivel de cuerpo normativo, como el evaluador)."""
    citadas = normalizacion.extract_canonical(texto_citable(sub))
    respaldo = set()
    for p in pasajes[:10]:
        respaldo |= {c.split("#")[0] for c in normalizacion.extract_canonical(p.get("texto") or "")}
    return [{"norma": c, "respaldada": c.split("#")[0] in respaldo} for c in sorted(citadas)]


def responder_item(item: dict, rec: dict, motor, catalogo=None) -> dict:
    """Línea de submissions.jsonl de un ítem ya recuperado. Es el ÚNICO camino de generación:
    lo usan Responder (verificación en vivo, interfaz) y la corrida por lotes (src.lote), así
    que no pueden divergir. La fase 8 (citas y abstención) ocurre dentro de `ensamblar`, con
    las señales de la recuperación y el catálogo para respaldar citas con el corpus."""
    from src.generacion.pipeline import generar
    return generar(item, rec["pasajes"], motor, senales_por_id={item["id"]: rec["senales"]},
                   catalogo=catalogo)


# ------------------------------------------------------------------ el respondedor
class Responder:
    """Carga una sola vez el recuperador y el decoder. `recuperador` y `motor` se pueden
    inyectar (pruebas)."""

    def __init__(self, cfg: dict | None = None, recuperador=None, motor=None):
        self.cfg = cfg or cargar_config()
        self._rec, self._motor = recuperador, motor

    @property
    def recuperador(self):
        if self._rec is None:
            from src.recuperacion.pipeline import Recuperador
            self._rec = Recuperador(RAIZ / self.cfg["indice"])
        return self._rec

    @property
    def motor(self):
        if self._motor is None:
            from src.generacion.motor import Motor
            self._motor = Motor(self.cfg["modelo"], n_ctx=self.cfg["n_ctx"])
        return self._motor

    @property
    def catalogo(self):
        """El catálogo de chunks que ya cargó el recuperador (None con un recuperador falso)."""
        return getattr(self.recuperador, "cat", None)

    def cargar(self, con_motor: bool = True) -> "Responder":
        """Fuerza la carga de los modelos (para pagar el arranque antes de la primera pregunta)."""
        self.recuperador
        if con_motor:
            self.motor
        return self

    def responder(self, entrada, formato: str | None = None, opciones: dict | None = None,
                  solo_recuperar: bool = False) -> dict:
        item = preparar_item(entrada, formato, opciones, self.cfg["palabras_caso_largo"])
        t0 = time.perf_counter()
        rec = self.recuperador.recuperar(item)
        if solo_recuperar:
            sub = {"id": item["id"], "formato": item["formato"], "abstencion": False,
                   "pasajes_recuperados": rec["pasajes"]}
        else:
            sub = responder_item(item, rec, self.motor, self.catalogo)
        return {
            "item": item,
            "submission": sub,
            "formato": item["formato"],
            "abstencion": bool(sub.get("abstencion")),
            "respuesta": "" if solo_recuperar else texto_respuesta(sub, item),
            "pasajes": rec["pasajes"],
            "normas_citadas": [] if solo_recuperar else normas_citadas(sub, rec["pasajes"]),
            "senales": rec["senales"],
            "latencia_ms": int((time.perf_counter() - t0) * 1000),
        }


# ------------------------------------------------------------------ verificación en vivo
def buscar_por_id(ident: int, rutas: list[Path]) -> dict | None:
    for ruta in rutas:
        if ruta.exists():
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                if linea.strip():
                    it = json.loads(linea)
                    if it.get("id") == ident:
                        return it
    return None


def _ids_pasajes(pasajes: list[dict]) -> list[tuple]:
    return [(p["doc_id"], p.get("inicio"), p.get("fin")) for p in pasajes[:10]]


def comparar(vivo: dict, entregado: dict) -> dict:
    """Lo que revisa el jurado: normas citadas y pasajes recuperados, más la respuesta."""
    sub = vivo["submission"]
    normas_v = {n["norma"] for n in normas_citadas(sub, vivo["pasajes"])}
    normas_e = {n["norma"] for n in normas_citadas(entregado, entregado.get("pasajes_recuperados") or [])}
    pas_v, pas_e = _ids_pasajes(sub["pasajes_recuperados"]), _ids_pasajes(
        entregado.get("pasajes_recuperados") or [])
    ignorar = {"latencia_ms"}
    return {
        "normas_coinciden": normas_v == normas_e,
        "solo_en_vivo": sorted(normas_v - normas_e), "solo_en_entrega": sorted(normas_e - normas_v),
        "pasajes_coinciden": set(pas_v) == set(pas_e), "mismo_orden": pas_v == pas_e,
        "pasajes_en_comun": len(set(pas_v) & set(pas_e)), "pasajes_entrega": len(pas_e),
        "respuesta_identica": {k: v for k, v in sub.items() if k not in ignorar}
                              == {k: v for k, v in entregado.items() if k not in ignorar},
    }


def _logs() -> None:
    """Avance -> stdout; solo los ERROR -> stderr (convención de los jobs)."""
    salida = logging.StreamHandler(sys.stdout)
    salida.addFilter(lambda r: r.levelno < logging.ERROR)
    errores = logging.StreamHandler(sys.stderr)
    errores.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[salida, errores])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int, help="id de la pregunta en --preguntas")
    g.add_argument("--pregunta", help="texto libre (con opciones A) B) C) D) si es cerrada)")
    ap.add_argument("--preguntas", type=Path, nargs="+", default=PREGUNTAS_POR_DEFECTO)
    ap.add_argument("--modelo", help="alias del decoder (por defecto config/responder.json)")
    ap.add_argument("--comparar", type=Path, help="submissions.jsonl contra el que verificar")
    ap.add_argument("--json", action="store_true", help="imprimir solo la línea de submissions.jsonl")
    ap.add_argument("--solo-recuperar", action="store_true", help="no cargar el decoder")
    args = ap.parse_args()
    _logs()

    cfg = cargar_config()
    if args.modelo:
        cfg["modelo"] = args.modelo
    if args.id is not None:
        entrada = buscar_por_id(args.id, args.preguntas)
        if entrada is None:
            log.error("no encontré el id %s en %s", args.id, [str(r) for r in args.preguntas])
            return 2
    else:
        entrada = args.pregunta

    t0 = time.perf_counter()
    resp = Responder(cfg).cargar(con_motor=not args.solo_recuperar)
    arranque = time.perf_counter() - t0
    r = resp.responder(entrada, solo_recuperar=args.solo_recuperar)

    if args.json:
        print(json.dumps(r["submission"], ensure_ascii=False))
    else:
        print(f"[{r['formato']}] id={r['item']['id']}  (arranque {arranque:.1f} s, "
              f"respuesta {r['latencia_ms'] / 1000:.1f} s)")
        if r["respuesta"]:
            print("\n" + r["respuesta"])
        if r["normas_citadas"]:
            print("\nNormas citadas: " + ", ".join(
                f"{n['norma']}{'' if n['respaldada'] else ' (SIN respaldo)'}" for n in r["normas_citadas"]))
        print(f"\nPasajes recuperados ({len(r['pasajes'])}):")
        for i, p in enumerate(r["pasajes"], start=1):
            print(f"  [P{i}] {p['doc_id']} {p.get('norma_id', '')}  score {p.get('score')}  {p.get('via', '')}")
        print("\n" + json.dumps(r["submission"], ensure_ascii=False))

    if args.comparar:
        entregado = buscar_por_id(args.id, [args.comparar]) if args.id is not None else None
        if entregado is None:
            log.error("no hay una línea con id %s en %s para comparar", args.id, args.comparar)
            return 2
        c = comparar(r, entregado)
        print("\nCOMPARACIÓN CON LA ENTREGA")
        print(f"  normas citadas: {'coinciden' if c['normas_coinciden'] else 'DIFIEREN'}"
              + ("" if c["normas_coinciden"] else f"  solo en vivo {c['solo_en_vivo']}  solo en entrega {c['solo_en_entrega']}"))
        print(f"  pasajes: {c['pasajes_en_comun']}/{c['pasajes_entrega']} en común"
              f" ({'mismo orden' if c['mismo_orden'] else 'orden distinto'})")
        print(f"  respuesta idéntica (salvo latencia): {'sí' if c['respuesta_identica'] else 'no'}")
        return 0 if c["normas_coinciden"] and c["pasajes_coinciden"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
