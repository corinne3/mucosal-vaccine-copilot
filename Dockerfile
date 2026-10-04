# Mucosal Vaccine Copilot — one container, no Python on the host.
#
# Built for a reader who is not a developer. The whole contract is:
#   docker compose up
# then open http://localhost:8501. Nothing else is installed on their machine,
# nothing leaves it, and uninstalling is `docker compose down`.
#
# Deliberately NOT included: the Ollama models. They are several gigabytes, they
# are optional everywhere in this project, and baking them in would turn a
# 400 MB image into a 5 GB one to enable a path that has a deterministic
# fallback. docker-compose.yml shows how to attach a local Ollama if wanted.

FROM python:3.12-slim

# curl is for the container's own healthcheck; nothing in the app needs network.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so editing the source does not re-resolve the whole
# dependency tree on every rebuild.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[app]"

COPY app/ ./app/
COPY data/ ./data/
COPY tests/ ./tests/
COPY docs/ ./docs/

# Streamlit otherwise asks for an email address on first run, which stops a
# non-developer dead, and tries to phone home for usage statistics.
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    PYTHONUNBUFFERED=1

# Fail the build, not the demo, if the app cannot even be imported.
RUN python -c "import mvc, mvc.consortia, mvc.comparability; print('import ok')"

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app/dashboard.py", "--server.port=8501"]
