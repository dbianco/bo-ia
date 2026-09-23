# PoC de scraping

Spike descartable para comparar Scrapy y Playwright contra un día público del
BOP de Córdoba.

```bash
uv run --with scrapy --with playwright --with httpx python poc/scraping/run_poc.py
```

Playwright usa Chrome instalado localmente (`channel="chrome"`). La salida
queda en `resultados.json` y el análisis en
`docs/superpowers/reports/2026-09-23-scraping-poc.md`.
