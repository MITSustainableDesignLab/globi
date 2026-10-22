# Tutorial: edit the model in sbem-ui

A GloBI model has four inputs:

| Input             | File in the tutorial    | What it holds                                                                                     |
| ----------------- | ----------------------- | ------------------------------------------------------------------------------------------------- |
| GIS file          | `buildings-100.geojson` | Building footprints and their attributes                                                          |
| Semantic fields   | `semantic-fields.yml`   | The attributes that describe a building (`Typology`, `Age_bracket`, ...) and their allowed values |
| Component map     | `component-map.yml`     | Which semantic fields choose each part of the energy model                                        |
| Component library | `components-lib.db`     | The parts themselves: constructions, windows, lighting, setpoints, HVAC, schedules                |

**sbem-ui** is a browser app with one page for each input. In this tutorial, you open the sample-buildings model in sbem-ui and make one change on each page. Then you run the buildings again with your edited model.

!!! warning "Experimental"

    Ask the GloBI team for access to sbem-ui before you start. The sbem-ui repository is private, and the app is under active development.

## Before you start

- Complete [section A of the sample-buildings tutorial](tutorial.md#a-one-building) (one building). The batch run in step 8 also needs section B (100 buildings).
- Install [Node.js](https://nodejs.org/) 18 or newer. To check the version, run `node --version`.
- Clone sbem-ui **next to** your `globi` folder. The two folders must be in the same parent folder:

  ```
  your-folder/
  ├── globi/
  └── sbem-ui/
  ```

!!! note "Windows: use Git Bash"

    Run all commands on this page in **Git Bash**, as in the main tutorial. If `make` is not found, see [Troubleshooting make on Windows](../getting-started/requirements.md#troubleshooting-make-on-windows).

---

## Step 1: Install sbem-ui

```bash
cd sbem-ui
make setup
```

`make setup` installs the Python environment (with GloBI from `../globi`), generates the database client and installs the frontend packages. The first time, it takes a few minutes.

sbem-ui uses the same `epinterface` version as GloBI. Thus GloBI can read a model that you edit in sbem-ui.

## Step 2: Copy the tutorial model

Edit a copy, not the original tutorial files. From the `globi` folder, run:

```bash
cp -r examples/tutorial/sbem-project inputs/my-model
cp tests/data/e2e/components-lib.db tests/data/e2e/semantic-fields.yml tests/data/e2e/component-map.yml inputs/my-model/
```

The folder `inputs/my-model/` now contains these files:

| File                                                            | Used by | Purpose                                                                 |
| --------------------------------------------------------------- | ------- | ----------------------------------------------------------------------- |
| `project.json`                                                  | sbem-ui | Marks the folder as an sbem-ui project and tells it which files to edit |
| `semantic-fields.yml`, `component-map.yml`, `components-lib.db` | both    | The model you edit                                                      |
| `building.yml`, `artifacts.yml`, `manifest.yml`                 | globi   | Configs for running one building or the batch with this model           |

The folder is in `inputs/` because the Docker workers can only see some folders, and `inputs/` is one of them.

## Step 3: Open the model in sbem-ui

1. Start sbem-ui from the `sbem-ui` folder:

   ```bash
   make dev
   ```

   Keep this terminal open. The app runs at <http://localhost:5173>, and its backend uses port 8000. To stop the app, press `Ctrl+C`.

2. Open <http://localhost:5173>. On **Open a project**, select **Open existing**.
3. Enter the **Folder path** of your copy. The path must be absolute. To get it, run `pwd` in the `globi` folder and add `/inputs/my-model`.

   ```text
   macOS / Linux:  /Users/you/your-folder/globi/inputs/my-model
   Windows:        C:/Users/you/your-folder/globi/inputs/my-model
   ```

   On Windows, run `pwd -W` in Git Bash to get the path in the `C:/...` form.

4. Click **Open project**. The sidebar shows the pages. This tutorial uses the first four pages.

This tutorial does not cover the other pages (**Prior Trees**, **Retrofits**, **Sampling**, **Model Execution**). These pages are for stochastic models.

## Step 4: GIS Cleaning

The GIS Cleaning page checks that your GIS file has the columns that GloBI needs.

1. Under **1. Upload GIS data**, select `examples/tutorial/buildings-100.geojson` in the `globi` folder. Click **Upload**. The page shows 100 rows.
2. Under **2. Match columns**, look at the suggested columns for building ID, number of floors and height. For this file, sbem-ui suggests `building_id`, `num_storeys` and `height`.
3. Optionally, select `id` for the building ID. GloBI uses the `id` column, because `semantic-fields.yml` names it. Both columns have a unique value for each building.
4. Under **4. Validate**, click **Validate**. The page shows no issues.

In this tutorial, you use the GIS page only to check the data. GloBI continues to read `examples/tutorial/buildings-100.geojson`, as set in `inputs/my-model/artifacts.yml`.

## Step 5: Semantic Fields

Click **Semantic Fields**. The page shows the five fields of the tutorial model: `Region`, `Typology`, `Age_bracket`, `Income` and `Scenario`. Select a field to see its options. For example, `Typology` has `Office`, `School`, `Residential`, `Hospital` and `Hotel`.

Each option must be in three places:

1. As a value in the GIS file column with the same name.
2. In `semantic-fields.yml` (this page).
3. In the names of the components that the option selects (step 6).

Thus, a new option (for example `Warehouse`) also needs warehouse buildings in the GIS file and warehouse components in the component library. For this tutorial, do not change the fields. If you change a field, click **Save**. To go back to the last saved version, click **Revert**.

## Step 6: Component Map

Click **Component Map**. The component map selects four top-level components for each building. It joins the semantic field values of the building with `_` to make each component name:

| Component  | Name built from                         | Example (residential, post-2000, low income, Baseline) |
| ---------- | --------------------------------------- | ------------------------------------------------------ |
| `Envelope` | Region, Typology, Scenario, Age_bracket | `TestRegion_Residential_Baseline_Post_2000`            |
| `SpaceUse` | Region, Typology, Income, Scenario      | `TestRegion_Residential_Low_Baseline`                  |
| `HVAC`     | Region, Typology, Scenario, Age_bracket | `TestRegion_Residential_Baseline_Post_2000`            |
| `DHW`      | Region, Typology                        | `TestRegion_Residential`                               |

To see the names that a selector builds, click **Preview names**.

Make a change that GloBI cannot build, and see how the check finds the error:

1. Under **Operations → SpaceUse**, remove `Income` from the fields of the selector.
2. Click **Save & check library**. The check reports that all sampled combinations have no record (`Library check: ... sampled combinations have no record`). It also shows an error like `TestRegion_Hotel_Retrofit not found`.
3. Add `Income` again in its initial position (after `Typology`).
4. Click **Save & check library** again. The check reports `Library check passed`.

The check fails in step 2 because the map now builds SpaceUse names without `Income`, such as `TestRegion_Hotel_Retrofit`. The component library has only `TestRegion_Hotel_Low_Retrofit` and `TestRegion_Hotel_High_Retrofit`.

Change the component map when you add components. For example, to give each age bracket its own lighting, create the matching records in the component library. Then add `Age_bracket` to the selector.

## Step 7: Component Library

Each top-level component refers to smaller components. For example, a `SpaceUse` record names its `Lighting`, `Equipment`, `Occupancy`, `Thermostat` and `WaterUse` components.

Records can share a smaller component. In the sample component library, all four residential `SpaceUse` records (low and high income, Baseline and Retrofit) use the same `Lighting` record, `TestRegion_Residential`. A change to this record changes all residential buildings in the two scenarios.

Each scenario has its own `Thermostat` record (`TestRegion_Residential_Baseline`, `TestRegion_Residential_Retrofit`). A change to one of these records changes only that scenario. To see the components that a record uses, open the record with **Edit**. The form shows the linked components by name.

For example, to double the lighting power in residential buildings:

1. In the sidebar, click **Component Library**.
2. Under component types, click **Lighting**.
3. Find `TestRegion_Residential` and click **Edit**.
4. Change **PowerDensity** from `6.5` to `13` (W/m²).
5. Click **Save**.

sbem-ui writes the change to `inputs/my-model/components-lib.db` immediately.

## Step 8: Run with your model

### One building

```bash
make cli-native simulate -- --config examples/tutorial/building.yml --output-dir outputs/model-original
make cli-native simulate -- --config inputs/my-model/building.yml --output-dir outputs/my-model-building
```

If you run EnergyPlus in Docker, use `make cli` instead of `make cli-native`.

Compare the **End Uses** that the two runs print. Lighting doubles, from approximately 18.7 to 37.4 kWh/m². The total energy increases less, from approximately 176 to 185 kWh/m². The cause is the heat from the lights, which decreases the heating energy.

### 100 buildings

Start the local stack from [section B](tutorial.md#b-100-buildings-baseline). Then run:

```bash
make cli submit manifest -- --path inputs/my-model/manifest.yml
make cli-native get experiment -- --run-name GloBI_Tutorial_MyModel/Baseline
```

Before the batch run starts, `submit manifest` checks that GloBI can build each building from your edited model.

To compare the results with the original run, use the viewer ([section E](tutorial.md#e-explore-results)). Open **Use Cases → Scenario Comparison** and select `GloBI_Tutorial/Baseline/...` and `GloBI_Tutorial_MyModel/Baseline/...`. Only the residential buildings change.

---

## Going further

- **Change other components** in the same way: window U-values (`GlazingConstructionSimple`), constructions (`ConstructionAssembly`), heating and cooling setpoints (`Thermostat`), schedules (`Day`, `Week`, `Year`).
- **Add a component** with **+ Add ...**. Then connect a parent record to it. For example, set the `Lighting` of a `SpaceUse` record to your new record.
- **Be careful when you rename or delete records.** GloBI finds top-level components by name, and parent records refer to child records by name. **Save & check library** on the Component Map page and `submit manifest` both find missing components before the simulation starts.

## Troubleshooting

Click a problem to see the cause and the fix.

??? problem "`make setup` fails with `npm: command not found` or `node: command not found`"

    **Cause:** Node.js is not installed, or it is not on the PATH of your terminal.

    **Fix:**

    1. Install Node.js 18 or newer from <https://nodejs.org/>.
    2. Open a new terminal. On Windows, open a new Git Bash window. In VS Code, restart VS Code.
    3. Run `node --version`, then run `make setup` again.

??? problem "`make setup` fails at `prisma generate`"

    **Cause:** this step downloads a database engine from the Prisma servers, so it needs internet access. Some university or company networks block the download.

    **Fix:**

    1. Connect to a different network, or turn off the VPN.
    2. Run `make prisma-generate` again.
    3. If the step fails again, send the full error to the GloBI team.

??? problem "`make setup` fails with an error about `../globi`"

    **Cause:** sbem-ui installs GloBI from a folder with the name `globi` next to the `sbem-ui` folder. That folder is missing or has a different name.

    **Fix:**

    1. Put `sbem-ui` and `globi` in the same parent folder.
    2. Check that the GloBI folder has the name `globi`.
    3. Run `make setup` again.

??? problem "`is not a project workspace (missing project.json)` when opening"

    **Cause:** the folder path is wrong, or step 2 did not run. If `inputs/my-model` existed before step 2, `cp -r` copied the template into `inputs/my-model/sbem-project/`.

    **Fix:**

    1. Run `ls inputs/my-model`. The output must show `project.json` and the files from step 2.
    2. If the files are not there, run `rm -rf inputs/my-model`. Then do step 2 again (the two `cp` commands).
    3. Use the absolute path: the output of `pwd` (or `pwd -W` on Windows), plus `/inputs/my-model`.

??? problem "The Semantic Fields or Component Map page is empty or shows a template picker"

    **Cause:** sbem-ui opened a different folder, or the files from step 2 are missing.

    **Fix:**

    1. Check that `inputs/my-model/semantic-fields.yml` and `inputs/my-model/component-map.yml` exist.
    2. Open the project again with **Open existing**.

??? problem "The page at localhost:5173 does not load, or shows errors when loading"

    **Cause:** `make dev` is not running or stopped with an error, or a different program uses port 5173 or 8000.

    **Fix:**

    1. Look for errors in the `make dev` terminal.
    2. Check the ports: run `lsof -i :8000` on macOS/Linux, or `netstat -ano | grep 8000` in Git Bash. Close the other program.
    3. Run `make dev` again.

??? problem "**Save & check library** reports combinations with no record"

    **Cause:** the component map builds a name that is not in the component library. For example, you removed a field from a selector, or renamed or deleted a record.

    **Fix:** read the missing name in the error. Then do one of these steps:

    - Change the selector back. **Revert** goes back to the last saved map.
    - In **Component Library**, create a record with exactly that name.

??? problem "Results did not change after editing"

    **Cause:** GloBI reads the original files, or the buildings that you ran do not use the record that you edited.

    **Fix:**

    1. Run the configs in `inputs/my-model/` (`building.yml` or `manifest.yml`), not the configs in `examples/tutorial/`.
    2. Check that you clicked **Save** in sbem-ui. Open the record again with **Edit** to see the saved value.
    3. Use [step 6](#step-6-component-map) and [step 7](#step-7-component-library) to find the records that the buildings use.

??? problem "`No such file or directory` for the model files when using `make cli`"

    **Cause:** Docker can only see `inputs/`, `outputs/`, `examples/` and `tests/data/e2e/`. A model in a different folder (for example, your Documents folder) is not available in the container.

    **Fix:** keep the model in `inputs/`. In the configs, use relative paths like `inputs/my-model/components-lib.db`.
