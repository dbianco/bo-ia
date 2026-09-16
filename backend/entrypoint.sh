#!/bin/sh
set -e

# Corre las migraciones pendientes en cada arranque, para que "docker
# compose up" sea de verdad un solo comando (FR-016): nadie tiene que
# correr `alembic upgrade head` a mano.
alembic upgrade head

exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
