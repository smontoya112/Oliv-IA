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
    assert md.startswith("---\n{") and '"doc_id": "ley_9999_2020"' in md
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


def test_prueba_urls_alternativas(tmp_path):
    buena = f"{BASE}ley_9999_2020.html"

    def srv(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if str(request.url) == buena:
            return httpx.Response(200, content=PAGINA_1.encode("cp1252"),
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)

    cfg = Config(raiz=tmp_path, intervalo_por_host=0, reintentos=1)
    cliente = Cliente(cfg, transport=httpx.MockTransport(srv))
    obj = {"doc_id": "x", "titulo": "X", "fuente": "S", "areas": ["civil"], "tipo": "html",
           "seguir_paginas": False, "url": f"{BASE}no_existe.html", "urls_alternativas": [buena]}
    reg = procesar(obj, cliente, cfg)
    assert reg["url"] == buena and reg["n_partes"] == 1


def test_conversor_seed():
    from src.descarga.seed_a_fuentes import convertir
    seed = {"documentos": [
        {"norma": "Ley 80 de 1993", "canonico": ["ley", "80", "1993"], "items_del_banco": 12,
         "areas": ["Derecho administrativo"], "donde_buscar": "x"},
        {"norma": "Sentencia SU-214 de 2016", "canonico": ["jurisprudencia", "SU-214", "2016"],
         "items_del_banco": 2, "areas": ["Derecho de familia"], "donde_buscar": "x"},
        {"norma": "Sentencia SL-3385 de 2022", "canonico": ["jurisprudencia", "SL-3385", "2022"],
         "items_del_banco": 4, "areas": ["Derecho laboral"], "donde_buscar": "x"},
        {"norma": "Ley 11500 de 2007", "canonico": ["ley", "11500", "2007"], "items_del_banco": 1,
         "areas": ["Derecho constitucional"], "donde_buscar": "x"},
    ]}
    listas, pendientes = convertir(seed)
    assert listas[0]["url"].endswith("ley_0080_1993.html") and listas[0]["areas"] == ["administrativo"]
    assert listas[1]["url"].endswith("/2016/SU214-16.htm")
    assert listas[1]["urls_alternativas"][0].endswith("/2016/SU-214-16.htm")
    assert {p["norma"] for p in pendientes} == {"Sentencia SL-3385 de 2022", "Ley 11500 de 2007"}


def test_objetivo_desde_url():
    from src.descarga.metadatos import objetivo_desde_url
    o = objetivo_desde_url(BASE + "ley_0080_1993.html")
    assert (o["doc_id"], o["numero"], o["anio"], o["canonico"]) == ("ley_80_1993", "80", 1993, ["ley", "80", "1993"])
    o = objetivo_desde_url("https://www.corteconstitucional.gov.co/relatoria/2006/C-355-06.htm")
    assert o["doc_id"] == "sentencia_c-355_2006" and o["canonico"] == ["jurisprudencia", "C-355", "2006"]
    assert o["fuente"] == "Relatoría de la Corte Constitucional"
    assert objetivo_desde_url("https://ejemplo.gov.co/x/Mi%20Norma.PDF")["doc_id"] == "mi_norma"


def test_enlaces_txt_completa_metadata(tmp_path):
    from src.descarga.metadatos import hacer_ids_unicos, leer_enlaces, objetivo_desde_url
    ruta = tmp_path / "enlaces.txt"
    ruta.write_text(f"# comentario\n\n{BASE}ley_9999_2020.html  # inline\n{BASE}ley_9999_2020.html\n",
                    encoding="utf-8")
    urls = leer_enlaces(ruta)
    assert urls == [BASE + "ley_9999_2020.html"]                 # sin repetidos ni comentarios
    obj = objetivo_desde_url(urls[0])
    hacer_ids_unicos([obj], set())
    cfg = Config(raiz=tmp_path, intervalo_por_host=0)
    cliente = Cliente(cfg, transport=httpx.MockTransport(servidor))
    reg = procesar(obj, cliente, cfg)
    cliente.cerrar()
    assert reg["doc_id"] == "ley_9999_2020" and reg["tipo_norma"] == "ley" and reg["anio"] == 2020
    assert reg["fuente"] == "Secretaría General del Senado"
    assert reg["titulo"] and reg["areas"]
    assert {"titulo", "areas"} <= set(reg["metadata_autocompletada"])
    Manifest(cfg.ruta_manifest).actualizar(reg)                  # cumple los campos obligatorios


def test_enlace_invalido(tmp_path):
    from src.descarga.metadatos import leer_enlaces
    ruta = tmp_path / "e.txt"
    ruta.write_text("no-es-un-link\n", encoding="utf-8")
    with pytest.raises(ValueError):
        leer_enlaces(ruta)



def test_docx_conserva_tildes_y_se_detecta_por_bytes(tmp_path):
    import io
    import zipfile
    from src.descarga.texto import detectar_formato, docx_a_markdown
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           '<w:p><w:r><w:t>ARTÍCULO 1o. Señor magistrado: la acción de nulidad</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Ñandú, corazón y jurisdicción</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    datos = buf.getvalue()
    assert detectar_formato(datos, "text/html") == "docx"      # aunque diga text/html
    assert detectar_formato(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 10) == "doc"
    assert detectar_formato(b"<html></html>") == "html"
    ruta = tmp_path / "x.docx"
    ruta.write_bytes(datos)
    md = docx_a_markdown(ruta).markdown
    assert "Señor magistrado" in md and "Ñandú, corazón y jurisdicción" in md and "\ufffd" not in md


def test_detecta_capa_de_texto_ilegible():
    from src.descarga.texto import _capa_ilegible
    assert _capa_ilegible(["Decidela Corte 島nal prorerido C血nara Ⅳ珊 ！" * 20])
    assert not _capa_ilegible(["ARTÍCULO 1o. Señor magistrado: ¿qué dice la ley? “Sí”." * 20])


# ------------------------------------------------------------- rondas de proximidad
def _descubiertos(ruta, filas):
    import csv
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "veces_enlazada", "n_documentos", "enlazada_desde"])
        for url, n in filas:
            w.writerow([url, n, 1, "x"])


