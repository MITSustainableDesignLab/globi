# Globi Workshop Setup Guide

This guide will walk you through setting up the Globi environment. Please follow each step carefully based on your operating system.

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

FOR MAC:

```bash
docker not found
```

5. Make sure that docker is set properly in path. For Mac, this is :

```bash
export PATH=$PATH:$HOME/.docker/bin
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

### 3. Install Python and uv

This project requires Python 3.12 or higher and uses `uv` for package management.

##TODO: only install uv, use uv instructions to install python

#### macOS/Linux

1. Install `uv`:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Verify installation:
   ```bash
   uv --version
   ```
3. After installing `uv`, you can install python if you don't have it already. To check if you do, verify through:

```bash
python --version
```

#Review the [uv documentation](https://docs.astral.sh/uv/getting-started/installation/) on how to install python:
https://docs.astral.sh/uv/guides/install-python/

Check that you have the right version installed:

```bash
python --version
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

### Install git

Check if you have git installed on your computer already:

```bash
git --version
```

If not, then go to the git website for required steps to download
https://git-scm.com/install/

## Installing `make`

For Mac, make should be fully installed already.
For Windows, you need to install `make` in order to use any of the following commands.
To do this, you use one of the following methods:

```bash
choco install make
```
