"""Motor de generación con llama.cpp (llama-cpp-python): temperatura 0, semilla fija y salida
guiada por JSON schema (gramática). Se eligió llama.cpp porque en hypatia los nodos GPU son
Quadro RTX 6000 (Turing, 24 GB) con driver CUDA 11.8, donde vLLM no corre.

llama_cpp se importa recién al crear el Motor, así el resto del paquete (prompts,
postproceso, pruebas) funciona sin GPU ni la librería instalada.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("generacion")

# alias -> (repo de Hugging Face con GGUF, patrón del archivo). Todos de ≤8.000 M de parámetros
# (restricción del reto). Q8_0 pesa ~1 GB por cada 1.000 M de parámetros: cabe en 24 GB.
MODELOS: dict[str, tuple[str, str]] = {
    "qwen3-8b": ("Qwen/Qwen3-8B-GGUF", "*Q8_0.gguf"),
    "llama-3.1-8b": ("bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "*Q8_0.gguf"),
    # BSC-LT solo publica salamandra-7b-instruct en Safetensors, no en GGUF; se usa la
    # conversión GGUF comunitaria de RichardErkhov, que sí trae un Q8_0.
    "salamandra-7b": ("RichardErkhov/BSC-LT_-_salamandra-7b-instruct-gguf", "*Q8_0.gguf"),
}
SEMILLA = 0


class Motor:
    def __init__(self, modelo: str = "qwen3-8b", n_ctx: int = 8192, n_gpu_layers: int = -1,
                 flash_attn: bool | None = None, verbose: bool | None = None):
        from llama_cpp import Llama
        if flash_attn is None:        # OLIVIA_FLASH_ATTN=0 la apaga (diagnóstico)
            flash_attn = os.environ.get("OLIVIA_FLASH_ATTN", "1") != "0"
        if verbose is None:           # OLIVIA_LLAMA_VERBOSE=1 muestra los mensajes de llama.cpp
            verbose = os.environ.get("OLIVIA_LLAMA_VERBOSE", "0") == "1"
        self.nombre = modelo
        self.admite_pensar = "qwen3" in modelo.lower()      # ChatML con bloque <think>
        if modelo in MODELOS:
            repo, patron = MODELOS[modelo]
            log.info("Cargando %s (%s, %s, n_ctx=%d)", modelo, repo, patron, n_ctx)
            self.llm = Llama.from_pretrained(repo_id=repo, filename=patron, n_ctx=n_ctx,
                                             n_gpu_layers=n_gpu_layers, flash_attn=flash_attn,
                                             seed=SEMILLA, verbose=verbose)
        else:                                   # ruta a un .gguf local
            log.info("Cargando %s (n_ctx=%d)", modelo, n_ctx)
            self.llm = Llama(model_path=modelo, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers,
                             flash_attn=flash_attn, seed=SEMILLA, verbose=verbose)

    def contar(self, texto: str) -> int:
        """Tokens reales del decoder (para el presupuesto del contexto, paso 6.7)."""
        return len(self.llm.tokenize(texto.encode("utf-8"), add_bos=False))

    def reiniciar(self) -> None:
        """Olvida el estado del contexto: el siguiente ítem se calcula desde cero, sin reutilizar
        el prefijo (sistema/few-shot) del ítem anterior. Con prefijo reutilizado los lotes de
        llama.cpp tienen otra forma y los logits cambian en el último decimal, así que un ítem
        podía salir distinto en la corrida por lote y en `src.responder --id N`."""
        self.llm.reset()
        ctx = getattr(self.llm, "_ctx", None)
        for nombre in ("kv_cache_clear", "memory_clear"):
            borrar = getattr(ctx, nombre, None)
            if borrar:
                try:
                    borrar() if nombre == "kv_cache_clear" else borrar(True)
                except Exception:                       # versión sin esa llamada: reset() basta
                    pass
                break

    def generar_lote(self, conversaciones: list[list[dict]], esquemas: list[dict],
                     max_tokens: int = 900, repeat_penalty: float | None = None) -> list[str]:
        """Una conversación y un esquema por ítem; devuelve el texto crudo de cada salida, en
        el mismo orden. llama.cpp atiende un ítem a la vez: los tiempos medidos son los reales.
        La gramática obliga a empezar en '{', así que Qwen3 no abre su bloque de pensamiento.
        `repeat_penalty` > 1 rompe los bucles de repetición de la decodificación voraz (solo
        se usa al reintentar una salida inválida; None deja el valor por defecto de la librería)."""
        extra = {} if repeat_penalty is None else {"repeat_penalty": repeat_penalty}
        salidas = []
        for mensajes, esquema in zip(conversaciones, esquemas):
            self.reiniciar()
            r = self.llm.create_chat_completion(
                messages=mensajes, response_format={"type": "json_object", "schema": esquema},
                temperature=0.0, seed=SEMILLA, max_tokens=max_tokens, **extra)
            salidas.append(r["choices"][0]["message"]["content"] or "")
        return salidas

    # ------------------------------------------------------------------ razonar y comprometer
    @staticmethod
    def chatml(mensajes: list[dict], inicio_respuesta: str = "") -> str:
        """Prompt ChatML (el formato de Qwen3 y de los Qwen en general) armado a mano: así se
        controla qué hay después de '<|im_start|>assistant' (por ejemplo '<think>\\n')."""
        texto = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in mensajes)
        return texto + "<|im_start|>assistant\n" + inicio_respuesta

    def _completar(self, prompt: str, max_tokens: int, stop: list[str] | None = None,
                   esquema: dict | None = None, repeat_penalty: float | None = None) -> tuple[str, str]:
        """(texto, motivo_de_fin). Con `esquema` la salida se fuerza a ese JSON."""
        extra = {} if repeat_penalty is None else {"repeat_penalty": repeat_penalty}
        if esquema is not None:
            from llama_cpp import LlamaGrammar
            extra["grammar"] = LlamaGrammar.from_json_schema(json.dumps(esquema))
        r = self.llm.create_completion(prompt=prompt, max_tokens=max_tokens, temperature=0.0,
                                       seed=SEMILLA, stop=stop, **extra)
        c = r["choices"][0]
        return c["text"] or "", c.get("finish_reason") or ""

    def pensar(self, mensajes: list[dict], esquema: dict, max_pensar: int = 1200,
               max_final: int = 700, repeat_penalty: float | None = 1.05,
               reiniciar: bool = True) -> dict:
        """Dos fases sobre el mismo contexto. (1) Razonamiento libre dentro de '<think>' hasta
        '</think>' o `max_pensar` tokens (si se pasa, se cierra a la fuerza: presupuesto).
        (2) Respuesta final forzada al JSON `esquema`, ya con el razonamiento delante.
        Devuelve {"razonamiento", "final" (texto JSON), "cortado" (bool), "tokens_pensar"}.
        `reiniciar=False` deja reutilizar el prefijo de la llamada anterior SOBRE EL MISMO ítem
        (determinista: lote e individual hacen la misma secuencia de llamadas)."""
        if reiniciar:
            self.reiniciar()
        prompt = self.chatml(mensajes, "<think>\n")
        razon, motivo = self._completar(prompt, max_pensar, stop=["</think>"],
                                        repeat_penalty=repeat_penalty)
        razon = razon.strip()
        cerrado = f"{prompt}{razon}\n</think>\n\n"
        final, _ = self._completar(cerrado, max_final, esquema=esquema)
        return {"razonamiento": razon, "final": final, "cortado": motivo == "length",
                "tokens_pensar": len(self.llm.tokenize(razon.encode("utf-8"), add_bos=False))}

    def probabilidades_letras(self, mensajes: list[dict], letras: list[str],
                              reiniciar: bool = True) -> dict[str, float]:
        """Probabilidad (softmax solo entre `letras`) de que la respuesta sea cada letra, sin
        razonamiento: el bloque de pensamiento va vacío y la respuesta arranca con "Respuesta:",
        así el siguiente token es la letra (sin ese ancla el modelo empieza con otra cosa y las
        letras salen casi uniformes). Se suma la masa de " A" y "A". Un solo prefill, sin generar."""
        import numpy as np
        from llama_cpp import LogitsProcessorList
        ids: dict[str, list[int]] = {}
        for l in letras:
            variantes = {self.llm.tokenize(v.encode("utf-8"), add_bos=False)[0] for v in (f" {l}", l)}
            ids[l] = sorted(variantes)
        capturado: dict = {}

        def captura(_ids, scores):
            capturado["logits"] = np.array(scores, dtype=np.float64)
            return scores

        if reiniciar:
            self.reiniciar()
        prompt = self.chatml(mensajes, "<think>\n\n</think>\n\nRespuesta:")
        self.llm.create_completion(prompt=prompt, max_tokens=1, temperature=0.0, seed=SEMILLA,
                                   logits_processor=LogitsProcessorList([captura]))
        lg = capturado["logits"]
        mx = lg.max()
        masa = np.array([sum(np.exp(lg[i] - mx) for i in ids[l]) for l in letras])
        p = masa / masa.sum()
        return {l: float(x) for l, x in zip(letras, p)}
