"""Pruebas de la fase 2 sin internet: un servidor falso imita las páginas del Senado."""
import json

import httpx
import pytest

from src.descarga.config import Config
from src.descarga.fuentes import base_senado, procesar
from src.descarga.http import Cliente
from src.descarga.manifest import CAMPOS_OBLIGATORIOS, Manifest
from src.descarga.texto import decodificar, html_a_markdown

BASE = "http://www.secretariasenado.gov.co/senado/basedoc/"
INDICE = "".join(f"<li>{i}</li>" for i in range(1, 60))

PAGINA_1 = f"""<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
<title>LEY_9999_2020</title><script>function insRow1(){{}}</script></head><body>
<p>Última actualización: 15 de septiembre de 2026 - (Diario Oficial No. 53.619)</p>
<p>Derechos de autor reservados - Prohibida su reproducción</p>
<div id="arbol"><p>Artículo</p><ul>{INDICE}</ul></div>
<a href="{BASE}ley_9999_2020_pr001.html">Siguiente</a>
<p>LEY 9999 DE 2020</p>
<p><a href="javascript:insRow1()">Resumen de Notas de Vigencia</a></p>
<div style="display: none">Nota oculta: artículo modificado por la Ley 2000 de 2022.</div>
<p>ARTÍCULO 1o. OBJETO. Esta ley regula la contestación de la demanda.</p>
<p><a href="{BASE}ley_9999_2020.html#top"><img src="up.jpg"></a></p>
<p>ARTÍCULO 2o. TÉRMINO. 7. &lt;Numeral modificado por el artículo
<a href="{BASE}ley_1996_2019.html#35">35</a> de la Ley 1996 de 2019. El nuevo texto es el siguiente:&gt;
El término será de diez (10) días.</p>
<p>4. &lt;Aparte tachado INEXEQUIBLE&gt; <strike>El Ministerio podrá</strike> También podrá asesorar.</p>
<p>Véase el artículo <a href="{BASE}codigo_civil_pr056.html#1824">1824</a> del Código Civil.</p>
</body></html>"""

PAGINA_2 = f"""<html><head><meta charset="iso-8859-1"></head><body>
<a href="{BASE}ley_9999_2020.html">Anterior</a>
<p>ARTÍCULO 3o. VIGENCIA. La presente ley rige a partir de su promulgación.</p>
<a href="{BASE}otra_ley_2021.html">Siguiente</a>
<p>Disposiciones analizadas por Avance Jurídico Casa Editorial S.A.S.©</p>
<p>Texto del pie que no debe aparecer.</p>
</body></html>"""


def servidor(request: httpx.Request) -> httpx.Response:
    rutas = {
        "/robots.txt": (404, b""),
        "/senado/basedoc/ley_9999_2020.html": (200, PAGINA_1.encode("cp1252")),
        "/senado/basedoc/ley_9999_2020_pr001.html": (200, PAGINA_2.encode("cp1252")),
    }
    estado, cuerpo = rutas.get(request.url.path, (404, b"no existe"))
    return httpx.Response(estado, content=cuerpo, headers={"content-type": "text/html"})


@pytest.fixture
def entorno(tmp_path):
    cfg = Config(raiz=tmp_path, intervalo_por_host=0)
    cliente = Cliente(cfg, transport=httpx.MockTransport(servidor))
    obj = {"doc_id": "ley_9999_2020", "titulo": "Ley 9999 de 2020", "fuente": "Senado",
           "url": BASE + "ley_9999_2020.html", "areas": ["procesal"], "tipo_norma": "ley"}
    yield cfg, cliente, obj
    cliente.cerrar()


def test_decodifica_windows_1252():
    texto, enc = decodificar("ARTÍCULO 1o. CONTESTACIÓN".encode("cp1252"), "text/html; charset=ISO-8859-1")
    assert texto == "ARTÍCULO 1o. CONTESTACIÓN" and enc == "cp1252"


