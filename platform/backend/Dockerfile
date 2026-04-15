FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps via pip (extract deps from pyproject.toml)
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi[standard]>=0.115" \
    "uvicorn[standard]>=0.32" \
    "sqlalchemy[asyncio]>=2.0" \
    "asyncpg>=0.30" \
    "alembic>=1.14" \
    "pydantic-settings>=2.6" \
    "authlib>=1.4" \
    "httpx>=0.28" \
    "python-jose[cryptography]>=3.3" \
    "celery[redis]>=5.4" \
    "redis>=5.2" \
    "pyyaml>=6.0" \
    "openpyxl>=3.1" \
    "python-multipart>=0.0.12" \
    "itsdangerous>=2.1" \
    "psycopg2-binary>=2.9" \
    "pdfplumber>=0.11" \
    "python-docx>=1.1" \
    "anthropic>=0.40" \
    "beautifulsoup4>=4.12" \
    "dnspython>=2.6" \
    "bcrypt>=4.2"

# Copy app
COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
