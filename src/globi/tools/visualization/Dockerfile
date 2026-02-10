ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS main
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /uvx /bin/


# Install dependencies for running energy models
# etc
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        build-essential ca-certificates \
        libx11-6 libexpat1 libgomp1 libcurl4-openssl-dev libssl-dev libxml2-dev gfortran \
        curl tk python3-tk \
        git \
        gdal-bin libgdal-dev libproj-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


WORKDIR /code
COPY uv.lock pyproject.toml README.md /code/

RUN uv sync --locked --no-install-project --extra cli --extra visualization

RUN uv run epi prisma generate

COPY src /code/src/

COPY src/globi/tools/visualization/config.toml /code/.streamlit/config.toml

RUN uv sync --locked --extra cli --extra visualization


CMD [ "uv", "run", "streamlit", "run", "src/globi/tools/visualization/main.py" ]
