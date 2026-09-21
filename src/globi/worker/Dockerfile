ARG EP_VERSION=25.2.0
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.9.30

# # Use a suitable base image, preferably one that's based on Ubuntu or Debian
FROM debian:bookworm-slim AS energyplus

ARG EP_VERSION
# Set automatically by Docker when building for a platform (e.g. linux/arm64 on Mac M1).
# Fallback to amd64 when unset (older docker or default amd64 build).
ARG TARGETARCH

COPY energyplus_versions.json /tmp/energyplus_versions.json

# Install required packages; pick amd64 or arm64 URL from versions JSON (fallback to amd64 if no arm64 for this version)
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
    ca-certificates \
    # build-essential \
    curl \
    jq \
    && \
    ARCH=${TARGETARCH:-amd64} && \
    export ENERGYPLUS_DOWNLOAD_URL=$(jq -r --arg ver "$EP_VERSION" --arg arch "$ARCH" '.[$ver][$arch] // .[$ver].amd64' /tmp/energyplus_versions.json) && \
    echo $ENERGYPLUS_DOWNLOAD_URL && \
    curl -SLO $ENERGYPLUS_DOWNLOAD_URL && \
    export ENERGYPLUS_DOWNLOAD_FILENAME=$(basename $ENERGYPLUS_DOWNLOAD_URL) && \
    export ENERGYPLUS_DOWNLOAD_BASENAME=$(basename $ENERGYPLUS_DOWNLOAD_FILENAME .tar.gz) && \
    tar -xvf $ENERGYPLUS_DOWNLOAD_FILENAME && \
    cd $ENERGYPLUS_DOWNLOAD_BASENAME && \
    chmod +x energyplus && \
    rm -rf \
    DataSets \
    Documentation \
    ExampleFiles \
    WeatherData \
    MacroDataSets \
    workflows \
    PostProcess/convertESOMTRpgm \
    PostProcess/EP-Compare \
    PreProcess/FMUParser \
    PreProcess/ParametricPreProcessor && \
    cd / && \
    mv $ENERGYPLUS_DOWNLOAD_BASENAME /energyplus-local && \
    rm -f $ENERGYPLUS_DOWNLOAD_FILENAME && \
    rm -f /tmp/energyplus_versions.json && \
    apt-get clean && rm -rf /var/lib/apt/lists/*


FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM python:${PYTHON_VERSION}-slim-bookworm AS main
COPY --from=uv /uv /uvx /bin/

# Install dependencies for running energy models
# etc
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        build-essential \
        ca-certificates \
        libx11-6 \
        libexpat1 \
        libgomp1 \
        libcurl4-openssl-dev \
        libssl-dev \
        libxml2-dev \
        gfortran \
        curl \
        tk \
        python3-tk \
        git \
        gdal-bin \
        libgdal-dev \
        libproj-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy EnergyPlus from the first stage to the second stage
ARG EP_VERSION
COPY --from=energyplus /energyplus-local /usr/local/EnergyPlus-${EP_VERSION}

# Rename directory from dotted to dashed version and set up symlinks
RUN EP_VERSION_DASH=$(echo "${EP_VERSION}" | tr '.' '-') && \
    mv /usr/local/EnergyPlus-${EP_VERSION} /usr/local/EnergyPlus-${EP_VERSION_DASH} && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/energyplus /usr/local/bin/energyplus && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/runenergyplus /usr/local/bin/runenergyplus && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/runreadvars /usr/local/bin/runreadvars && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/runepmacro /usr/local/bin/runepmacro && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/ExpandObjects /usr/local/bin/ExpandObjects && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/PreProcess/GrndTempCalc/Basement /usr/local/bin/Basement && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/PreProcess/GrndTempCalc/Slab /usr/local/bin/Slab && \
    ln -s /usr/local/EnergyPlus-${EP_VERSION_DASH}/energyplus EnergyPlus


WORKDIR /code
COPY uv.lock pyproject.toml README.md /code/

# TODO: only insttall ml for certain containers by passing in a flag to the docker build command
RUN uv sync --locked --no-install-project --extra cli --extra ml-gpu

RUN uv run epi prisma generate

COPY src /code/src/

RUN uv sync --locked --extra cli --extra ml-gpu

CMD [ "uv", "run", "src/globi/worker/main.py" ]
