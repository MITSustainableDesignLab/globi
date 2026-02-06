FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /bin/uv

# Which one of these is needed for gdal?
RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential ca-certificates \
    libx11-6 libexpat1 libgomp1 libcurl4-openssl-dev libssl-dev libxml2-dev gfortran \
    curl tk python3-tk \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements to cache them in docker layer
WORKDIR /code
COPY uv.lock pyproject.toml README.md /code/

# Project initialization:
RUN uv sync --locked --no-install-project

# Copy Python code to the Docker image
COPY src/globi/worker/initialize .

ENTRYPOINT ["uv", "run", "python", "local_aws_init.py"]
