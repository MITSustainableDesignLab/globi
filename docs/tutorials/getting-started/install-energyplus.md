# Install EnergyPlus (native runs only)

Use this page only to run simulations **without Docker** (the `make cli-native ...` commands). The Docker workers already include EnergyPlus.

GloBI uses **EnergyPlus 25.2.0**. The worker image (`src/globi/worker/Dockerfile`) installs the same version. With the same version, your local results match the Docker results.

## Step 1: Download and install

Download the installer for your operating system from the [EnergyPlus v25.2.0 release page](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v25.2.0).

=== "macOS"

    1. Download the macOS installer for your chip (`arm64` for Apple Silicon, `x86_64` for Intel).
    2. Run the installer. Keep the default location, `/Applications/EnergyPlus-25-2-0`.
    3. If macOS blocks the installer, open **System Settings → Privacy & Security** and click **Open Anyway**.

=== "Linux"

    1. Download the `Linux-Ubuntu22.04` `.tar.gz` for your architecture. The file `energyplus_versions.json` in the repository root lists the exact URLs.
    2. Extract the file to `/usr/local/EnergyPlus-25-2-0`:

       ```bash
       tar -xzf EnergyPlus-25.2.0-*-Linux-Ubuntu22.04-*.tar.gz
       sudo mv EnergyPlus-25.2.0-*-Linux-Ubuntu22.04-*/ /usr/local/EnergyPlus-25-2-0
       ```

=== "Windows"

    1. Download the `.exe` installer (or the `.zip`) for Windows.
    2. Install to the default location, `C:\EnergyPlusV25-2-0`.
    3. Run all `make` commands in **Git Bash** (see [Install make](requirements.md#step-4-install-make)).

## Step 2: How GloBI finds EnergyPlus

GloBI searches these default locations:

| OS      | Searched folders            |
| ------- | --------------------------- |
| macOS   | `/Applications/EnergyPlus*` |
| Linux   | `/usr/local/EnergyPlus*`    |
| Windows | `C:\EnergyPlus*`            |

GloBI reads the version from the folder name. Keep the version in the name, for example `EnergyPlus-25-2-0`.

If you installed EnergyPlus in a different folder, set `ENERGYPLUS_LOCATION` to that folder. To keep the setting, add the line to your shell profile (`~/.zshrc` on macOS, `~/.bashrc` on Linux and in Git Bash):

=== "macOS / Linux"

    ```bash
    export ENERGYPLUS_LOCATION=/path/to/EnergyPlus-25-2-0
    ```

=== "Windows (Git Bash)"

    ```bash
    export ENERGYPLUS_LOCATION="C:/path/to/EnergyPlusV25-2-0"
    ```

    Use the `C:/...` form with forward slashes, not `/c/...`.

If you have **several versions installed**, GloBI uses the newest version. To use a specific version, export `EPINTERFACE_ENERGYPLUS_VERSION` in the same way. You can also add the line (without `export`) to the `.env` file in the repository root:

```bash
export EPINTERFACE_ENERGYPLUS_VERSION=25.2.0
```

!!! note

    Set `ENERGYPLUS_LOCATION` in your shell. The `.env` file works only for `EPINTERFACE_ENERGYPLUS_VERSION`.

## Step 3: Check that it works

Check EnergyPlus:

=== "macOS"

    ```bash
    /Applications/EnergyPlus-25-2-0/energyplus --version
    ```

=== "Linux"

    ```bash
    /usr/local/EnergyPlus-25-2-0/energyplus --version
    ```

=== "Windows (Git Bash)"

    ```bash
    /c/EnergyPlusV25-2-0/energyplus.exe --version
    ```

The output is `EnergyPlus, Version 25.2.0-...`. Then check that GloBI can find and run EnergyPlus. The commands are the same on all operating systems:

```bash
cp .env.local.host.hatchet.example .env.local.host.hatchet   # first time only, see note
make cli-native simulate -- --config examples/tutorial/building.yml --output-dir outputs/tutorial
```

The simulation takes a few seconds and prints a results summary.

!!! note "Why the Hatchet env file?"

    Copy the example file before the first native run. `make cli-native` always loads `.env.local.host.hatchet`. A single-building run does not connect to Hatchet, so the example file is sufficient. Later, `make hatchet-token` replaces the file with a real token for batch runs.

## Troubleshooting

Click a problem to see the cause and the fix.

??? problem "`EnergyPlusVersionError ... is not installed`"

    **Cause:** GloBI did not find the EnergyPlus version folder.

    **Fix:** check the folder name and `ENERGYPLUS_LOCATION`.

??? problem "Warnings like `Version: in IDF=\"22.2\" not the same as expected=\"25.2\"`"

    **Cause:** the generated model has the version tag 22.2.

    **Fix:** nothing to do. These warnings are expected, and the model runs correctly on 25.2.

??? problem "Results differ from the Docker run"

    **Cause:** a different EnergyPlus version is used.

    **Fix:** use 25.2.0 (set `EPINTERFACE_ENERGYPLUS_VERSION`).
