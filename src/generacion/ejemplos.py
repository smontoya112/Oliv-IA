"""Paso 7.3: ejemplos few-shot propios, uno por formato (cerrado, semiabierto, abierto),
redactados a mano con casos simples y verificables para que el modelo vea el patrón exacto
de salida esperado (campos, orden, estilo de cita) antes de responder la consulta real.

Cada entrada de EJEMPLOS es [turno_usuario, turno_asistente]: el turno de usuario se arma
con prompts.construir_mensajes() (el mismo camino que una consulta real) para que el
ejemplo luzca idéntico a como el modelo ve las preguntas de verdad, incluido el bloque de
pasajes [P1]... Si el texto de los prompts cambia, el ejemplo se actualiza solo.
"""
from __future__ import annotations

import json

from .prompts import construir_mensajes

_MC = {"formato": "multiple_choice", "area": "Derecho procesal",
       "pregunta": "¿Cuál es el término para contestar la demanda en el proceso verbal, según "
                   "el Código General del Proceso?",
       "opciones": {"A": "Diez (10) días", "B": "Veinte (20) días", "C": "Treinta (30) días",
                    "D": "Cinco (5) días"}}
_MC_PASAJES = ("[P1] ley_1564_2012\nArtículo 369. Traslado de la demanda. El juez correrá "
               "traslado de la demanda al demandado por el término de veinte (20) días, para "
               "que la conteste, proponga excepciones y solicite pruebas.")
_MC_RESPUESTA = {
    "justificacion": "El artículo 369 del Código General del Proceso (Ley 1564 de 2012) fija en "
                     "veinte días el traslado de la demanda en el proceso verbal, término dentro "
                     "del cual el demandado debe contestarla.",
    "respuesta_correcta": "B",
    "descarte_opciones": {
        "A": "Diez días no corresponde al término fijado por el artículo 369 de la Ley 1564 de 2012.",
        "C": "Treinta días excede el plazo que establece el artículo 369 del CGP.",
        "D": "Cinco días es insuficiente y no está previsto por la norma citada.",
    },
}

_SEMI = {"formato": "semi_open", "area": "Derecho civil",
         "pregunta": "¿Cuándo se configura la mora del deudor según el Código Civil?"}
_SEMI_PASAJES = ("[P1] ley_84_1873\nArtículo 1608. El deudor está en mora: 1o.) Cuando no ha "
                 "cumplido la obligación dentro del término estipulado... 3o.) En los demás "
                 "casos, cuando el deudor ha sido judicialmente reconvenido por el acreedor.")
_SEMI_RESPUESTA = {
    "respuesta": "El deudor incurre en mora cuando no cumple la obligación dentro del plazo "
                "pactado, o, si no hay plazo, cuando el acreedor lo reconviene judicialmente "
                "sin que medie cumplimiento. El artículo 1608 del Código Civil regula estos "
                "supuestos.",
    "palabras_clave": ["mora", "incumplimiento", "reconvención judicial"],
    "referencia_legal": "Código Civil (Ley 84 de 1873), artículo 1608",
}

_ABIERTA = {"formato": "open_ended", "area": "Derecho constitucional",
            "pregunta": "Analice la procedencia de la acción de tutela contra particulares que "
                        "prestan un servicio público."}
_ABIERTA_PASAJES = ("[P1] decreto_2591_1991\nArtículo 42. Procedencia. La acción de tutela "
                    "procederá contra acciones u omisiones de particulares... cuando el "
                    "particular preste un servicio público del cual dependa el ejercicio del "
                    "derecho fundamental.")
_ABIERTA_RESPUESTA = {
    "marco_normativo": "Artículo 86 de la Constitución Política y artículo 42 del Decreto 2591 "
                       "de 1991.",
    "analisis": "El artículo 86 de la Constitución habilita la tutela contra particulares en los "
               "casos que señale la ley. El artículo 42 del Decreto 2591 de 1991 desarrolla esa "
               "habilitación y la extiende, entre otros casos, a los particulares que prestan "
               "un servicio público del cual depende el goce del derecho fundamental invocado.",
    "jurisprudencia": "No hay pronunciamientos jurisprudenciales en los pasajes suministrados.",
    "conclusion": "La tutela sí procede frente a particulares prestadores de un servicio "
                 "público, siempre que se cumplan los demás requisitos de subsidiariedad e "
                 "inmediatez.",
}


def _ejemplo(item: dict, pasajes_texto: str, respuesta: dict) -> list[dict]:
    usuario = construir_mensajes(item, pasajes_texto)[-1]
    return [usuario, {"role": "assistant", "content": json.dumps(respuesta, ensure_ascii=False)}]


EJEMPLOS: dict[str, list[dict]] = {
    "multiple_choice": _ejemplo(_MC, _MC_PASAJES, _MC_RESPUESTA),
    "semi_open": _ejemplo(_SEMI, _SEMI_PASAJES, _SEMI_RESPUESTA),
    "open_ended": _ejemplo(_ABIERTA, _ABIERTA_PASAJES, _ABIERTA_RESPUESTA),
}
