"""Paso 5.1: encoder denso BAAI/bge-m3.

Se usa `transformers` directamente (sin sentence-transformers): el vector denso de bge-m3
es el estado oculto del token [CLS] normalizado a norma 1, así que el producto interno de
FAISS equivale al coseno. Las consultas no llevan prefijo de instrucción.
"""
from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger("indice")

MODELO = "BAAI/bge-m3"
REVISION = "5617a9f61b028005a4858fdac845db406aefb181"   # commit de HF fijado (paso 12.2)
DIM = 1024
MAX_TOKENS = 512          # los chunks tienen <= 300 palabras + cabecera


class Encoder:
    def __init__(self, modelo: str = MODELO, revision: str = REVISION,
                 device: str | None = None, max_tokens: int = MAX_TOKENS):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = self.device.startswith("cuda")
        self.modelo, self.revision, self.max_tokens = modelo, revision, max_tokens
        self.tok = AutoTokenizer.from_pretrained(modelo, revision=revision)
        self.model = AutoModel.from_pretrained(
            modelo, revision=revision,
            dtype=torch.float16 if self.fp16 else torch.float32).to(self.device).eval()

    def longitudes(self, textos: list[str]) -> np.ndarray:
        """Tokens por texto (con especiales, sin truncar): para ordenar y para el reporte."""
        ids = self.tok(textos, add_special_tokens=True, truncation=False)["input_ids"]
        return np.fromiter((len(x) for x in ids), dtype=np.int32, count=len(textos))

    def encode(self, textos: list[str], batch: int = 32,
               longitudes: np.ndarray | None = None) -> np.ndarray:
        """Matriz (n, DIM) float32 normalizada, en el mismo orden de `textos`.

        Se procesa de mayor a menor longitud para que cada lote tenga poco relleno.
        """
        torch = self.torch
        n = len(textos)
        if longitudes is None:
            longitudes = self.longitudes(textos)
        orden = np.argsort(-longitudes, kind="stable")
        salida = np.empty((n, DIM), dtype=np.float32)
        t0, n_lotes = time.time(), (n + batch - 1) // batch
        with torch.inference_mode():
            for b, ini in enumerate(range(0, n, batch), start=1):
                idx = orden[ini:ini + batch]
                enc = self.tok([textos[i] for i in idx], padding=True, truncation=True,
                               max_length=self.max_tokens, return_tensors="pt").to(self.device)
                cls = self.model(**enc).last_hidden_state[:, 0]
                cls = torch.nn.functional.normalize(cls.float(), dim=-1)
                salida[idx] = cls.cpu().numpy()
                if b % 50 == 0 or b == n_lotes:
                    log.info("  encoding %d/%d lotes (%.0f s)", b, n_lotes, time.time() - t0)
        return salida

    def consultas(self, textos: list[str], batch: int = 32) -> np.ndarray:
        """Encoding de consultas (la fase 6 lo reutiliza). bge-m3 no usa prefijos."""
        return self.encode(textos, batch=batch)
