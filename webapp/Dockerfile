# Lean runtime image for the OpenAlex demo web app.
# Build from the repo root:  docker build -f webapp/Dockerfile -t oa-demo .
#
# Only the live-search + static-serving runtime is installed. Clustering and
# embeddings happen offline (generate_examples.py), so numpy/scikit-learn/umap/
# openai are intentionally excluded and the OpenAI key never lives on the server.
FROM python:3.14-slim

WORKDIR /app

# Install the openalex_cli package WITHOUT its heavy deps, then the runtime subset.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY webapp/requirements-server.txt ./webapp/requirements-server.txt
RUN pip install --no-cache-dir -r webapp/requirements-server.txt

# App code + pre-generated datasets + static frontend.
COPY webapp ./webapp

ENV OA_MAX_RESULTS=10
EXPOSE 8000

# Healthcheck hits the cheap, dependency-free endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]