def test_repara_mojibake():
    texto, _ = decodificar("CONTESTACIÓN".encode("utf-8").decode("cp1252").encode("cp1252"), "charset=cp1252")
    assert texto == "CONTESTACIÓN"


def test_base_senado():
    assert base_senado(BASE + "ley_1564_2012_pr003.html#391") == BASE + "ley_1564_2012.html"


def test_limpieza_html():
    r = html_a_markdown(PAGINA_1, BASE + "ley_9999_2020.html")
    md = r.markdown
    assert "ARTÍCULO 1o. OBJETO." in md
    assert "{{Numeral modificado por el artículo 35 de la Ley 1996 de 2019. El nuevo texto es el siguiente:}}" in md
    assert "~~El Ministerio podrá~~" in md
    assert "\n45\n" not in md                              # índice lateral eliminado
    assert "Nota oculta" not in md and any("Nota oculta" in n for n in r.notas)
    assert "Resumen de Notas" not in md and "Siguiente" not in md
    assert "Derechos de autor" not in md and "Última actualización" not in md
    assert r.siguiente == BASE + "ley_9999_2020_pr001.html"
    assert r.fecha_actualizacion_fuente.startswith("15 de septiembre de 2026")
    assert BASE + "codigo_civil_pr056.html#1824" in r.enlaces


def test_flujo_completo(entorno):
    cfg, cliente, obj = entorno
    reg = procesar(obj, cliente, cfg)
    assert reg["n_partes"] == 2                  # siguió _pr001 y no saltó a otra_ley_2021
    assert reg["n_articulos_detectados"] == 3
    assert reg["codificacion"] == ["cp1252"]
    md = (cfg.dir_md / "ley_9999_2020.md").read_text(encoding="utf-8")
    assert md.startswith("---\ndoc_id: ley_9999_2020")
    assert "Texto del pie" not in md
    assert (cfg.dir_raw / "ley_9999_2020" / "parte_000.html").exists()
    meta = json.loads((cfg.dir_raw / "ley_9999_2020" / "meta.json").read_text())
    assert len(meta["partes"][0]["sha256"]) == 64

    m = Manifest(cfg.ruta_manifest)
    m.actualizar(reg)
    guardado = json.loads(cfg.ruta_manifest.read_text(encoding="utf-8"))[0]
    assert all(guardado[c] for c in CAMPOS_OBLIGATORIOS)


def test_cache_y_solo_convertir(entorno):
    cfg, cliente, obj = entorno
    procesar(obj, cliente, cfg)
    sin_red = Cliente(cfg, transport=httpx.MockTransport(lambda r: pytest.fail("no debía descargar")))
    reg = procesar(obj, sin_red, cfg, solo_convertir=True)
    assert reg["n_partes"] == 2


def test_pdf_quita_encabezados_y_une_lineas(tmp_path):
    import pymupdf
    from src.descarga.texto import pdf_a_markdown
    doc = pymupdf.open()
    for i in range(5):
        p = doc.new_page()
        p.insert_text((50, 40), "Diario Oficial No. 48.489")
        p.insert_text((50, 55), "Ley 1564 de 2012")
        y = 100
        for k in range(3):
            n = i * 3 + k + 1
            p.insert_text((50, y), f"ARTÍCULO {n}o. El juez deberá resolver la solicitud número {n} y las")
            p.insert_text((50, y + 15), f"demás actuaciones del caso {n}.")
            y += 40
        p.insert_text((50, 800), f"Página {i + 1}")
    ruta = tmp_path / "doc.pdf"
    doc.save(ruta)
    r = pdf_a_markdown(ruta)
    assert r.metodo == "pdf_texto" and r.paginas == 5
    assert "Diario Oficial" not in r.markdown and "Página" not in r.markdown
    assert "número 1 y las demás actuaciones del caso 1." in r.markdown   # línea unida
    assert r.markdown.count("ARTÍCULO") == 15