def test_ronda_omite_lo_intentado_y_acumula(tmp_path):
    from src.descarga.proximidad import nueva_ronda
    desc, man, acum = tmp_path / "d.csv", tmp_path / "m.json", tmp_path / "acum.txt"
    _descubiertos(desc, [(BASE + "ley_1_2000.html", 9), (BASE + "ley_2_2000.html", 5),
                         (BASE + "ley_3_2000.html", 2), (BASE + "ley_4_2000.html", 1)])
    man.write_text(json.dumps([
        {"doc_id": "a", "url": BASE + "ley_1_2000.html", "estado": "ok"},          # ya descargada
        {"doc_id": "b", "url": BASE + "ley_2_2000.html", "estado": "error"},       # fallida: no se reintenta en otra ronda
    ]), encoding="utf-8")
    archivo, nuevos, ya = nueva_ronda(desc, man, acum, tmp_path / "rondas", 1, minimo=0, maximo=None)
    assert [u.rsplit("/", 1)[1] for u, _ in nuevos] == ["ley_3_2000.html", "ley_4_2000.html"] and ya == 2
    assert archivo.name == "ronda_01.txt" and "ley_3_2000" in archivo.read_text(encoding="utf-8")
    assert acum.read_text(encoding="utf-8").count("ley_") == 2
    # repetir la misma ronda (p. ej. tras una interrupción) no duplica el acumulado
    nueva_ronda(desc, man, acum, tmp_path / "rondas", 1, minimo=0, maximo=None)
    assert acum.read_text(encoding="utf-8").count("ley_3_2000") == 1
    # --minimo y --max
    _, n2, _ = nueva_ronda(desc, man, tmp_path / "otro.txt", tmp_path / "rondas", 2, minimo=1, maximo=None)
    assert [u.rsplit("/", 1)[1] for u, _ in n2] == ["ley_3_2000.html"]
    _, n3, _ = nueva_ronda(desc, man, tmp_path / "otro2.txt", tmp_path / "rondas", 3, minimo=0, maximo=1)
    assert len(n3) == 1 and n3[0][1] == 2                       # el más enlazado entre los pendientes


def test_ronda_sin_manifest_y_pendientes_de_una_ronda_interrumpida(tmp_path):
    from src.descarga.proximidad import nueva_ronda
    desc = tmp_path / "d.csv"
    _descubiertos(desc, [(BASE + "ley_7_2001.html", 3)])
    # una ronda anterior listó el link en el acumulado pero nunca llegó a descargarlo (no está en el manifest)
    acum = tmp_path / "acum.txt"
    acum.write_text(f"{BASE}ley_7_2001.html  # ronda 1\n", encoding="utf-8")
    _, nuevos, _ = nueva_ronda(desc, tmp_path / "no_hay_manifest.json", acum, tmp_path / "r", 2, 0, None)
    assert len(nuevos) == 1                                     # se vuelve a ofrecer: lo que decide es el manifest


# ------------------------------------------- identidad de una norma (duplicados del corpus)
DIAN = "https://normograma.dian.gov.co/dian/compilacion/docs/"


