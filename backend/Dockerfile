FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl: usado por el conector boletin-cba-pdf-diario (Etapa 5) en vez de
# urllib — boletinoficial.cba.gov.ar (CloudFront) devuelve 403 a
# peticiones de urllib pero no a las de curl (ver
# src/connectors/boletin_cba/connector.py).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY entrypoint.sh ./

# torch CPU-only primero: el paquete de PyPI por defecto arrastra las
# dependencias de CUDA (varios GB) aunque el MVP corre siempre en CPU
# (sección 15 del design spec). Instalarlo desde el índice CPU de PyTorch
# antes que el resto evita que pip lo resuelva con soporte GPU.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install . && chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
