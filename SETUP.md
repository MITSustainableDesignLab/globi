# Globi Workshop Setup Guide

This guide will walk you through setting up the Globi environment. Please follow each step carefully based on your operating system.

## Prerequisites

Before starting, ensure you have the following installed on your system:

### 1. Install Docker

Docker is required to run the Hatchet server locally.

#### macOS

1. Download [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop)
2. Open the downloaded `.dmg` file and drag Docker to your Applications folder
3. Launch Docker Desktop from Applications
4. Verify installation by running in Terminal:
   ```bash
   docker --version
   ```

#### Windows

1. Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)
2. Run the installer and follow the installation wizard
3. Restart your computer if prompted
4. Launch Docker Desktop
5. Verify installation by running in PowerShell or Command Prompt:
   ```bash
   docker --version
   ```

#### Linux (Ubuntu/Debian)

1. Update your package index:
   ```bash
   sudo apt-get update
   ```
2. Install Docker:
   ```bash
   sudo apt-get install docker.io
   ```
3. Start Docker and enable it to start on boot:
   ```bash
   sudo systemctl start docker
   sudo systemctl enable docker
   ```
4. Add your user to the docker group (to run docker without sudo):
   ```bash
   sudo usermod -aG docker $USER
   ```
5. Log out and log back in for the group change to take effect
6. Verify installation:
   ```bash
   docker --version
   ```

### 2. Install EnergyPlus

EnergyPlus is required for running building energy simulations.

#### macOS

