"""Descarga y conversión de un documento objetivo.

Estructura en disco:
    data/raw/<doc_id>/parte_000.html|pdf   bytes originales, sin tocar
    data/raw/<doc_id>/meta.json            URL, SHA-256, codificación y fecha de cada parte
    data/raw/<doc_id>/enlaces.json         enlaces salientes (para descubrir fuentes)
    data/md/<doc_id>.md                    Markdown limpio con front matter JSON
    data/md/<doc_id>.notas.md              contenido oculto (notas de vigencia), aparte
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config
from .http import Cliente, ErrorDescarga
from .metadatos import completar
from .texto import (decodificar, detectar_formato, doc_a_markdown, docx_a_markdown,
                    html_a_markdown, pdf_a_markdown)

log = logging.getLogger(__name__)

TIPOS = {"senado", "html", "html_js", "pdf"}
_PAGINA_SENADO = re.compile(r"_pr\d{3}(?=\.html?$)", re.I)
_ENCABEZADO_ARTICULO = re.compile(r"^\s*(?:#+\s*)?ART[ÍI]CULO\s+\d+", re.I | re.M)
_SOSPECHOSOS = re.compile(r"pregunta|quiz|examen|simulacro|banco|cuestionario|test", re.I)


def base_senado(url: str) -> str:
    """ley_1564_2012_pr003.html#391 -> ley_1564_2012.html (sin fragmento)."""
    return _PAGINA_SENADO.sub("", url.split("#")[0])


def inferir_tipo(obj: dict) -> str:
    if obj.get("tipo"):
        return obj["tipo"]
    url = obj["url"].lower()
    if "secretariasenado.gov.co" in url:
        return "senado"
    if url.split("?")[0].endswith(".pdf"):
        return "pdf"
    return "html"


def validar_objetivo(obj: dict) -> list[str]:
    errores = []
    # titulo, fuente y areas son opcionales: si faltan, se completan al leer el documento.
    for campo in ("doc_id", "url"):
        if not obj.get(campo):
            errores.append(f"falta '{campo}'")
    if obj.get("doc_id") and not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", obj["doc_id"]):
        errores.append("doc_id solo admite minúsculas, números, '_' y '-'")
    if obj.get("tipo") and obj["tipo"] not in TIPOS:
        errores.append(f"tipo debe ser uno de {sorted(TIPOS)}")
    if obj.get("areas") and not isinstance(obj["areas"], list):
        errores.append("'areas' debe ser una lista")
    return errores


def _ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# ------------------------------------------------------------------- descarga
def _pagina_vacia(contenido: bytes, ctype: str) -> bool:
    """Algunos sitios responden 200 con una página de 'no encontrado'."""
    if contenido[:5] == b"%PDF-":
        return False
    texto, _ = decodificar(contenido, ctype)
    return len(html_a_markdown(texto, "").markdown) < 1500


def _primera_url(obj: dict, tipo: str, cliente: Cliente, verify: bool):
    """Prueba la URL principal y luego las alternativas. Devuelve (url, contenido, ctype, estado)."""
    candidatas = [obj["url"]] + list(obj.get("urls_alternativas") or [])
    ultimo = None
    for url in candidatas:
        try:
            if tipo == "html_js":
                contenido, ctype = cliente.get_renderizado(url)
                estado = 200
            else:
                r = cliente.get(url, verify=verify)
                contenido, ctype, estado = r.content, r.headers.get("content-type", ""), r.status_code
        except ErrorDescarga as e:
            if e.estado in (404, 410) and url != candidatas[-1]:
                log.info("  %s no existe, probando alternativa", url)
                ultimo = e
                continue
            raise
        if len(candidatas) > 1 and url != candidatas[-1] and _pagina_vacia(contenido, ctype):
            log.info("  %s respondió una página casi vacía, probando alternativa", url)
            continue
        return url, contenido, ctype, estado
    raise ultimo or ErrorDescarga(f"Ninguna URL candidata tuvo contenido para {obj['doc_id']}")


