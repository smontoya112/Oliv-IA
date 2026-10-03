"""Registro de los experimentos de la rama prueba-claude: lee `experimentos/claude/catalogo.json`
(qué se probó y qué se decidió) y los `metricas.json` de cada corrida, y escribe
`experimentos/claude/REGISTRO.md` y `experimentos/claude/registro.csv`.

    python -m src.analisis.registro_claude

Cada corrida es una carpeta `experimentos/claude/<etiqueta>/` con `metricas.json` (lo escribe
`src.analisis.resumen_corrida` o `src.generacion.exp_letras`), la `submission_sample50.jsonl` y, si se
adopta, un `RESUMEN.md`. El catálogo guarda la configuración (modelo, estrategia, contexto, índice),
la hipótesis y la decisión (adoptar / descartar / inconcluso) con su razón.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DIR = RAIZ / "experimentos" / "claude"


def _leer(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fila(etiqueta: str, cfg: dict) -> dict:
    m = _leer(DIR / etiqueta / "metricas.json") or {}
    pol = (m.get("cerradas_politicas") or {})
    ac = pol.get("aciertos") or {}
    oficial = m.get("oficial") or {}
    proxy = m.get("texto_libre_proxy") or {}
    t = m.get("tiempos") or {}
    letras = (m.get("variantes") or {}).get(cfg.get("variante", ""), {})
    return {
        "etiqueta": etiqueta, "modelo": cfg.get("modelo"), "estrategia": cfg.get("estrategia"),
        "contexto": cfg.get("contexto"), "indice": cfg.get("indice"), "politica": cfg.get("politica"),
        "cerradas_final": f"{ac.get('final')}/{pol.get('n')}" if (ac and (t.get("multiple_choice"))) else (
            f"{letras.get('aciertos')}/{letras.get('n')}" if letras else ""),
        "cerradas_por_permutacion": letras.get("exactitud_por_permutacion", ""),
        "proxy_texto": proxy.get("proxy", "") if (t.get("semi_open") or t.get("open_ended")) else "",
        "proxy_lexico": proxy.get("lexico", "") if (t.get("semi_open") or t.get("open_ended")) else "",
        "citas_indice": (oficial.get("citas") or {}).get("indice", "") if len(t) >= 3 else "",
        "s_cerrada": (t.get("multiple_choice") or {}).get("s_por_pregunta", letras.get("segundos_por_pregunta", "")),
        "s_semi": (t.get("semi_open") or {}).get("s_por_pregunta", ""),
        "s_abierta": (t.get("open_ended") or {}).get("s_por_pregunta", ""),
        "decision": cfg.get("decision"), "razon": cfg.get("razon"), "hipotesis": cfg.get("hipotesis"),
    }


def main() -> None:
    cat = _leer(DIR / "catalogo.json") or {}
    filas = [fila(e, c) for e, c in cat.items()]
    campos = list(filas[0]) if filas else []
    with (DIR / "registro.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, campos)
        w.writeheader()
        w.writerows(filas)
    md = ["# Registro de experimentos — rama `prueba-claude`", "",
          "Generado por `python -m src.analisis.registro_claude` desde `catalogo.json` y los `metricas.json`.",
          "Cerradas: aciertos sobre las 15 de `sample_50` (un ítem = 0,067; ruido de ±1-2). Texto libre: proxy local de RAGAS ",
          "(0,25·coseno e5 + 0,75·F1 léxico; ordena variantes, no sustituye al juez). RAGAS real: ver los RESUMEN.md.", "",
          "| Etiqueta | Modelo | Estrategia / política | Contexto | Cerradas | Proxy | Citas | s/cerr · semi · abierta | Decisión |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in filas:
        cerr = r["cerradas_final"] + (f" (perm. {r['cerradas_por_permutacion']})" if r["cerradas_por_permutacion"] != "" else "")
        md.append(f"| {r['etiqueta']} | {r['modelo'] or ''} | {r['estrategia'] or ''} {r['politica'] or ''} | "
                  f"{r['contexto'] or ''} | {cerr} | {r['proxy_texto']} | {r['citas_indice']} | "
                  f"{r['s_cerrada']} · {r['s_semi']} · {r['s_abierta']} | **{r['decision'] or ''}** |")
    md += ["", "## Hipótesis y razones", ""]
    for r in filas:
        md += [f"- **{r['etiqueta']}** — {r['hipotesis'] or ''} → {r['decision'] or ''}: {r['razon'] or ''}"]
    (DIR / "REGISTRO.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(filas)} experimentos -> {DIR / 'REGISTRO.md'}")


if __name__ == "__main__":
    main()