1. Visit the [EnergyPlus Downloads page](https://energyplus.net/downloads)
2. Download the macOS installer (version 23.2 or higher recommended)
3. Open the downloaded package and follow the installation wizard
4. The default installation location is `/Applications/EnergyPlus-X-X-X/`
5. Verify installation:
   ```bash
   ls /Applications/ | grep EnergyPlus
   ```

#### Windows

1. Visit the [EnergyPlus Downloads page](https://energyplus.net/downloads)
2. Download the Windows installer (version 23.2 or higher recommended)
3. Run the installer and follow the installation wizard
4. The default installation location is `C:\EnergyPlusVX-X-X\`
5. Add EnergyPlus to your PATH:
   - Right-click on 'This PC' or 'My Computer' and select 'Properties'
   - Click 'Advanced system settings'
   - Click 'Environment Variables'
   - Under 'System variables', find and select 'Path', then click 'Edit'
   - Click 'New' and add the path to your EnergyPlus installation (e.g., `C:\EnergyPlusV23-2-0\`)
   - Click 'OK' to save

#### Linux (Ubuntu/Debian)

1. Visit the [EnergyPlus Downloads page](https://energyplus.net/downloads)
2. Download the Linux `.deb` or `.tar.gz` installer (version 23.2 or higher recommended)
3. For `.deb` file:
   ```bash
   sudo dpkg -i EnergyPlus-*-Linux.deb
   ```
4. For `.tar.gz` file:
   ```bash
   tar -xzf EnergyPlus-*-Linux.tar.gz
   sudo mv EnergyPlus-*-Linux /usr/local/
   ```
5. Add to your PATH by adding to `~/.bashrc` or `~/.zshrc`:
   ```bash
   export PATH="/usr/local/EnergyPlus-X-X-X:$PATH"
   ```
6. Reload your shell configuration:
   ```bash
   source ~/.bashrc  # or source ~/.zshrc
   ```

### 3. Install Python and uv

This project requires Python 3.12 or higher and uses `uv` for package management.

#### macOS/Linux

1. Install Python 3.12+ if not already installed:

   - macOS (using Homebrew):
     ```bash
     brew install python@3.12
     ```
   - Linux:
     ```bash
     sudo apt-get install python3.12
     ```

2. Install `uv`:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. Verify installation:
   ```bash
   uv --version
   ```

#### Windows

1. Download and install Python 3.12+ from [python.org](https://www.python.org/downloads/)
2. During installation, make sure to check "Add Python to PATH"
3. Install `uv` using pip:
   ```bash
   pip install uv
   ```
4. Verify installation:
   ```bash
   uv --version
   ```

## Setup Steps

### Step 1: Clone the Repository

```bash
#TODO: let's choose where we want the repo to live and what it shoudl be called
cd globi
```

### Step 2: Install Hatchet CLI

Hatchet is the workflow orchestration engine used to manage simulation jobs efficiently.
#TODO: More detail here explaining the workflow?

1. Visit the [Hatchet cli installation](https://docs.hatchet.run/cli)
2. Follow the platform-specific installation instructions for the Hatchet CLI

**For macOS/Linux:**

```bash
curl -fsSL https://get.hatchet.run/cli/install.sh | sh
```

**For Windows (PowerShell):**

```powershell
irm https://get.hatchet.run/cli/install.ps1 | iex
```

3. Verify installation:
   ```bash
   hatchet --version
   ```

### Step 3: Install Project Dependencies

Install all project dependencies using `uv` and `make`:

```bash
make install
#TODO: any other commands they need to run to initialize? do we want to reduce the number of dependencies
```

This will install all required Python packages defined in `pyproject.toml`.

### Step 4: Start Hatchet Server

The Hatchet server provides the UI and orchestration backend for managing workflows.
#TODO: provide more explanation?

1. Start the Hatchet server using the Makefile command:

   ```bash
   make hatchet-simulation-worker
   ```

   For parallel processing, start the fanouts worker in a **new terminal window**:

   ```bash
   make hatchet-simulation-worker
   make hatchet-fanouts-worker
   ```

2. On first run, you will be prompted to create an account in the terminal. The email and password for that account will be provided to you in the terminal directly
   #TODO: add picture here

3. After the worker starts, open your web browser and navigate to:

   ```
   http://localhost:8080
   ```

   Hatchet will give you a different port if the above port is busy. You can see the port in your terminal in the blue box.
   #TODO: add picture here

4. Verify that you have workers running:
   - In the Hatchet UI, navigate to the "Workers" section
   - You should see two workers active

### Step 5: Start Additional Workers

1. Open a new terminal and navigate to the globi directory:

   ```bash
   cd /path/to/globi
   ```

2. Start the fanouts worker:

   ```bash
   make hatchet-fanouts-worker
   ```

3. Return to the Hatchet UI and verify you now see **two workers** running

### Step 6: Create Environment Configuration File

Create a `.env` file in the project root directory with the required configuration:

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Open `.env` in your text editor and update the `HATCHET_CLIENT_TOKEN` value:

   - In the Hatchet UI, navigate to your account settings
   - Find the "API Tokens" or "Client Tokens" section
   - Copy your client token
   - Paste it into the `.env` file:
     ```
     HATCHET_CLIENT_TOKEN=your_token_here
     ```

3. Save the `.env` file

### Step 7: Run a Test Simulation

Now you're ready to run your first simulation using the mock data!

1. Make sure both Hatchet workers are running

2. Run the simulation command:

   ```bash
   hatchet worker dev --run-cmd "uv run --env-file .env globi submit manifest --path data/partners/example/manifest.yml --grid-run"
   ```

3. Monitor the simulation progress:

   - Open the Hatchet UI in your browser (http://localhost:8080)
   - Navigate to the "Workflows" or "Runs" section
   - You should see your simulation job appear
   - Watch as it gets allocated to a worker and begins processing

4. Wait for the simulation to complete:
   - The status will change from "Running" to "Completed" when finished
   - You can click on the workflow to see detailed logs and outputs

## Troubleshooting

### Docker Issues

- **Docker daemon not running:** Make sure Docker Desktop is running before executing commands
- **Permission denied:** On Linux, ensure your user is in the docker group (see Linux Docker installation step)

### EnergyPlus Issues

- **EnergyPlus not found:** Verify EnergyPlus is in your system PATH
- **Version mismatch:** Ensure you have version 23.2 or higher installed

### Hatchet Issues

- **Workers not appearing:** Check that both worker terminals are running without errors
- **Connection refused:** Ensure the Hatchet server is running and accessible at http://localhost:8080
- **Token errors:** Verify your `HATCHET_CLIENT_TOKEN` in the `.env` file is correct

### Python/uv Issues

- **Module not found:** Run `uv sync --all-extras --all-groups` again to ensure all dependencies are installed
- **Python version error:** Verify you have Python 3.12 or higher with `python --version`

## Quick Reference

### Essential Commands

```bash
# Start simulation worker
make hatchet-simulation-worker

# Start fanouts worker (in separate terminal)
make hatchet-fanouts-worker

# Run a simulation
hatchet worker dev --run-cmd "uv run --env-file .env globi submit manifest --path data/partners/LOCATION/manifest.yml --grid-run"

# Check Hatchet UI
open http://localhost:8080
```

### File Locations

- Environment config: `.env`
- Data directory: `data/`
- Hatchet config: `hatchet.yaml`
- Makefile commands: `Makefile`
