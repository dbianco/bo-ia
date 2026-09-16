FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

# torch CPU-only primero: el paquete de PyPI por defecto arrastra las
# dependencias de CUDA (varios GB) aunque el MVP corre siempre en CPU
# (sección 15 del design spec). Instalarlo desde el índice CPU de PyTorch
# antes que el resto evita que pip lo resuelva con soporte GPU.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install .

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