def _descargar(obj: dict, tipo: str, cliente: Cliente, cfg: Config, dir_doc: Path) -> dict:
    verify = obj.get("verificar_ssl", True)
    partes, visitadas = [], set()
    url, *pendiente = _primera_url(obj, tipo, cliente, verify)
    url_efectiva = url
    base = base_senado(url_efectiva)
    seguir = obj.get("seguir_paginas", tipo == "senado")

    while url and url.split("#")[0] not in visitadas and len(partes) < cfg.max_paginas:
        visitadas.add(url.split("#")[0])
        if pendiente:                       # la primera página ya se descargó al probar URLs
            contenido, ctype, estado = pendiente
            pendiente = None
        elif tipo == "html_js":
            contenido, ctype = cliente.get_renderizado(url)
            estado = 200
        else:
            r = cliente.get(url, verify=verify)
            contenido, ctype, estado = r.content, r.headers.get("content-type", ""), r.status_code

        formato = detectar_formato(contenido, ctype)
        es_pdf = formato == "pdf"
        archivo = f"parte_{len(partes):03d}.{formato}"
        (dir_doc / archivo).write_bytes(contenido)
        partes.append({"archivo": archivo, "url": url, "sha256": _sha256(contenido),
                       "bytes": len(contenido), "content_type": ctype,
                       "http_status": estado, "descargado": _ahora()})
        log.info("  %s  %s (%d KB)", archivo, url, len(contenido) // 1024)

        if formato != "html" or not seguir:
            break
        texto, _ = decodificar(contenido, ctype)
        siguiente = html_a_markdown(texto, url).siguiente
        # Solo se sigue la paginación dentro del mismo documento.
        url = siguiente if siguiente and base_senado(siguiente) == base else None

    meta = {"doc_id": obj["doc_id"], "url": url_efectiva, "tipo": tipo, "partes": partes}
    (dir_doc / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return meta


# ------------------------------------------------------------------ conversión
def _convertir(obj: dict, meta: dict, cfg: Config, dir_doc: Path) -> dict:
    bloques, notas, enlaces, titulo_html = [], [], [], None
    metodos, codificaciones, fecha_fuente = set(), set(), None

    for p in meta["partes"]:
        ruta = dir_doc / p["archivo"]
        encabezado = f"<!-- parte {p['archivo']} | {p['url']} -->"
        bruto = ruta.read_bytes()
        # El formato real se decide por los bytes, no por la extensión con que se guardó
        # (descargas antiguas de Word quedaron como parte_000.html).
        formato = detectar_formato(bruto, p.get("content_type"))
        if formato != "html" and ruta.suffix != f".{formato}":
            nueva = ruta.with_suffix(f".{formato}")
            ruta.rename(nueva)
            p["archivo"], ruta = nueva.name, nueva
            (dir_doc / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
            encabezado = f"<!-- parte {p['archivo']} | {p['url']} -->"
        if formato in ("pdf", "docx", "doc"):
            convertir_binario = {"pdf": lambda r: pdf_a_markdown(r, cfg.ocr_idioma),
                                 "docx": docx_a_markdown, "doc": doc_a_markdown}[formato]
            r = convertir_binario(ruta)
            metodos.add(r.metodo)
            bloques.append(f"{encabezado}\n{r.markdown}")
        else:
            texto, enc = decodificar(bruto, p.get("content_type"))
            codificaciones.add(enc)
            r = html_a_markdown(texto, p["url"])
            metodos.add("html")
            bloques.append(f"{encabezado}\n{r.markdown}")
            notas.extend(r.notas)
            enlaces.extend(r.enlaces)
            fecha_fuente = fecha_fuente or r.fecha_actualizacion_fuente
            titulo_html = titulo_html or r.titulo

    cuerpo = "\n\n".join(bloques)
    n_articulos = len(_ENCABEZADO_ARTICULO.findall(cuerpo))
    fecha_consulta = meta["partes"][0]["descargado"][:10]
    obj = {**obj, "url": meta.get("url", obj["url"])}
    autocompletados = completar(obj, titulo_html, cuerpo)

    registro = {
        "doc_id": obj["doc_id"],
        "titulo": obj["titulo"],
        "fuente": obj["fuente"],
        "url": obj["url"],
        "fecha_consulta": fecha_consulta,
        "areas": obj["areas"],
        "tipo_norma": obj.get("tipo_norma"),
        "numero": obj.get("numero"),
        "anio": obj.get("anio"),
        "organo_emisor": obj.get("organo_emisor"),
        "canonico": obj.get("canonico"),
        "items_del_banco": obj.get("items_del_banco"),
        "formato_origen": sorted(metodos),
        "codificacion": sorted(codificaciones),
        "ocr": "pdf_ocr" in metodos,
        "n_partes": len(meta["partes"]),
        "urls_partes": [p["url"] for p in meta["partes"]],
        "sha256_partes": [p["sha256"] for p in meta["partes"]],
        "fecha_actualizacion_fuente": fecha_fuente,
        "n_caracteres": len(cuerpo),
        "n_articulos_detectados": n_articulos,
        "archivo_md": f"md/{obj['doc_id']}.md",
        "metadata_autocompletada": autocompletados,
        "advertencias": [m for m in sorted(metodos) if m in ("pdf_sin_texto", "pdf_texto_ilegible")],
        "estado": "ok",
    }

    cfg.dir_md.mkdir(parents=True, exist_ok=True)
    # JSON con sangría: además es YAML válido, así que cualquier lector de front matter lo entiende.
    front = json.dumps({k: v for k, v in registro.items() if k != "estado"},
                       ensure_ascii=False, indent=2) + "\n"
    (cfg.dir_md / f"{obj['doc_id']}.md").write_text(f"---\n{front}---\n\n{cuerpo}",
                                                   encoding="utf-8")
    if notas:
        (cfg.dir_md / f"{obj['doc_id']}.notas.md").write_text(
            "\n\n---\n\n".join(notas) + "\n", encoding="utf-8")
    (dir_doc / "enlaces.json").write_text(
        json.dumps(sorted(set(enlaces)), ensure_ascii=False, indent=2), encoding="utf-8")
    return registro


# ------------------------------------------------------------------- principal
def procesar(obj: dict, cliente: Cliente, cfg: Config, forzar: bool = False,
             solo_convertir: bool = False) -> dict:
    tipo = inferir_tipo(obj)
    dir_doc = cfg.dir_raw / obj["doc_id"]
    dir_doc.mkdir(parents=True, exist_ok=True)
    ruta_meta = dir_doc / "meta.json"

    if _SOSPECHOSOS.search(obj["url"]):
        log.warning("%s: la URL parece material con preguntas o respuestas. Revísenla: "
                    "indexar ese material es causal de descalificación.", obj["doc_id"])

    if ruta_meta.exists() and not forzar:
        meta = json.loads(ruta_meta.read_text(encoding="utf-8"))
        log.info("%s: usando descarga en caché (%d partes)", obj["doc_id"], len(meta["partes"]))
    elif solo_convertir:
        raise ErrorDescarga(f"{obj['doc_id']}: no hay descarga previa para convertir")
    else:
        log.info("%s: descargando (%s)", obj["doc_id"], tipo)
        meta = _descargar(obj, tipo, cliente, cfg, dir_doc)

    return _convertir(obj, meta, cfg, dir_doc)


def dominio(url: str) -> str:
    return urlsplit(url).netloc.lower()
