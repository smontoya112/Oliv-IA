"""Cliente HTTP educado: robots.txt, límite de velocidad por host, reintentos
con espera exponencial y, opcionalmente, un navegador (Playwright) para
páginas que se construyen con JavaScript."""
from __future__ import annotations

import logging
import random
import time
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

from .config import Config

log = logging.getLogger(__name__)
REINTENTABLES = {429, 500, 502, 503, 504}


class ErrorDescarga(Exception):
    pass


class Cliente:
    def __init__(self, cfg: Config, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport          # permite inyectar un MockTransport en pruebas
        self._clientes: dict[bool, httpx.Client] = {}
        self._ultimo_acceso: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._pw = None
        self._navegador = None

    # ------------------------------------------------------------------ util
    def _cliente(self, verify: bool) -> httpx.Client:
        if verify not in self._clientes:
            self._clientes[verify] = httpx.Client(
                headers={
                    "User-Agent": self.cfg.user_agent,
                    "Accept-Language": "es-CO,es;q=0.9",
                },
                timeout=self.cfg.timeout,
                follow_redirects=True,
                verify=verify,
                transport=self._transport,
            )
        return self._clientes[verify]

    def _esperar_turno(self, url: str) -> None:
        host = urlsplit(url).netloc
        transcurrido = time.monotonic() - self._ultimo_acceso.get(host, 0.0)
        if transcurrido < self.cfg.intervalo_por_host:
            time.sleep(self.cfg.intervalo_por_host - transcurrido)
        self._ultimo_acceso[host] = time.monotonic()

    def _permitido(self, url: str, verify: bool) -> bool:
        if not self.cfg.respetar_robots:
            return True
        partes = urlsplit(url)
        base = f"{partes.scheme}://{partes.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                self._esperar_turno(base)
                r = self._cliente(verify).get(base + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp.parse([])            # sin robots.txt: se permite todo
            except httpx.HTTPError:
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.cfg.user_agent, url)

    # ------------------------------------------------------------ descargas
    def get(self, url: str, verify: bool = True) -> httpx.Response:
        if not self._permitido(url, verify):
            raise ErrorDescarga(
                f"robots.txt no permite descargar {url}. Si el sitio responde 403 a "
                "robots.txt pero la página abre en el navegador, revísenlo a mano y usen --sin-robots")
        ultimo_error = None
        for intento in range(self.cfg.reintentos):
            self._esperar_turno(url)
            try:
                r = self._cliente(verify).get(url)
                if r.status_code in REINTENTABLES:
                    ultimo_error = f"HTTP {r.status_code}"
                elif r.status_code >= 400:
                    raise ErrorDescarga(f"HTTP {r.status_code} en {url}")
                else:
                    return r
            except httpx.HTTPError as e:
                ultimo_error = f"{type(e).__name__}: {e}"
            espera = (2 ** intento) + random.uniform(0, 1)
            log.warning("Falló %s (%s). Reintento en %.1f s", url, ultimo_error, espera)
            time.sleep(espera)
        raise ErrorDescarga(f"Agotados los reintentos para {url}: {ultimo_error}")

    def get_renderizado(self, url: str) -> tuple[bytes, str]:
        """Descarga una página que necesita JavaScript. Devuelve (html_bytes, content_type)."""
        if not self._permitido(url, True):
            raise ErrorDescarga(f"robots.txt no permite descargar {url}")
        if self._navegador is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise ErrorDescarga(
                    "Esta fuente requiere Playwright: uv add playwright && "
                    "uv run playwright install chromium"
                ) from e
            self._pw = sync_playwright().start()
            self._navegador = self._pw.chromium.launch()
        self._esperar_turno(url)
        pagina = self._navegador.new_page(user_agent=self.cfg.user_agent)
        try:
            pagina.goto(url, wait_until="networkidle", timeout=self.cfg.timeout * 1000)
            html = pagina.content()
        finally:
            pagina.close()
        return html.encode("utf-8"), "text/html; charset=utf-8"

    def cerrar(self) -> None:
        for c in self._clientes.values():
            c.close()
        if self._navegador is not None:
            self._navegador.close()
            self._pw.stop()