def test_claves_unifican_las_variantes_de_una_misma_norma():
    from src.descarga.claves import clave_url
    misma = [BASE + "ley_0599_2000.html", BASE + "ley_0599_2000_pr012.html#5",
             "https://secretariasenado.gov.co/senado/basedoc/ley/2000/ley_0599_2000_pr003.html",
             DIAN + "ley_0599_2000.htm", BASE + "ley_599_2000.html"]
    assert {clave_url(u) for u in misma} == {"ley_599_2000"}
    assert clave_url(BASE + "ley_0600_2000.html") != "ley_599_2000"
    assert (clave_url("https://www.corteconstitucional.gov.co/relatoria/2006/C-355-06.htm")
            == clave_url("http://corteconstitucional.gov.co/relatoria/2006/c-355-06.htm")
            == "sentencia_C-355_2006")
    assert (clave_url("https://www.suin-juriscol.gov.co/viewDocument.asp?ruta=Acuerdo/30034638")
            != clave_url("https://www.suin-juriscol.gov.co/viewDocument.asp?ruta=Acuerdo/30034639"))


def test_un_link_ya_descargado_reutiliza_su_id_en_vez_de_duplicarse(tmp_path):
    from src.descarga.run import objetivos_desde_enlaces
    ruta = tmp_path / "enlaces_proximidad.txt"
    ruta.write_text(f"{BASE}ley_0009_2002.html\n{DIAN}ley_0009_2002.htm\n{BASE}ley_0010_2002.html\n",
                    encoding="utf-8")
    registros = [{"doc_id": "ley_9_2002", "url": BASE + "ley_0009_2002.html", "estado": "ok"}]
    nuevos = objetivos_desde_enlaces(ruta, [], registros)
    # ley 9: mismo documento -> mismo id (se sirve del caché); la copia de la DIAN se omite; ley 10 es nueva
    assert [o["doc_id"] for o in nuevos] == ["ley_9_2002", "ley_10_2002"]
    assert nuevos[0]["origen"] == "enlaces_proximidad"
    # volver a correrlo no cambia nada: es idempotente
    registros.append({"doc_id": "ley_10_2002", "url": BASE + "ley_0010_2002.html", "estado": "ok"})
    assert [o["doc_id"] for o in objetivos_desde_enlaces(ruta, [], registros)] == ["ley_9_2002", "ley_10_2002"]


def test_sufijo_solo_si_el_id_es_de_otra_norma(tmp_path):
    from src.descarga.run import objetivos_desde_enlaces
    ruta = tmp_path / "r.txt"
    ruta.write_text(BASE + "ley_0009_2002.html\n", encoding="utf-8")
    # el id ley_9_2002 ya pertenece a OTRA norma (otra URL, otra clave): ahí sí hace falta el sufijo
    registros = [{"doc_id": "ley_9_2002", "url": "https://x.gov.co/algo.html", "estado": "ok"}]
    assert objetivos_desde_enlaces(ruta, [], registros)[0]["doc_id"] == "ley_9_2002-2"


def test_ronda_no_relista_la_misma_norma_con_otra_url(tmp_path):
    from src.descarga.proximidad import nueva_ronda
    desc, man = tmp_path / "d.csv", tmp_path / "m.json"
    _descubiertos(desc, [(DIAN + "ley_0599_2000.htm", 40), (BASE + "ley_0599_2000.html", 30),
                         (BASE + "ley_0700_2001.html", 5), (DIAN + "ley_0700_2001.htm", 9),
                         (BASE + "ley_0800_2002.html", 2)])
    man.write_text(json.dumps([{"doc_id": "codigo_penal", "estado": "ok",
                                "canonico": ["codigo_penal", None, None],
                                "url": BASE + "ley_0599_2000.html"}]), encoding="utf-8")
    _, nuevos, _ = nueva_ronda(desc, man, tmp_path / "a.txt", tmp_path / "r", 1, 0, None)
    # la 599 ya está (bajo otra URL); de la 700 queda UNA sola URL, la del Senado; luego la 800
    assert [u.rsplit("/", 1)[1] for u, _ in nuevos] == ["ley_0700_2001.html", "ley_0800_2002.html"]


def test_descubiertos_junta_las_variantes_y_omite_lo_ya_incluido(tmp_path):
    from src.descarga.config import Config
    from src.descarga.manifest import Manifest
    from src.descarga.run import actualizar_descubiertos
    cfg = Config(raiz=tmp_path)
    (cfg.dir_raw / "d1").mkdir(parents=True)
    (cfg.dir_raw / "d2").mkdir(parents=True)
    (cfg.dir_raw / "d1" / "enlaces.json").write_text(json.dumps(
        [BASE + "ley_0080_1993.html", BASE + "ley_0081_1994.html", DIAN + "ley_0081_1994.htm"]),
        encoding="utf-8")
    (cfg.dir_raw / "d2" / "enlaces.json").write_text(
        json.dumps([BASE + "ley_0081_1994_pr002.html#3"]), encoding="utf-8")
    man = Manifest(cfg.ruta_manifest)
    man.docs["ley_80_1993"] = {"doc_id": "ley_80_1993", "url": BASE + "ley_0080_1993.html", "estado": "ok"}
    assert actualizar_descubiertos(cfg, [], man) == 1                # la 80 ya está; la 81 cuenta una vez
    fila = cfg.ruta_descubiertos.read_text(encoding="utf-8").splitlines()[1].split(",")
    assert fila[0].endswith("ley_0081_1994.html") and "secretariasenado" in fila[0] and fila[1] == "3"


