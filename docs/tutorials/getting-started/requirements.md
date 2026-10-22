# Setup Guide

This guide tells you how to install the tools that you need to work with the `globi` repository.

## What to install

You need five tools:

1. **Docker**: runs the local stack (Hatchet, localstack and workers) in containers.
2. **Git**: gets and manages the code.
3. **uv**: installs and manages Python packages.
4. **Python 3.12+**: the programming language of GloBI.
5. **make**: runs the project commands. Windows needs a separate install (Step 4).

## Step 1: Install Docker

Docker Desktop runs the local stack in isolated containers. Thus, you do not install large applications on your computer.

=== "macOS"

    1. **Download** [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop).
    2. Open the `.dmg` file. Drag Docker to your Applications folder.
    3. Start Docker Desktop from Applications.
    4. **Verify** the installation. Open Terminal and run:
       ```bash
       docker --version
       ```
       The output is similar to `Docker version 24.0.x`.

    ??? problem "`docker: command not found`"

        **Cause:** Docker is not on your PATH.

        **Fix:** add it:
        ```bash
        export PATH=$PATH:$HOME/.docker/bin
        ```
        To keep this setting, add the line above to your `~/.zshrc` or `~/.bash_profile` file.

=== "Windows"

    1. **Download** [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop).
    2. Run the installer. Follow the steps in the installation wizard.
    3. When the installer tells you, restart your computer.
    4. Start Docker Desktop from the Start menu.
    5. **Verify** the installation. Open PowerShell or Command Prompt and run:
       ```bash
       docker --version
       ```
       The output is similar to `Docker version 24.0.x`.

=== "Linux"

    1. Update your package index:
       ```bash
       sudo apt-get update
       ```
    2. Install Docker:
       ```bash
       sudo apt-get install docker.io
       ```
    3. Start Docker, and set it to start when the computer starts:
       ```bash
       sudo systemctl start docker
       sudo systemctl enable docker
       ```
    4. Add your user to the `docker` group. Then you can run Docker without `sudo`:
       ```bash
       sudo usermod -aG docker $USER
       ```
    5. **Log out and log back in**. The group change starts to apply after you log in again.
    6. **Verify** the installation:
       ```bash
       docker --version
       ```
       The output is similar to `Docker version 24.0.x`.

---

## Step 2: Install Git

You use Git to clone the `globi` repository. The repository is public, so you do not need a GitHub account.

### Check for Existing Installation

Open your terminal and run:

```bash
git --version
```

If you see a version number such as `git version 2.x.x`, Git is installed. Go to Step 3.

### Install Git

