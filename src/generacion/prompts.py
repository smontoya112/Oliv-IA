"""Prompts en español, uno por formato, y armado del bloque de pasajes [P1]…[Pk]."""
from __future__ import annotations

from src.recuperacion import contexto

from . import cerradas

SISTEMA = """Eres un asistente jurídico experto en derecho colombiano. Respondes con rigor, \
en español, y SOLO con base en los pasajes numerados [P1], [P2]… que se te entregan.

Reglas:
1. Fundamenta la respuesta en los pasajes. No uses normas, artículos ni sentencias que no \
aparezcan en ellos.
2. Cita siempre la norma y el artículo con su nombre completo, por ejemplo: "artículo 88 de \
la Constitución Política", "Ley 472 de 1998, artículo 46", "Código General del Proceso, \
artículo 391", "Sentencia C-355 de 2006".
3. Si los pasajes no alcanzan para una conclusión segura, elige la alternativa mejor \
respaldada y dilo con claridad en el texto; no inventes fuentes.
4. Responde únicamente con un objeto JSON válido con los campos pedidos, sin texto adicional."""

SISTEMA_LIBRE = """Eres un asistente jurídico experto en derecho colombiano. Respondes con rigor y en \
español. Usa los pasajes numerados [P1], [P2]… como fuente principal y nombra la norma y el artículo \
con su nombre completo (por ejemplo "artículo 88 de la Constitución Política", "Ley 472 de 1998, \
artículo 46", "Sentencia C-355 de 2006"). Si ningún pasaje trata el punto que se pregunta, responde \
con lo que conozcas con seguridad del derecho colombiano; no inventes números de artículos ni \
sentencias. Responde únicamente con un objeto JSON válido con los campos pedidos."""

_FORMATOS = {
    "multiple_choice": """Pregunta de opción múltiple. Evalúa CADA opción por separado y luego \
elige UNA.
Campos del JSON, en este orden:
- "analisis_opciones": un objeto con una entrada por cada letra. Cada entrada tiene \
"veredicto" ("correcta" o "incorrecta") y "razon": una oración que confronte la opción con \
los pasajes y cite la norma y el artículo. Juzga cada opción por lo que afirma, no por el \
orden de los pasajes.
- "justificacion": 2 a 4 oraciones que expliquen por qué la opción elegida es la correcta y \
citen la norma y el artículo que la respaldan.
- "respuesta_correcta": la letra elegida. Debe ser una opción cuyo veredicto sea "correcta".
Opciones compuestas ("Todas las anteriores", "Ninguna de las anteriores", "A y B"): su \
veredicto depende de los veredictos de las opciones a las que remiten.""",
    "semi_open": """Pregunta semiabierta.
Campos del JSON:
- "respuesta": de 3 a 5 oraciones, máximo 150 palabras, directa y precisa; enuncia la regla \
aplicable y su fundamento con la norma y el artículo. Si la pregunta menciona una sentencia o \
norma concreta, nómbrala en la respuesta con su nombre completo (por ejemplo "Sentencia \
C-891 de 2012").
- "palabras_clave": entre 3 y 6 términos jurídicos clave de la respuesta.
- "referencia_legal": la norma y el artículo (o sentencia) que fundamentan la respuesta.""",
    "open_ended": """Pregunta abierta de análisis jurídico.
Campos del JSON:
- "marco_normativo": las normas y artículos aplicables, citados con precisión; si la \
pregunta menciona una norma o sentencia concreta, inclúyela con su nombre completo.
- "analisis": de 5 a 8 oraciones que apliquen el marco normativo a la pregunta.
- "jurisprudencia": las sentencias relevantes que aparezcan en los pasajes; si no hay \
ninguna, indícalo en una frase.
- "conclusion": una conclusión de 1 a 2 oraciones.""",
}


def formatear_pasajes(pasajes: list[dict], presupuesto_tokens: int = 4500, contar=None,
                      max_pasajes: int = 8) -> tuple[str, list[dict]]:
    """Bloque "[P1] doc_id ..." con los mejores pasajes, en el orden dado, hasta max_pasajes y
    sin pasar del presupuesto. La lógica vive en src.recuperacion.contexto (paso 6.7)."""
    return contexto.armar(pasajes, max_tokens=presupuesto_tokens, max_pasajes=max_pasajes,
                          contar=contar)


def construir_mensajes(item: dict, pasajes_texto: str,
                       ejemplos: list[dict] | None = None,
                       instrucciones: str | None = None,
                       sistema: str | None = None) -> list[dict]:
    """Mensajes de chat (system/user) para un ítem. `ejemplos` son turnos few-shot ya
    redactados por el equipo: [{"role": "user"|"assistant", "content": ...}, ...].
    `instrucciones` reemplaza el bloque de instrucciones del formato (prompt v2 por
    sub-tarea, src.generacion.subtarea)."""
    formato = item["formato"]
    if formato not in _FORMATOS:
        raise ValueError(f"formato desconocido: {formato!r}")
    partes = [f"Área: {item.get('area') or 'No indicada'}"]
    if item.get("tema"):
        partes.append(f"Tema: {item['tema'].strip()}")
    partes.append(f"Pregunta: {item['pregunta'].strip()}")
    if formato == "multiple_choice":
        tipos = cerradas.clasificar(item["opciones"])
        partes.append("Opciones:\n" + "\n".join(
            f"{k}. {v.strip()}{cerradas.nota_opcion(tipos[k])}"
            for k, v in sorted(item["opciones"].items())))
    usuario = (f"{instrucciones or _FORMATOS[formato]}\n\n=== PASAJES ===\n{pasajes_texto or '(sin pasajes)'}\n\n"
               "=== CONSULTA ===\n" + "\n".join(partes))
    return [{"role": "system", "content": sistema or SISTEMA}, *(ejemplos or []),
            {"role": "user", "content": usuario}]
