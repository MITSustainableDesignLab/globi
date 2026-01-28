## Run simulations with Hatchet and Docker

This guide walks you through running `globi` simulations end‑to‑end using Hatchet and Docker.

It assumes you have already completed the [setup guide](../getting-started/requirements.md), including:

- cloning the `globi` repo
- installing dependencies with `uv sync --all-extras --all-groups`
- installing Docker, Git, Python 3.12+, and `make`

The steps below cover:

- starting the Hatchet server and simulation engine
- configuring environment files and tokens
- submitting a simulation manifest
- monitoring runs in the Hatchet UI
- fetching and storing results
- safely shutting everything down

---

### Before you start

- **docker running**: make sure Docker Desktop (or the Docker daemon) is running.
- **terminal location**: run commands from the repository root (the folder containing `Makefile` and `pyproject.toml`).
- **network access**: the first run may download container images from remote registries and can take several minutes.

!!! note

    the commands in this guide are the same for macOS, linux, and windows (using a unix‑like shell such as git bash or wsl).

---

### Step 1: Start the Hatchet server

The Hatchet server provides the UI and orchestration backend for managing workflows.

=== "first run"

    Run:

    ```bash
    make hatchet-lite
    ```

    This:

    - builds and/or pulls the `hatchet-lite` docker image
    - starts the Hatchet server container in the background
    - exposes the Hatchet UI on `http://localhost:8080`

    !!! note

        the first run may take several minutes while docker downloads and builds images. later runs are much faster.

=== "subsequent runs"

    If you have already started Hatchet once before, you can simply ensure it is running with:

    ```bash
    make hatchet-lite
    ```

    Docker will reuse existing images and start the container if it is not already running.

You can verify the container is up by running:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet.yml ps
```

Look for a `hatchet-lite` container with a `running` status.

---

### Step 2: Create and configure Hatchet environment files

Hatchet uses a client token stored in environment files that are loaded by the `make cli` target.

1. **Generate a Hatchet client token**:

   ```bash
   make hatchet-token
   ```

   This will:

   - ensure `hatchet-lite` is running
   - execute the Hatchet admin command inside the container
   - print a `HATCHET_CLIENT_TOKEN` value in your terminal

2. **Copy the token into your Hatchet env files**.

   In your terminal output, locate a line similar to:

   ```text
   HATCHET_CLIENT_TOKEN=your_generated_token_here
   ```

   Open your Hatchet environment file(s), for example:

   - `.env.local.host.hatchet`

   and add or update the line:

   ```text
   HATCHET_CLIENT_TOKEN=your_generated_token_here
   ```

3. **Save the files**.

!!! warning

    treat your `HATCHET_CLIENT_TOKEN` like a password. do not commit it to git, and do not share it publicly.

!!! tip

    if you see example files such as `.env.local.host.hatchet.example`, copy them once and then edit the resulting `.env` files:

    ```bash
    cp .env.local.host.hatchet.example .env.local.host.hatchet
    ```

    then replace the placeholder token with the real one.

---

### Step 3: Start the simulation engine and workers

Now start the full engine stack, which includes:

- Hatchet server
- simulation workers
- fanout workers
- any required supporting services

Run:

```bash
make engine
```

This command:

- composes `docker-compose.yml`, `docker-compose.hatchet.yml`, and `docker-compose.aws.yml`
- builds images if needed
- starts all services in the background with `-d`

You can check container status with:

```bash
docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml ps
```

You should see containers for Hatchet and the simulation services with a `running` status.

!!! note

    on macos, you may occasionally see an error like:

    ```text
    target simulations: failed to solve: image ".../hatchet/globi:latest": already exists

    make: *** [engine] Error 1
    ```

    this is usually transient. re‑run:

    ```bash
    make engine
    ```

    and the issue should resolve.

---

### Step 4: Access the Hatchet UI

Open your browser and go to:

```text
http://localhost:8080
```

On the first run, Hatchet may prompt you to create or confirm an admin account in the terminal where the container is running.

For the local `hatchet-lite` instance, you can use:

```text
username: admin@example.com
password: Admin123!!
```

In the Hatchet UI:

- navigate to **workers**
- verify that the expected workers are **running** and **healthy**

If you do **not** see workers, refer to the troubleshooting section below.

---

### Step 5: Run a test simulation

Now you can submit a simulation manifest via the `make cli` target, which wraps the `globi` CLI with the correct environment files.

1. **Confirm the engine is running**:

   - ensure `make engine` has completed without errors
   - verify containers are running with `docker compose ... ps`

2. **Decide which manifest to run**.

   A typical manifest path looks like:

   ```text
   data/partners/LOCATION/manifest.yml
   ```

   Replace `LOCATION` with the specific dataset or project you want to simulate.

3. **Submit the manifest**:

   ```bash
   make cli submit manifest -- --path {PATH_TO_MANIFEST} --grid-run
   ```

   where:

   - `{PATH_TO_MANIFEST}` is your manifest file path (for example `data/partners/Cambridge_UK/manifest.yml`)
   - `--grid-run` enables grid‑style execution over the manifest configuration

4. **Monitor progress in the Hatchet UI**:

   - go to `http://localhost:8080`
   - navigate to **workflows** or **runs**
   - locate the workflow corresponding to your manifest submission
   - watch status transition from `pending` → `running` → `completed` (or `failed` if there is an error)

