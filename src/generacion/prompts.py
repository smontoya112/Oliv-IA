"""Prompts en español, uno por formato, y armado del bloque de pasajes [P1]…[Pk]."""
from __future__ import annotations

from src.recuperacion import contexto

SISTEMA = """Eres un asistente jurídico experto en derecho colombiano. Respondes con rigor, \
en español, y SOLO con base en los pasajes numerados [P1], [P2]… que se te entregan.

Reglas:
1. Fundamenta la respuesta en los pasajes. No uses normas, artículos ni sentencias que no \
aparezcan en ellos.
2. Cita siempre la norma y el artículo con su nombre completo, por ejemplo: "artículo 88 de \
la Constitución Política", "Ley 472 de 1998, artículo 46", "Código General del Proceso, \
artículo 391", "Sentencia C-355 de 2006".
3. Responde siempre con el dato más específico y literal que SÍ aparezca en los pasajes \
(el número de artículo o numeral exacto, la cifra, el nombre de la sentencia, el sí/no), \
aunque la respuesta sea parcial. No escribas frases sobre la falta o suficiencia de \
información ("no se encuentra en los pasajes", "no se especifica", etc.): elige y cita el \
fragmento más cercano a lo preguntado sin inventar fuentes que no estén en los pasajes.
4. Empieza la respuesta por el dato puntual que se pregunta (el número, el nombre, el sí/no) \
y luego el fundamento; evita rodeos o contexto general que no se haya pedido.
5. Responde únicamente con un objeto JSON válido con los campos pedidos, sin texto adicional."""

_FORMATOS = {
    "multiple_choice": """Pregunta de opción múltiple. Elige UNA opción (A, B, C o D).
Campos del JSON, en este orden:
- "justificacion": 2 a 4 oraciones que expliquen por qué la opción elegida es la correcta y \
citen la norma y el artículo que la respaldan.
- "respuesta_correcta": la letra elegida.
- "descarte_opciones": un objeto con las letras de las opciones INCORRECTAS como llaves y, \
como valor, una razón breve de por qué se descarta (no incluyas la letra elegida).""",
    "semi_open": """Pregunta semiabierta.
Campos del JSON:
- "respuesta": de 1 a 5 oraciones, máximo 150 palabras. La primera oración debe dar \
directamente el dato puntual que se pregunta (el número, la cifra, el nombre, el sí/no) \
con la norma y el artículo; el resto, si hace falta, amplía el fundamento. No agregues \
contexto general que no se haya pedido.
- "palabras_clave": entre 3 y 6 términos jurídicos clave de la respuesta.
- "referencia_legal": la norma y el artículo (o sentencia) que fundamentan la respuesta.""",
    "open_ended": """Pregunta abierta de análisis jurídico.
Campos del JSON:
- "marco_normativo": las normas y artículos aplicables, citados con precisión.
- "analisis": de 5 a 8 oraciones que apliquen el marco normativo al caso concreto de la \
pregunta (hechos, partes, cifras mencionadas), no una explicación genérica de la norma.
- "jurisprudencia": las sentencias relevantes que aparezcan en los pasajes; si no hay \
ninguna, indícalo en una frase.
- "conclusion": la respuesta puntual al caso en 1 a 2 oraciones (qué procede, quién tiene \
razón, o el valor pedido), no una reflexión general.""",
}


def formatear_pasajes(pasajes: list[dict], presupuesto_tokens: int = 4500, contar=None,
                      max_pasajes: int = 8) -> tuple[str, list[dict]]:
    """Bloque "[P1] doc_id ..." con los mejores pasajes, en el orden dado, hasta max_pasajes y
    sin pasar del presupuesto. La lógica vive en src.recuperacion.contexto (paso 6.7)."""
    return contexto.armar(pasajes, max_tokens=presupuesto_tokens, max_pasajes=max_pasajes,
                          contar=contar)


def construir_mensajes(item: dict, pasajes_texto: str,
                       ejemplos: list[dict] | None = None) -> list[dict]:
    """Mensajes de chat (system/user) para un ítem. `ejemplos` son turnos few-shot ya
    redactados por el equipo: [{"role": "user"|"assistant", "content": ...}, ...]."""
    formato = item["formato"]
    if formato not in _FORMATOS:
        raise ValueError(f"formato desconocido: {formato!r}")
    partes = [f"Área: {item.get('area') or 'No indicada'}"]
    if item.get("tema"):
        partes.append(f"Tema: {item['tema'].strip()}")
    partes.append(f"Pregunta: {item['pregunta'].strip()}")
    if formato == "multiple_choice":
        partes.append("Opciones:\n" + "\n".join(
            f"{k}. {v.strip()}" for k, v in sorted(item["opciones"].items())))
    usuario = (f"{_FORMATOS[formato]}\n\n=== PASAJES ===\n{pasajes_texto or '(sin pasajes)'}\n\n"
               "=== CONSULTA ===\n" + "\n".join(partes))
    return [{"role": "system", "content": SISTEMA}, *(ejemplos or []),
            {"role": "user", "content": usuario}]