# ------------------------------------------------------------------------ deduplicar
def _crear_doc(cfg, doc_id, url, texto, **extra):
    (cfg.dir_raw / doc_id).mkdir(parents=True, exist_ok=True)
    (cfg.dir_raw / doc_id / "enlaces.json").write_text("[]", encoding="utf-8")
    cfg.dir_md.mkdir(parents=True, exist_ok=True)
    (cfg.dir_md / f"{doc_id}.md").write_text("---\n{}\n---\n\n" + texto, encoding="utf-8")
    return {"doc_id": doc_id, "url": url, "estado": "ok", "n_articulos_detectados": 10,
            "n_caracteres": len(texto), **extra}


def test_deduplicar_conserva_uno_por_norma_y_mueve_las_copias(tmp_path):
    from src.descarga.config import Config
    from src.descarga.deduplicar import agrupar, aplicar, elegir
    from src.descarga.manifest import Manifest
    cfg = Config(raiz=tmp_path)
    texto = "ARTÍCULO 1o. Objeto de la ley. " * 40
    man = Manifest(cfg.ruta_manifest)
    senado_viejo = "https://secretariasenado.gov.co/senado/basedoc/ley/1993/ley_0080_1993_pr001.html"
    man.docs.update({
        "ley_80_1993": _crear_doc(cfg, "ley_80_1993", BASE + "ley_0080_1993.html", texto),
        "ley_80_1993-2": _crear_doc(cfg, "ley_80_1993-2", DIAN + "ley_0080_1993.htm", texto + "x",
                                    origen="ronda_01"),
        "ley_80_1993-3": _crear_doc(cfg, "ley_80_1993-3", senado_viejo, texto, origen="ronda_02"),
        # otra URL que las claves no relacionan, pero con el MISMO texto: lo detecta la huella del texto
        "copia_texto": _crear_doc(cfg, "copia_texto", "https://espejo.example.org/doc.html", texto),
        "ley_81_1994": _crear_doc(cfg, "ley_81_1994", BASE + "ley_0081_1994.html", "Otra ley distinta. " * 80),
    })
    grupos = agrupar(man.docs, cfg.dir_md)
    assert len(grupos) == 1 and set(grupos[0]) == {"ley_80_1993", "ley_80_1993-2", "ley_80_1993-3", "copia_texto"}
    assert elegir(man.docs, grupos[0]) == "ley_80_1993"              # lista inicial + Senado gana
    assert agrupar(man.docs, None) == [["ley_80_1993", "ley_80_1993-2", "ley_80_1993-3"]]   # sin mirar el texto

    informe = aplicar(cfg, man, grupos, tmp_path / "descartados")
    assert informe[0]["conservado"] == "ley_80_1993" and len(informe[0]["descartados"]) == 3
    assert set(man.docs) == {"ley_80_1993", "ley_81_1994"}
    assert (cfg.dir_md / "ley_80_1993.md").exists() and not (cfg.dir_md / "ley_80_1993-2.md").exists()
    assert (tmp_path / "descartados" / "md" / "ley_80_1993-2.md").exists()           # movido, no borrado
    assert (tmp_path / "descartados" / "raw" / "ley_80_1993-3" / "enlaces.json").exists()
    assert not (cfg.dir_raw / "ley_80_1993-3").exists()
    guardado = {r["doc_id"] for r in json.loads(cfg.ruta_manifest.read_text(encoding="utf-8"))}
    assert guardado == {"ley_80_1993", "ley_81_1994"}


def test_deduplicar_junta_codigos_con_su_ley():
    from src.descarga.deduplicar import agrupar, elegir
    registros = {
        "estatuto_tributario": {"doc_id": "estatuto_tributario", "estado": "ok", "n_articulos_detectados": 900,
                                "canonico": ["decreto", "624", "1989"], "url": BASE + "estatuto_tributario.html"},
        "decreto_624_1989": {"doc_id": "decreto_624_1989", "estado": "ok", "origen": "ronda_01",
                             "canonico": ["decreto", "624", "1989"], "n_articulos_detectados": 900,
                             "url": BASE + "decreto_0624_1989.html"},
        "ley_1_2000": {"doc_id": "ley_1_2000", "estado": "ok", "url": BASE + "ley_0001_2000.html"},
    }
    g = agrupar(registros)
    assert g == [["decreto_624_1989", "estatuto_tributario"]] and elegir(registros, g[0]) == "estatuto_tributario"
