"""Motor de generación con vLLM: temperatura 0, semilla fija, salida guiada por JSON schema,
ejecución offline por lotes (LLM.chat). vLLM se importa recién al crear el Motor, así el resto
del paquete (prompts, postproceso, pruebas) funciona sin GPU."""
from __future__ import annotations

import logging

log = logging.getLogger("generacion")

# Todos de 8.000 millones de parámetros o menos (restricción del reto).
MODELOS = {
    "qwen3-8b": "Qwen/Qwen3-8B",
    "llama-3.1-8b": "meta-llama/Llama-3.1-8B-Instruct",
    "salamandra-7b": "BSC-LT/salamandra-7b-instruct",
}
SEMILLA = 0


def _params_guiados(esquema: dict, max_tokens: int):
    """SamplingParams con salida estructurada; cubre las dos APIs de vLLM
    (structured_outputs en las versiones nuevas, guided_decoding en las anteriores)."""
    from vllm import SamplingParams
    base = dict(temperature=0.0, seed=SEMILLA, max_tokens=max_tokens)
    try:
        from vllm.sampling_params import StructuredOutputsParams
        return SamplingParams(**base, structured_outputs=StructuredOutputsParams(json=esquema))
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams
        return SamplingParams(**base, guided_decoding=GuidedDecodingParams(json=esquema))


class Motor:
    def __init__(self, modelo: str = "qwen3-8b", max_model_len: int = 8192,
                 gpu_memory_utilization: float = 0.90, dtype: str = "auto"):
        from vllm import LLM
        self.nombre = modelo
        self.ruta = MODELOS.get(modelo, modelo)
        log.info("Cargando %s (max_model_len=%d)", self.ruta, max_model_len)
        self.llm = LLM(model=self.ruta, dtype=dtype, seed=SEMILLA,
                       max_model_len=max_model_len,
                       gpu_memory_utilization=gpu_memory_utilization)

    def generar_lote(self, conversaciones: list[list[dict]], esquemas: list[dict],
                     max_tokens: int = 900) -> list[str]:
        """Una conversación y un esquema por ítem; devuelve el texto crudo de cada salida,
        en el mismo orden. Qwen3 se ejecuta sin modo de pensamiento."""
        params = [_params_guiados(e, max_tokens) for e in esquemas]
        salidas = self.llm.chat(conversaciones, params,
                                chat_template_kwargs={"enable_thinking": False}, use_tqdm=False)
        return [s.outputs[0].text for s in salidas]