If Git is not installed, go to the [official Git installation page](https://git-scm.com/downloads). Follow the instructions for your operating system.

After the installation, verify it:

```bash
git --version
```

---

## Step 3: Install uv and Python

GloBI uses Python 3.12+ and `uv` for package management. Install `uv` first. Then use `uv` to install Python.

=== "macOS"

    1. **Install uv**:

       ```bash
       curl -LsSf https://astral.sh/uv/install.sh | sh
       ```

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       The output is similar to `uv 0.x.x`.

    3. **Check your Python version**:

       ```bash
       python --version
       ```

       or

       ```bash
       python3 --version
       ```

    4. **Install Python with uv** if necessary:

       If your Python version is older than 3.12, or Python is not installed, install it with `uv`:

       ```bash
       uv python install 3.12
       ```

       For more information, see the [uv Python installation guide](https://docs.astral.sh/uv/guides/install-python/).

    5. **Verify the Python installation**:
       ```bash
       python --version
       ```
       The output must be `Python 3.12.x` or higher.

=== "Linux"

    1. **Install uv**:

       ```bash
       curl -LsSf https://astral.sh/uv/install.sh | sh
       ```

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       The output is similar to `uv 0.x.x`.

    3. **Check your Python version**:

       ```bash
       python --version
       ```

       or

       ```bash
       python3 --version
       ```

    4. **Install Python with uv** if necessary:

       If your Python version is older than 3.12, or Python is not installed, install it with `uv`:

       ```bash
       uv python install 3.12
       ```

       For more information, see the [uv Python installation guide](https://docs.astral.sh/uv/guides/install-python/).

    5. **Verify the Python installation**:
       ```bash
       python --version
       ```
       The output must be `Python 3.12.x` or higher.

=== "Windows"

    1. **Install uv** in PowerShell:

       ```bash
       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
       ```

    !!! note "About ExecutionPolicy ByPass"

        The `-ExecutionPolicy ByPass` flag lets this one command run the installation script from the internet. It does not change your system settings.

        To read the script before you run it, use:
        ```bash
        powershell -c "irm https://astral.sh/uv/install.ps1 | more"
        ```

        You can also [download the installer from GitHub](https://github.com/astral-sh/uv/releases).

    2. **Verify** the installation:

       ```bash
       uv --version
       ```

       The output is similar to `uv 0.x.x`.

    3. **Check your Python version**:

       ```bash
       python --version
       ```

    4. **Install Python with uv** if necessary:

       If your Python version is older than 3.12, or Python is not installed, run:

       ```bash
       uv python install 3.12
       ```

    5. **Verify the Python installation**:
       ```bash
       python --version
       ```
       The output must be `Python 3.12.x` or higher.

---

## Step 4: Install make

=== "macOS"

    `make` comes with Apple's Command Line Tools. Check it:

    ```bash
    make --version
    ```

    If you see `GNU Make 3.x` or `4.x`, `make` is installed. If macOS offers to install the Command Line Tools, accept. You can also run:

    ```bash
    xcode-select --install
    ```

=== "Linux"

    Check that `make` is installed:

    ```bash
    make --version
    ```

    The output is similar to `GNU Make 4.x`. If the command is not found, install `make`. On Debian or Ubuntu:

    ```bash
    sudo apt-get install make
    ```

=== "Windows"

    Windows does not include `make`, and **Git Bash does not include it either**. Install `make` one time. Then run all `make` commands in **Git Bash**, not in PowerShell or Command Prompt. The `make` targets use `bash` scripts and Unix commands.

    1. **Install make** in PowerShell with one of these commands:

        ```bash
        winget install GnuWin32.Make     # installs to C:\Program Files (x86)\GnuWin32\bin
        ```

        If you use [Chocolatey](https://chocolatey.org/) or [Scoop](https://scoop.sh/), use one of these:

        ```bash
        choco install make
        scoop install make
        ```

    2. **Put make on Git Bash's PATH** (winget only; Chocolatey and Scoop do this for you). Open Git Bash and run:

        ```bash
        echo 'export PATH="$PATH:/c/Program Files (x86)/GnuWin32/bin"' >> ~/.bashrc
        source ~/.bashrc
        ```

    3. **Verify** in Git Bash:

        ```bash
        which make
        make --version
        ```

        The output shows a path and `GNU Make 3.x` or `4.x`. If it does not, see [Troubleshooting make on Windows](#troubleshooting-make-on-windows).

    !!! tip "VS Code users"

        Make Git Bash the default terminal. Open the command palette, run **Terminal: Select Default Profile**, and select **Git Bash**. After you change PATH, restart VS Code fully. Open terminals keep the old PATH.

---

## Step 5: Install the project

Clone the repository and install the Python environment. On Windows, do this in Git Bash:

```bash
git clone https://github.com/mitsustainabledesignlab/globi.git
cd globi
make install
```

`make install` runs `uv sync`, installs the pre-commit hooks, and generates the database client that `epinterface` uses (`epi prisma generate`).

### Environment files

The `make` commands load settings from `.env.*` files in the repository root:

| File                                             | Purpose                                                                                                  |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `.env`                                           | Chooses which set of files to use (`AWS_ENV`, `HATCHET_ENV`). Created from `.env.example` automatically. |
| `.env.local.aws` / `.env.local.host.aws`         | Local S3 (localstack). Committed, no changes needed.                                                     |
| `.env.local.hatchet` / `.env.local.host.hatchet` | Hatchet token. Written by `make hatchet-token`; not committed.                                           |
| `.env.scythe.*`                                  | Bucket name and worker settings. Committed.                                                              |

Commands that run **inside Docker** (`make cli`, the workers) use the `local` files. The commands that run **on your computer** (`make cli-native`, `make viz-native`) use the `local.host` files.

### Input files

Git ignores `inputs/`, so a new clone has no `inputs/` folder. The sample inputs are in `examples/tutorial/`. Start with the [sample-buildings tutorial](../run-simulations/tutorial.md).

Put your own GIS files and configs in `inputs/`. Then Git ignores them, and the Docker containers can see them.

### Optional: EnergyPlus

You need EnergyPlus on your computer only to run simulations without Docker. See [Install EnergyPlus](install-energyplus.md).

---

## Troubleshooting make on Windows

Do these checks in **Git Bash**. Click a problem to see the cause and the fix.

??? problem "`bash: make: command not found`"

    **Cause:** `make` is not on Git Bash's PATH. Run `which make`: if nothing prints, this is the problem.

    **Fix:**

    1. For winget installs, add the folder as in Step 4 (`/c/Program Files (x86)/GnuWin32/bin`). Then run `source ~/.bashrc`.
    2. Check that the file exists: `ls "/c/Program Files (x86)/GnuWin32/bin/make.exe"`.
    3. Close and open the terminal again. In VS Code, quit and restart VS Code fully.

??? problem "`make` works in PowerShell but not in Git Bash (or the other way round)"

    **Cause:** PowerShell reads the Windows `Path` setting. Git Bash also reads `~/.bashrc`.

    **Fix:** use Git Bash, and correct the PATH there.

??? problem "`'bash' is not recognized`, `'cp' is not recognized` or `process_begin: CreateProcess(NULL, ...) failed`"

    **Cause:** you ran `make` in PowerShell or Command Prompt. The targets need a Unix shell.

    **Fix:** open Git Bash and run the command again.

??? problem "`uv: command not found` or `docker: command not found` inside make"

    **Cause:** the tool is installed, but it is not on Git Bash's PATH.

    **Fix:** uv installs to `~/.local/bin`:

    ```bash
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
    ```

    For Docker, start Docker Desktop. Then open a new terminal.

??? problem "Arguments that start with `/` change (e.g. `/tmp/out` becomes `C:/Program Files/Git/tmp/out`)"

    **Cause:** Git Bash converts paths that look like Unix paths for Windows programs.

    **Fix:** use paths relative to the repository root (for example, `outputs/my-run`), or put `MSYS_NO_PATHCONV=1` in front of the command.

??? problem "`make: *** No rule to make target`"

    **Cause:** you are not in the repository root.

    **Fix:** use `cd` to go to the folder that contains `Makefile`.
