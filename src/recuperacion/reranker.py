"""Paso 6.5: reranker BAAI/bge-reranker-v2-m3 (cross-encoder multilingüe, base XLM-R).

Recibe pares (consulta, pasaje) y devuelve un puntaje (logit) por par; no genera texto. Se usa
con `transformers` y fp16 en GPU, igual que el encoder de la fase 5. El commit exacto del
modelo se registra en retrieval_config.json (`commit`) para fijarlo después (paso 12.2).
"""
from __future__ import annotations

import logging

log = logging.getLogger("recuperacion")

MODELO = "BAAI/bge-reranker-v2-m3"


class Reranker:
    def __init__(self, modelo: str = MODELO, revision: str | None = None,
                 device: str | None = None, lote: int = 16, max_tokens: int = 512):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.lote, self.max_tokens = lote, max_tokens
        self.modelo = modelo
        self.tok = AutoTokenizer.from_pretrained(modelo, revision=revision)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            modelo, revision=revision,
            dtype=torch.float16 if self.device.startswith("cuda") else torch.float32,
        ).to(self.device).eval()
        self.commit = getattr(self.model.config, "_commit_hash", None) or revision
        log.info("reranker %s@%s en %s", modelo, (self.commit or "-")[:8], self.device)

    def recortar_consulta(self, consulta: str) -> str:
        """Consulta que cabe en la ventana: los primeros 96 y los últimos 160 tokens (el final de un caso suele traer las
        preguntas). Solo se usa cuando la consulta, por sí sola, no deja espacio al pasaje."""
        ids = self.tok(consulta, add_special_tokens=False)["input_ids"]
        return self.tok.decode(ids[:96] + ids[-160:])

    def puntuar(self, consulta: str, textos: list[str]) -> list[float]:
        """Un puntaje por texto, en el mismo orden (mayor = más relevante).

        Con `truncation="only_second"` solo se recorta el pasaje: si la consulta misma pasa de la ventana el tokenizador
        falla («Sequence to truncate too short») y, sin este respaldo, la pregunta se abstenía. Entonces (y solo entonces)
        se recorta la consulta; las demás consultas se puntúan exactamente igual que antes."""
        torch = self.torch
        salida: list[float] = []
        with torch.inference_mode():
            for ini in range(0, len(textos), self.lote):
                trozo = textos[ini:ini + self.lote]
                try:
                    enc = self.tok([consulta] * len(trozo), trozo, padding=True, truncation="only_second",
                                   max_length=self.max_tokens, return_tensors="pt")
                except Exception as e:
                    if "runcation" not in str(e):
                        raise
                    log.warning("consulta de %d caracteres no cabe en la ventana del reranker: se recorta", len(consulta))
                    consulta = self.recortar_consulta(consulta)
                    enc = self.tok([consulta] * len(trozo), trozo, padding=True, truncation="only_second",
                                   max_length=self.max_tokens, return_tensors="pt")
                enc = enc.to(self.device)
                salida += self.model(**enc).logits.view(-1).float().cpu().tolist()
        return salida
