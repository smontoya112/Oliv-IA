"""Motor de generación con llama.cpp (llama-cpp-python): temperatura 0, semilla fija y salida
guiada por JSON schema (gramática). Se eligió llama.cpp porque en hypatia los nodos GPU son
Quadro RTX 6000 (Turing, 24 GB) con driver CUDA 11.8, donde vLLM no corre.

llama_cpp se importa recién al crear el Motor, así el resto del paquete (prompts,
postproceso, pruebas) funciona sin GPU ni la librería instalada.
"""
from __future__ import annotations

import logging

log = logging.getLogger("generacion")

# alias -> (repo de Hugging Face con GGUF, patrón del archivo). Todos de ≤8.000 M de parámetros
# (restricción del reto). Q8_0 pesa ~1 GB por cada 1.000 M de parámetros: cabe en 24 GB.
MODELOS: dict[str, tuple[str, str]] = {
    "qwen3-8b": ("Qwen/Qwen3-8B-GGUF", "*Q8_0.gguf"),
    "llama-3.1-8b": ("bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "*Q8_0.gguf"),
    "salamandra-7b": ("BSC-LT/salamandra-7b-instruct-gguf", "*Q8_0*.gguf"),
}
SEMILLA = 0


class Motor:
    def __init__(self, modelo: str = "qwen3-8b", n_ctx: int = 8192, n_gpu_layers: int = -1):
        from llama_cpp import Llama
        self.nombre = modelo
        if modelo in MODELOS:
            repo, patron = MODELOS[modelo]
            log.info("Cargando %s (%s, %s, n_ctx=%d)", modelo, repo, patron, n_ctx)
            self.llm = Llama.from_pretrained(repo_id=repo, filename=patron, n_ctx=n_ctx,
                                             n_gpu_layers=n_gpu_layers, flash_attn=True,
                                             seed=SEMILLA, verbose=False)
        else:                                   # ruta a un .gguf local
            log.info("Cargando %s (n_ctx=%d)", modelo, n_ctx)
            self.llm = Llama(model_path=modelo, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers,
                             flash_attn=True, seed=SEMILLA, verbose=False)

    def contar(self, texto: str) -> int:
        """Tokens reales del decoder (para el presupuesto del contexto, paso 6.7)."""
        return len(self.llm.tokenize(texto.encode("utf-8"), add_bos=False))

    def generar_lote(self, conversaciones: list[list[dict]], esquemas: list[dict],
                     max_tokens: int = 900) -> list[str]:
        """Una conversación y un esquema por ítem; devuelve el texto crudo de cada salida, en
        el mismo orden. llama.cpp atiende un ítem a la vez: los tiempos medidos son los reales.
        La gramática obliga a empezar en '{', así que Qwen3 no abre su bloque de pensamiento."""
        salidas = []
        for mensajes, esquema in zip(conversaciones, esquemas):
            r = self.llm.create_chat_completion(
                messages=mensajes, response_format={"type": "json_object", "schema": esquema},
                temperature=0.0, seed=SEMILLA, max_tokens=max_tokens)
            salidas.append(r["choices"][0]["message"]["content"] or "")
        return salidas
