import re, unicodedata
from pathlib import Path
from charset_normalizer import from_bytes
from selectolax.parser import HTMLParser

BASURA  = ["script", "style", "nav", "header", "footer", "noscript", "form"]

def leer_html(path: Path) -> str:
    crudo = path.read_bytes()
    texto = str(from_bytes(crudo).best())
    if "Ã" in texto or "Â" in texto:
        print(f"[!] posible codificación errónea: {path.name}")
    return texto


def html_a_texto(html: str) -> str:
    tree = HTMLParser(html)
    for sel in BASURA:
        for n in tree.css(sel):
            n.decompose()
    return tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")


# Corrige espacios

def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto)
    texto = texto.replace("\xa0", " ").replace("\u200b", "").replace("\r", "")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()

