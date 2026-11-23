# Two images from one file (design doc §16):
#   api: FastAPI agent service (agent, tools, DuckDB, BM25 corpus, boto3 for SageMaker)
#   ui:  Streamlit client; it reaches the agent only over HTTP, so it gets only the UI packages
# Build both with `docker compose build`. The dataset is not in the image: it is mounted at /data.

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY pyproject.toml uv.lock ./

FROM base AS api
# Main dependencies only: no dev tools, no Streamlit.
RUN uv sync --locked --no-default-groups --no-install-project
COPY housing housing
COPY tools tools
COPY agent agent
COPY api api
COPY rag rag
USER app
ENV DATA_DIR=/data RAG_CORPUS_DIR=/app/rag/corpus
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS ui
# The UI group only (streamlit, plotly, pandas, httpx): the UI imports nothing else.
RUN uv sync --locked --no-default-groups --group ui --no-install-project
COPY ui ui
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"
CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false", "--server.fileWatcherType=none", \
     "--client.toolbarMode=viewer"]
