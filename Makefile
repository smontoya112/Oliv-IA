# Atajos. El comando único de reproducción es `make reproduce` (equivale a `bash run.sh`; ver README.md).
#
#     make reproduce                        # las 992 preguntas de data/test_992.jsonl
#     make reproduce PREGUNTAS=data/sample_50.jsonl PARTES=1
#     make test                             # pruebas (corren sin GPU)
#     make informe                          # regenera informe/INFORME_TECNICO.pdf (necesita `pip install markdown` y Edge o Chrome)
PREGUNTAS ?= data/test_992.jsonl
PARTES ?= 3

.PHONY: reproduce test informe
reproduce:
	PARTES=$(PARTES) bash run.sh $(PREGUNTAS)

test:
	python -m pytest -q

informe:
	python informe/construir_pdf.py
