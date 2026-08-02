# grc-rag — container image for the HTTP boundary (ADR-0020).
#
# Two decisions drive this file, both about keeping a deployed answer identical to a local one:
#
# 1. The retrieval models are baked in at BUILD time, not fetched at boot. all-MiniLM-L6-v2 and
#    ms-marco-MiniLM-L-6-v2 are ~90 MB together; downloading them on first request would make a
#    cold start slow, make the container depend on Hugging Face being reachable in production, and
#    silently change behaviour if an upstream tag ever moved. Baked in, the image is hermetic.
#
# 2. The index (data/processed) is baked in too. It is small (~2.6 MB), derived, and already
#    committed, so shipping it makes the image self-contained — no volume, no init job, no chance
#    of serving against an index that doesn't match the scorecard the CI gate checked.
#
# The generator is the one thing NOT baked in: there is no Ollama in this image, so the container
# sets GRC_RAG_LLM=anthropic and reads its key from the environment at request time. Never bake a
# key into a layer.

FROM python:3.12-slim AS base

# Keep Python quiet, unbuffered and byte-code-free — standard for containers, and it makes logs
# appear immediately rather than being held in a buffer during a slow request.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# CPU-only torch, installed first and deliberately. sentence-transformers depends on torch, and the
# default PyPI wheel bundles the CUDA runtime — roughly 2 GB of GPU libraries that a Container App
# with no GPU can never execute. Pulling the CPU wheel from PyTorch's own index cuts the image by
# well over half and removes nothing we use. Installing it before the package means pip already has
# a satisfying torch and will not resolve the CUDA build as a transitive dependency.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

# Dependency layer next: pyproject alone changes far less often than src/, so an edit to a module
# does not re-resolve and re-download the whole dependency tree on every rebuild.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Pre-fetch the retrieval models into the image (see note 1 above). Runs as its own layer so it is
# cached across rebuilds that only touch application code.
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
print('retrieval models cached')"

# The committed index + calibrated support threshold (see note 2 above).
COPY data/processed/ ./data/processed/

# Hosted generation: this image has no Ollama daemon. ANTHROPIC_API_KEY is injected at runtime as
# a secret, never built into the image.
ENV GRC_RAG_LLM=anthropic \
    GRC_RAG_INDEX_DIR=/app/data/processed \
    PORT=8000

# Run unprivileged. A container that only needs to read its own index has no reason to be root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /opt/hf
USER appuser

EXPOSE 8000

# Container Apps sets $PORT; default to 8000 for a plain `docker run`.
CMD ["sh", "-c", "uvicorn grc_rag.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
