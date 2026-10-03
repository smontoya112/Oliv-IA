"""Recuperador y decoder falsos (sin GPU) que comparten test_responder y test_lote."""
import json

PASAJES = [
    {"doc_id": "constitucion", "inicio": 0, "fin": 50, "score": 4.2, "via": "hibrido",
     "texto": "Artículo 88 de la Constitución Política. Acciones populares y de grupo."},
    {"doc_id": "ley_472_1998", "inicio": 10, "fin": 90, "score": 3.1, "via": "directo",
     "texto": "Artículo 46 de la Ley 472 de 1998. Procedencia de la acción de grupo."},
]
CERRADA = ("¿En qué caso procede la acción de grupo?\n"
           "A) Para proteger derechos individuales.\n"
           "B) Cuando un grupo es afectado por una causa común.\n"
           "C) Para anular una ley.\n"
           "D) Para cobrar una deuda.")


class RecuperadorFalso:
    def recuperar(self, item):
        return {"pasajes": [dict(p) for p in PASAJES], "senales": {"score_top1": 4.2}}


class MotorFalso:
    """Devuelve JSON válido según el esquema pedido (sin vLLM ni llama.cpp)."""
    def generar_lote(self, conversaciones, esquemas, max_tokens=0):
        salidas = []
        for esq in esquemas:
            props = esq["properties"]
            if "analisis_opciones" in props:
                razones = {"A": "individual", "B": "causa común", "C": "no aplica", "D": "no aplica"}
                salidas.append(json.dumps({
                    "analisis_opciones": {l: {"veredicto": "correcta" if l == "B" else "incorrecta",
                                              "razon": r} for l, r in razones.items()},
                    "justificacion": "Según el artículo 46 de la Ley 472 de 1998 procede por causa común.",
                    "respuesta_correcta": "B"}))
            elif "palabras_clave" in props:
                salidas.append(json.dumps({
                    "respuesta": "La acción de grupo procede por una causa común. Está en la Ley 472 de 1998.",
                    "palabras_clave": ["acción de grupo", "causa común"],
                    "referencia_legal": "Artículo 88 de la Constitución Política; Ley 80 de 1993."}))
            else:
                salidas.append(json.dumps({"marco_normativo": "Constitución Política, artículo 88.",
                                           "analisis": "Primero. Segundo. Tercero.",
                                           "jurisprudencia": "No hay.", "conclusion": "Procede."}))
        return salidas
