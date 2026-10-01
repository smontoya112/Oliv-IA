"""Pruebas de la fase 5: tokenizador BM25, índices, orden de filas y qrels."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from src.indice import denso, lexico   # añade scripts/ al path
import citations  # noqa: E402
from src.indice.build import leer_chunks, sha256
from src.indice.evaluar import _citas_chunk, _tupla, colapsar, consulta, rrf

CHUNKS = Path("data/processed/chunks.parquet")


# ------------------------------------------------------------ tokenizador
def test_tokenizar_conserva_numeros_y_quita_tildes():
    toks = lexico.tokenizar("ARTÍCULO 391 del Código General del Proceso (Ley 1564 de 2012)")
    assert toks == ["articulo", "391", "codigo", "general", "proceso", "ley", "1564", "2012"]


@pytest.mark.parametrize("texto,token", [
    ("Sentencia C-355 de 2006", "c355"),
    ("sentencia SU-488 de 2011", "su488"),
    ("Sentencia SL3385-2022", "sl3385"),
    ("T - 760 de 2008", "t760"),
])
def test_tokenizar_une_sentencias(texto, token):
    toks = lexico.tokenizar(texto)
    numero = token.lstrip("abcdefghijklmnopqrstuvwxyz")
    assert token in toks and numero in toks


def test_tokenizar_no_elimina_terminos_juridicos():
    toks = lexico.tokenizar("art. 5 de la ley, salvo el decreto; no procede sin ARTÍCULO 1o.")
    for t in ("art", "ley", "decreto", "salvo", "no", "sin", "1"):
        assert t in toks
    assert "1o" not in toks and "la" not in toks


def test_bm25_encuentra_por_numero():
    textos = ["Artículo 391 del CGP. Proceso verbal sumario.",
              "Sentencia C-355 de 2006. Interrupción voluntaria del embarazo.",
              "Artículo 80 de la Ley 80 de 1993. Contratación estatal."]
    r = lexico.construir(textos)
    scores, ids = lexico.buscar(r, ["C-355", "verbal sumario 391"], k=3)
    assert ids[0][0] == 1 and ids[1][0] == 0 and scores.shape == (2, 3)


# ------------------------------------------------------------ denso
def test_vectores_unicos_codifica_cada_texto_una_vez():
    llamadas = []

    def falso(textos):
        llamadas.append(list(textos))
        return np.eye(4, dtype=np.float32)[: len(textos)]

    emb, n = denso.vectores_unicos(["a", "b", "a", "c"], ["h1", "h2", "h1", "h3"], falso)
    assert n == 3 and llamadas == [["a", "b", "c"]]
    assert np.array_equal(emb[0], emb[2]) and not np.array_equal(emb[0], emb[1])
    scores, ids = denso.buscar(denso.construir(emb), emb[[1]], k=2)
    assert ids[0][0] == 1 and scores[0][0] == pytest.approx(1.0)


def test_verificar_orden_detecta_rechunking(tmp_path):
    denso.guardar_orden(tmp_path, ["a#p1", "b#p1"], "sha")
    denso.verificar_orden(tmp_path, ["a#p1", "b#p1"])
    with pytest.raises(RuntimeError, match="no corresponde"):
        denso.verificar_orden(tmp_path, ["a#p1", "c#p1"])


# ------------------------------------------------------------ evaluación
def test_colapsar_y_rrf():
    sha1 = ["x", "x", "y", "z"]
    rk = colapsar(np.array([3.0, 2.9, 1.0, 0.0]), np.array([0, 1, 2, 3]), sha1, k=10,
                  descartar_cero=True)
    assert rk == [(0, 3.0), (2, 1.0)]
    fusion = rrf([(0, 1.0), (2, 0.5)], [(2, 0.9), (3, 0.1)], k=2)
    assert fusion[0][0] == 2


def test_citas_de_cabecera_identifican_el_articulo():
    texto = ("Artículo 391 del Código General del Proceso (Ley 1564 de 2012). Libro Tercero.\n"
             "ARTÍCULO 391. Remite al artículo 82 del Código Civil.")
    cab, txt = (set(map(_tupla, x)) for x in _citas_chunk(texto))
    assert ("codigo_general_proceso", None, None, "391") in cab
    assert ("codigo_civil", None, None, "82") in txt - cab


def test_consulta_incluye_opciones_en_cerradas():
    it = {"formato": "multiple_choice", "pregunta": "¿Cuál?", "opciones": {"A": "uno", "B": "dos"}}
    assert consulta(it) == "¿Cuál?\nA) uno\nB) dos"
    assert consulta({"formato": "open_ended", "pregunta": "¿Por qué?"}) == "¿Por qué?"


# ------------------------------------------------------------ build de punta a punta
@pytest.mark.skipif(not CHUNKS.exists(), reason="falta data/processed/chunks.parquet")
def test_build_lexico_limitado(tmp_path):
    subprocess.run([sys.executable, "-m", "src.indice.build", "--limite", "50", "--solo", "lexico",
                    "--salida", str(tmp_path)], check=True, capture_output=True)
    cfg = json.loads((tmp_path / "index_config.json").read_text(encoding="utf-8"))
    assert cfg["n_chunks"] == 50 and cfg["sha256_chunks"] == sha256(CHUNKS)
    assert cfg["lexico"]["k1"] == lexico.K1 and cfg["denso"] is None
    ids = leer_chunks(CHUNKS, 50)["chunk_id"]
    denso.verificar_orden(tmp_path, ids)
    scores, top = lexico.buscar(lexico.cargar(tmp_path, ids), ["artículo"], k=5)
    assert top.shape == (1, 5)


@pytest.mark.skipif(not CHUNKS.exists(), reason="falta data/processed/chunks.parquet")
def test_qrels_cgp_tiene_chunk_relevante():
    """Una cita del CGP a nivel de artículo debe tener su chunk en el corpus."""
    import pyarrow.parquet as pq
    t = pq.read_table(CHUNKS, columns=["doc_id", "texto"],
                      filters=[("doc_id", "=", "ley_1564_2012")]).to_pydict()
    ref = citations.article_level(citations.extract("Código General del Proceso, artículo 25"))
    cabeceras = [set(map(_tupla, _citas_chunk(x)[0])) for x in t["texto"]]
    assert ref and any(ref & c for c in cabeceras)


def _modelo_diminuto(dir_: Path) -> Path:
    """XLM-R aleatorio de 2 capas y tokenizador WordLevel: prueba Encoder sin descargar bge-m3."""
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, XLMRobertaConfig, XLMRobertaModel

    from src.indice.encoder import DIM
    vocab = {w: i for i, w in enumerate(["<s>", "<pad>", "</s>", "<unk>", "ley", "art", "391",
                                         "proceso", "verbal", "sumario"])}
    tk = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    PreTrainedTokenizerFast(tokenizer_object=tk, bos_token="<s>", eos_token="</s>",
                            cls_token="<s>", sep_token="</s>", pad_token="<pad>",
                            unk_token="<unk>").save_pretrained(dir_)
    cfg = XLMRobertaConfig(vocab_size=len(vocab), hidden_size=DIM, num_hidden_layers=2,
                           num_attention_heads=4, intermediate_size=64, pad_token_id=1)
    XLMRobertaModel(cfg).save_pretrained(dir_)
    return dir_


def test_encoder_normaliza_y_respeta_el_orden(tmp_path):
    from src.indice.encoder import DIM, Encoder
    enc = Encoder(modelo=str(_modelo_diminuto(tmp_path)), revision=None, device="cpu")
    textos = ["ley", "proceso verbal sumario art 391", "art 391", "ley"]
    emb = enc.encode(textos, batch=2)
    assert emb.shape == (4, DIM) and emb.dtype == np.float32
    assert np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-5)
    uno_a_uno = np.vstack([enc.encode([t]) for t in textos])
    assert np.allclose(emb, uno_a_uno, atol=1e-4)     # el orden por longitud no cambia filas
    lon = enc.longitudes(["ley", "art 391"])
    assert lon[1] == lon[0] + 1