You can click into the workflow to view task‑level logs and any errors.

---

### Step 6: Fetch simulation results

When a simulation completes, the CLI prints a summary similar to:

```text
versioned_experiment:
  base_experiment:
    experiment: scythe_experiment_simulate_globi_building
    run_name: Cambridge_UK/dryrun/Baseline
    storage_settings:
      BUCKET: globi-bucket
      BUCKET_PREFIX: globi
  version:
    major: 1
    minor: 0
    patch: 0
timestamp: '2026-01-23T13:57:36.233154'
```

- **run_name** identifies the specific run (for example `Cambridge_UK/dryrun/Baseline`)
- **version** is a semantic version (major.minor.patch) of the experiment configuration

#### Fetch the latest version of a run

Copy the `run_name` from the output and run:

```bash
make cli get experiment --run-name {YOUR_RUN_NAME_HERE}
```

This fetches the latest available version of that experiment and stores the results in your configured storage/output location. The CLI prints where the results were saved.

#### Fetch a specific version and output directory

If you have multiple versions of the same run, or you want to control exactly where results are written, include `--version` and `--output_dir`:

```bash
make cli get experiment \
  --run-name {YOUR_RUN_NAME_HERE} \
  --version {VERSION} \
  --output_dir {YOUR_CHOSEN_OUTPUT_DIR}
```

where:

- `{VERSION}` is of the form `major.minor.patch` (for example `1.0.0`)
- `{YOUR_CHOSEN_OUTPUT_DIR}` is a local path where you want results saved

!!! tip

    choose an output directory under a dedicated folder (for example `outputs/`) to keep simulation results organized by run and version.

---

### Step 7: Shut down Docker services

When you are done running simulations, you can stop all related Docker containers with:

```bash
make down
```

This:

- stops and removes containers from `docker-compose.yml`, `docker-compose.hatchet.yml`, and `docker-compose.aws.yml`
- keeps docker images on disk so future runs start faster

Run `make engine` again the next time you want to use the system.

---

## Troubleshooting

This section lists common issues and concrete steps to diagnose and fix them.

### Docker and container issues

- **docker daemon not running**

  - ensure Docker Desktop (macOS/windows) or the docker service (linux) is running
  - verify with:

    ```bash
    docker --version
    docker ps
    ```

- **containers not staying up**

  - check logs for a specific service, for example:

    ```bash
    docker compose -f docker-compose.yml -f docker-compose.hatchet.yml -f docker-compose.aws.yml logs hatchet-lite
    ```

  - look for configuration or startup errors in the log output

