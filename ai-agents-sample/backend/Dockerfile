FROM python:3.12.12-slim
WORKDIR /app/backend
ARG PYTHON_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple/
RUN pip install --no-cache-dir --index-url "$PYTHON_INDEX_URL" uv==0.11.32
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --default-index "$PYTHON_INDEX_URL"
COPY backend/src ./src
RUN uv sync --frozen --no-dev --default-index "$PYTHON_INDEX_URL"
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY data /app/data
ENV PATH="/app/backend/.venv/bin:$PATH" DATA_DIRECTORY="/app/data"
RUN useradd --create-home app && chown -R app:app /app
USER app
CMD ["uvicorn", "support_demo.main:app", "--host", "0.0.0.0", "--port", "8000"]
