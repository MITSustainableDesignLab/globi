# Globi Workshop Setup Guide

This guide will walk you through downloading all of the required dependencies to be able to work with the `globi` repo.

## What You'll Install

This workshop requires five essential tools:

1. **Docker** - Runs the Hatchet server locally in containers
2. **Git** - Version control for managing code
3. **uv** - Fast Python package manager
4. **Python 3.12+** - The programming language for this project
5. **make** - Build automation tool (Windows only; macOS includes this by default)

## Step 1: Install Docker

Docker lets you run the Hatchet server in an isolated container so you don't have to worry about installing large applications locally. You'll need to download Docker Desktop.

=== "macOS"

    1. **Download** [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop)
    2. Open the `.dmg` file and drag Docker to your Applications folder
    3. Launch Docker Desktop from Applications
    4. **Verify** the installation by opening Terminal and running:
       ```bash
       docker --version
       ```
       You should see output like: `Docker version 24.0.x`

    !!! note "Troubleshooting: Command not found"
        If you see `docker: command not found`, Docker may not be in your PATH. Add it by running:
        ```bash
        export PATH=$PATH:$HOME/.docker/bin
        ```
        To make this permanent, add the line above to your `~/.zshrc` or `~/.bash_profile` file.

=== "Windows"

    1. **Download** [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)
    2. Run the installer and follow the installation wizard
    3. Restart your computer when prompted
    4. Launch Docker Desktop from the Start menu
    5. **Verify** the installation by opening PowerShell or Command Prompt and running:
       ```bash
       docker --version
       ```
       You should see output like: `Docker version 24.0.x`

=== "Linux"

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
    4. Add your user to the docker group so you can run Docker without `sudo`:
       ```bash
       sudo usermod -aG docker $USER
       ```
    5. **Log out and log back in** for the group change to take effect
    6. **Verify** the installation:
       ```bash
       docker --version
       ```
       You should see output like: `Docker version 24.0.x`

---

## Step 2: Install Git

Git is essential for version control. We will use this to clone the globi repo, so you need to have an account beforehand.

### Check for Existing Installation

Open your terminal and run:

```bash
git --version
```

If you see a version number like `git version 2.x.x`, you're all set! Skip to Step 3.

### Install Git

If Git isn't installed, visit the [official Git installation page](https://git-scm.com/downloads) and follow the instructions for your operating system.

After installation, verify it worked:

```bash
git --version
```

---

## Step 3: Install uv and Python

This project uses Python 3.12+ and `uv` for package management. We recommend installing `uv` first, then using it to manage Python versions.

=== "macOS"

    1. **Install uv** with a single command:

       ```bash
       curl -LsSf https://astral.sh/uv/install.sh | sh
       ```

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       You should see output like: `uv 0.x.x`

    3. **Check if you have Python 3.12+**:

       ```bash
       python --version
       ```

       or

       ```bash
       python3 --version
       ```

    4. **Install Python using uv** if needed:

       If your Python version is below 3.12 or you don't have Python installed, use `uv` to install it:

       ```bash
       uv python install 3.12
       ```

       For more details, check the [uv Python installation guide](https://docs.astral.sh/uv/guides/install-python/).

    5. **Verify Python installation**:
       ```bash
       python --version
       ```
       You should see: `Python 3.12.x` or higher

=== "Linux"

    1. **Install uv** with a single command:

       ```bash
       curl -LsSf https://astral.sh/uv/install.sh | sh
       ```

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       You should see output like: `uv 0.x.x`

    3. **Check if you have Python 3.12+**:

       ```bash
       python --version
       ```

       or

       ```bash
       python3 --version
       ```

    4. **Install Python using uv** if needed:

       If your Python version is below 3.12 or you don't have Python installed, use `uv` to install it:

       ```bash
       uv python install 3.12
       ```

       For more details, check the [uv Python installation guide](https://docs.astral.sh/uv/guides/install-python/).

    5. **Verify Python installation**:
       ```bash
       python --version
       ```
       You should see: `Python 3.12.x` or higher

=== "Windows"

    1. **Install uv** using PowerShell:

       ```bash
       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
       ```

    !!! note "About ExecutionPolicy ByPass"
        The `-ExecutionPolicy ByPass` flag temporarily allows running the installation script from the internet. This only applies to this single command and doesn't change your system settings.

        If you'd like to inspect the script before running it, you can view it first:
        ```bash
        powershell -c "irm https://astral.sh/uv/install.ps1 | more"
        ```

        Alternatively, you can [download the installer directly from GitHub](https://github.com/astral-sh/uv/releases).

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       You should see output like: `uv 0.x.x`

    3. **Check if you have Python 3.12+**:

       ```bash
       python --version
       ```

    4. **Install Python using uv** if needed:

       If your Python version is below 3.12 or you don't have Python installed:

       ```bash
       uv python install 3.12
       ```

    5. **Verify Python installation**:
       ```bash
       python --version
       ```
       You should see: `Python 3.12.x` or higher

---

## Step 4: Install make

=== "macOS"

    You already have `make` installed by default! You can verify by running:

    ```bash
    make --version
    ```

    You should see output like: `GNU Make 3.x` or `4.x`

=== "Linux"

    You already have `make` installed by default! You can verify by running:

    ```bash
    make --version
    ```

    You should see output like: `GNU Make 4.x`

=== "Windows"

    You'll need to install `make` to use the project's build commands.

    **Option 1: Using winget (Recommended)**

    Windows 10+ includes winget by default, so no separate package manager installation needed:

    ```bash
    winget install GnuWin32.Make
    ```

    After installation, you may need to restart your terminal or add `C:\Program Files (x86)\GnuWin32\bin` to your PATH.

    **Option 2: Using Git Bash**

    If you installed Git for Windows in Step 2, you can use Git Bash terminal which includes `make`. Just open "Git Bash" instead of PowerShell or Command Prompt.

    **Option 3: Using Chocolatey**

    If you have [Chocolatey](https://chocolatey.org/) installed:

    ```bash
    choco install make
    ```

    **Option 4: Using Scoop**

    If you have [Scoop](https://scoop.sh/) installed:

    ```bash
    scoop install make
    ```

    **Verify Installation**

    ```bash
    make --version
    ```

    You should see output like: `GNU Make 3.x` or `4.x`
