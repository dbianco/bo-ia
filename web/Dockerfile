FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install "fastapi>=0.115,<1.0" "uvicorn[standard]>=0.32,<1.0" "jinja2>=3.1,<4.0" "httpx>=0.27,<1.0"

COPY app.py ./
COPY templates ./templates
COPY static ./static

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