- **image already exists error when running `make engine`**

  - if you see:

    ```text
    target simulations: failed to solve: image ".../hatchet/globi:latest": already exists
    ```

  - simply re‑run:

    ```bash
    make engine
    ```

  - if the error persists, run:

    ```bash
    make down
    make engine
    ```

- **port 8080 already in use**

  - if `hatchet-lite` fails to start because port `8080` is in use:
    - close any other application using port `8080`
    - or stop the conflicting container/process
    - then re‑run `make hatchet-lite` or `make engine`

---

### Hatchet UI and API issues

- **cannot load `http://localhost:8080`**

  - verify that `hatchet-lite` is running:

    ```bash
    docker compose -f docker-compose.yml -f docker-compose.hatchet.yml ps
    ```

  - if the container is not `running`, start it:

    ```bash
    make hatchet-lite
    ```

  - if it still fails, inspect logs:

    ```bash
    docker compose -f docker-compose.yml -f docker-compose.hatchet.yml logs hatchet-lite
    ```

- **workers not appearing in Hatchet UI**

  - ensure the engine stack is running:

    ```bash
    make engine
    ```

  - check for worker containers in `docker compose ... ps`
  - open Hatchet UI → **workers** and verify that they show as healthy
  - if workers crash repeatedly, inspect their logs using `docker compose ... logs <service-name>`

---

### Token and environment configuration issues

- **token errors or unauthorized requests**

  - confirm `HATCHET_CLIENT_TOKEN` is set in your Hatchet env file(s), for example:

    ```text
    HATCHET_CLIENT_TOKEN=your_generated_token_here
    ```

  - ensure there are no extra quotes or spaces around the value
  - if you suspect the token is invalid or expired:

    ```bash
    make hatchet-token
    ```

    then update the env files with the new token.

- **env file not being loaded**

  - `make cli` loads environment from:

    - `.env.$(AWS_ENV).aws` (default: `.env.local.host.aws`)
    - `.env.$(HATCHET_ENV).hatchet` (default: `.env.local.host.hatchet`)
    - `.env.scythe.fanouts`
    - `.env.scythe.storage`

  - verify these files exist and contain the expected variables

---

### Simulation and worker issues

- **jobs stuck in `pending`**

  - check that workers are running (Hatchet UI → **workers**)
  - confirm worker containers are healthy with `docker compose ... ps`
  - inspect worker logs for errors (for example configuration or connectivity issues)

- **workflow fails immediately after submission**

  - open the workflow in the Hatchet UI and inspect task logs
  - common causes:
    - invalid manifest path (`--path` does not exist)
    - missing or incorrect environment variables
    - storage configuration issues (for example s3 bucket permissions)

---

### Python and uv issues

- **`module not found` or missing dependency**

  - re‑sync dependencies:

    ```bash
    uv sync --all-extras --all-groups
    ```

  - or run the project install target:

    ```bash
    make install
    ```

- **python version error**

  - confirm that your python version is 3.12 or higher:

    ```bash
    python --version
    python3 --version
    ```

  - if needed, install python 3.12 with `uv` (see the setup guide).

---

## Quick reference

### Essential commands

```bash
# start hatchet server (ui and api)
make hatchet-lite

# generate hatchet token and print to terminal
make hatchet-token

# start full engine stack (hatchet + workers + services)
make engine

# submit a simulation manifest
make cli submit manifest -- --path data/partners/LOCATION/manifest.yml --grid-run

# fetch experiment results
make cli get experiment --run-name {YOUR_RUN_NAME_HERE}

# stop and remove all related docker containers
make down

# open hatchet ui
open http://localhost:8080  # macos
# or manually paste http://localhost:8080 into your browser
```

### Key file locations

- environment config: `.env.*` files used by `make cli`
- data directory: `data/`
- hatchet configuration: `hatchet.yaml`
- make targets: `Makefile`
