# Tutorial: build a model in sbem-ui

In [edit the model](edit-components.md), you change a model that already exists. This tutorial builds a model for 100 buildings, in one of two ways:

- **[Part A: start from a blank library.](#part-a-start-from-a-blank-library)** You decide what sets the buildings apart, build the components that differ, plan a retrofit and make GloBI's run files.
- **[Part B: start from ResStock.](#part-b-start-from-resstock)** You pick wall and heating options from NREL's ResStock, so their values come ready-made. Then you adapt them.

Each part takes about 45 minutes. Part B does not need Part A.

!!! warning "Experimental"

    sbem-ui is under active development. Ask the GloBI team for access before you start. Labels on screen can differ slightly from this page.

## Before you start

1. Install sbem-ui: do [step 1 of edit the model](edit-components.md#step-1-install-sbem-ui) (`make setup`).
2. Install EnergyPlus for native runs: see [Install EnergyPlus](../getting-started/install-energyplus.md). The single-building runs on this page use it.
3. Start the app from the `sbem-ui` folder, and keep the terminal open:

   ```bash
   make dev
   ```

4. Open <http://localhost:5173>.

A few things work the same on every page:

- **Sidebar.** The numbered steps go from top to bottom. A green tick means that the step is ready. **Component Library**, **Single Building**, **Simulations** and **Project Files** are tools below the steps.
- **Save.** Nothing reaches GloBI until you click **Save** on the page. When everything is saved, the button is grey.
- **Help text.** At the bottom of the sidebar, select **Explain** to show a short explanation under each section.

Four words appear often:

| Word on screen   | Meaning                                                                             | GloBI file             |
| ---------------- | ----------------------------------------------------------------------------------- | ---------------------- |
| Characteristic   | Something that sets buildings apart, with a few values (for example, `Age_bracket`) | `semantic-fields.yaml` |
| Component        | One version of a part of the model, such as one wall or one heating system          | `components-lib.db`    |
| Component map    | For each part, the characteristic that decides it and the component each value gets | `component-map.yaml`   |
| Retrofit package | A change to test, such as "every heating system becomes a heat pump"                | `Scenario` field       |

---

## Part A: start from a blank library

### A1. Create the project

1. On **Open a project**, select **Create new**. If a project is open, first click **Switch project** at the bottom of the sidebar.
2. **Project name**: `My model`.
3. **Component library**: **GloBI starter library**. It has GloBI's 265 construction materials, its schedules and one complete residential building, which every part starts from. You build the other components yourself.

   Do not select **Empty**. The wall builder in step A4 needs the materials.

4. **Folder path**: change it to a folder in GloBI's `inputs/`, for example `/Users/you/your-folder/globi/inputs/my-model`. Batch runs in Docker can only see some folders, and `inputs/` is one of them.
5. Click **Create project**. The app opens **GIS Cleaning**.

### A2. Load the buildings

1. Click **Use sample buildings (100)**. The page shows `buildings-100.geojson · 100 rows · 22 columns`. To use your own buildings, upload a CSV or GeoJSON file instead.
2. Under **Match columns**, check the suggestions: **Building ID** `building_id`, **Number of floors** `num_storeys`, **Building height** `height`. Leave the other rows on **Not mapped**. GloBI uses typical values for them.
3. Under **Check for missing values**, keep the suggestion.
4. Click **Validate**. The page shows **Validated**, and **GIS Cleaning** gets a tick.

This tutorial uses three columns: `YEAR_BUILT` (1900 to 2020), `use` (Single family, Apartment, Office, Primary school, Secondary school, Hospital, Hotel) and `MAINHEAT` (Gas_Radiator, Oil_Radiator, Electric_Direct). The file also has columns such as `Typology` and `WALLS`. Ignore them: in the next step you make your own groups from the raw data.

### A3. Describe the buildings

Click **Building Characteristics**. Each column of your file is a chip under **What does your data already tell you?** Click a chip to add a characteristic.

**Age bands from the year built**

1. Click the `YEAR_BUILT` chip. At the top of its card, rename it to `Age_bracket`.
2. In **Values**, type `Pre_1980, 1980_to_2000, Post_2000`. The **Rule type** is **Numeric ranges**.
3. In the **Ranges** table, enter **Min** and **Max**: `0`–`1979`, `1980`–`2000`, `2001`–`2100`.
4. Check the bars below the table: about 32, 32 and 36 buildings.

**Building types from the use**

1. Click **Add**, then the `use` chip. Rename it to `Typology`.
2. In **Values**, type `Residential, Office, School, Hospital, Hotel`. The **Rule type** is **Categorical mapping**. A red **no value** bar shows 58 buildings that have no type yet.
3. In **Value mapping**, set what each use becomes: Single family and Apartment become `Residential`. Primary school and Secondary school become `School`. Office, Hospital and Hotel stay the same. The red bar disappears.

**Heating from the file**

1. Click **Add**, then the `MAINHEAT` chip.
2. In **Values**, add `, HeatPump` at the end. No building has a heat pump yet, but the retrofit in step A5 needs the value.
3. Click **Save**. The page shows **Saved**, and the step gets a tick.

### A4. Build the components

Click **Component Map**. The top right shows **0 vary · 23 default · ✓ 100 buildings run**: every part still uses the starter building, so the model already runs. Each card is one part of the model, in three groups: **Envelope**, **Systems** and **Use**. Click a card to open it.

**Walls by age, built from a U-value**

1. Click **Walls**, then **Varies by…**, then the `Age_bracket` chip. The card shows one row for each age band.
2. In the **Pre_1980** row, click the value to open the list. Click **By U-value**, type `1.1` and click **Make it**. The app builds a wall with insulation sized for that U-value and selects it. The page shows `Reached U 1.10 W/m²K`.
3. Do the same for **1980_to_2000** (`0.5`) and **Post_2000** (`0.25`).

To choose each layer and its thickness yourself, click **Build layers** instead of **By U-value**.

**Heating systems, built in the Component Library**

The starter library has one heating system. Build one for direct electric heating and one for a heat pump.

1. In the sidebar, click **Component Library**, then the **ThermalSystem** type.
2. Find the starter heating system (`ConditioningType` is `Heating`) and duplicate it.
3. Name the copy `HeatPump_COP3`. Set **ConditioningType** to `Heating`, **Fuel** to `Electricity` and **SystemCOP** to `3`. Click **Save**.
4. Duplicate it again as `Electric_COP1`, with **SystemCOP** `1`. Click **Save**.

!!! note "Heating, not Cooling"

    The library also has cooling systems, for example `TestRegion_WindowASHP_AirDuctsUninsulated`. A cooling system in a heating row makes every building with that value fail, with `1 validation error for ZoneHVACComponent`. Pick only records whose **ConditioningType** is `Heating`.

5. Go back to **Component Map**. Click **Heating**, then **Varies by…**, then `MAINHEAT`. Select:
   - **Gas_Radiator** and **Oil_Radiator**: the starter heating system. The two rows get the same colour: they share one component.
   - **Electric_Direct**: `Electric_COP1`.
   - **HeatPump**: `HeatPump_COP3`.
6. Click **Save** at the top right. The app checks all 100 buildings. The top right shows **2 vary · 21 default · ✓ 100 buildings run**.

If the badge shows **✕ doesn't run**, click it. It names the part and the number of buildings that have no component, usually a row without a selection.

In **Component Library**, the **Options in use** tab lists every component your map uses and whether it exists. Use it as a checklist. Records named `auto_…` are rebuilt from your map on every save: do not edit them.

### A5. Plan a retrofit

1. Click **Retrofits**, then **Add package**. **Package name**: `Heat pumps`.
2. **Characteristic to change**: `MAINHEAT`. **Change it to**: `HeatPump`. Click **Add**.
3. Optionally, use **Only if** to limit the measure, for example to `Age_bracket` `Pre_1980`.
4. Click **Save**. The package shows `MAINHEAT → HeatPump`.

A measure can also change a part directly: switch from **characteristic** to **model part**, then **replace with** another component, or **multiply**, **add**, **at most** or **at least** on one of its numbers (for example, wall U × 0.5).

Each package becomes one value of the `Scenario` field, next to `Baseline`. GloBI runs your buildings once for each scenario.

### A6. Choose the buildings to simulate

1. Click **Sampling**. Keep **All buildings (100)**.
2. Click **Write sampled buildings**. The page shows `100 buildings × 1 draw = 100 simulations` and then `Wrote 100 rows to gis/buildings-sampled.geojson`.

This step writes each building's characteristics as columns of the saved buildings file, which the batch run reads. Without it, GloBI's batch files are not written.

### A7. Make the run files and run one building

Click **Model Execution**.

1. Under **Readiness**, check that all lines show **Ready**. For a line that shows **To do**, click **Go to step**.
2. Under **Example building (one test run)**, describe one building: `Age_bracket` `Pre_1980`, `Typology` `Residential`, `MAINHEAT` `Gas_Radiator`, `Scenario` `Baseline`. Keep the size and the weather file.

   The example building is only for a quick test run. The batch run ignores it: each building uses its own characteristics and size from the saved buildings.

3. Click **Generate globi files**. The page shows `Wrote building.yml, artifacts.yml, gis-preprocessor.yml, manifest.yml, manifest-heat-pumps.yml`, and the commands to run them.
4. Click **Run this example**. After about 10 seconds, the end uses (kWh/m²) and peak loads show on the right.
5. Set `Scenario` to `Heat pumps` and click **Run this example** again. Only heating changes.

To run the example in a terminal instead, copy the `make cli-native simulate …` command from the page and run it in the `globi` folder.

!!! note "Defaults"

    Parts that nobody decided still use the starter building's components. Before you trust the results, look at the default count at the top of **Component Map**: each default is an assumption.

### A8. Run the 100 buildings

1. Start the local stack: in the `globi` folder, run `make hatchet-token` and then `make engine`. See [section B of the sample-buildings tutorial](tutorial.md#b-100-buildings-baseline).
2. Run the batch commands that **Model Execution** shows, one for each scenario:

   ```bash
   make cli submit manifest -- --path inputs/my-model/manifest.yml
   make cli submit manifest -- --path inputs/my-model/manifest-heat-pumps.yml
   ```

3. To see the progress, click **Simulations** in the sbem-ui sidebar (the Hatchet dashboard, <http://localhost:8888>, user `admin@example.com`, password `Admin123!!`). **Runs** shows one task for each building.
4. When the runs finish, get the results:

   ```bash
   make cli-native get experiment -- --run-name "My model/Baseline"
   make cli-native get experiment -- --run-name "My model/Heat pumps"
   ```

   The run name is the project name, then `/`, then the scenario.

!!! note "In progress"

    **Model Execution** also has **Run a sample of your buildings**, which runs a random sample of the buildings for each scenario and shows the results in the app. This button is still being connected to GloBI. Use the commands above until it is available.

### A9. The project files

Click **Project Files** to see and download each file of the project:

| File                                             | Made in                  | Holds                                           |
| ------------------------------------------------ | ------------------------ | ----------------------------------------------- |
| `semantic-fields.yaml`                           | Building Characteristics | Your characteristics and their values           |
| `part-rules.yaml`                                | Component Map            | Your decisions for each part                    |
| `component-map.yaml`                             | Component Map (on Save)  | What GloBI reads, made from the two files above |
| `components-lib.db`                              | Component Library        | The components                                  |
| `retrofits.yaml`                                 | Retrofits                | The packages                                    |
| `gis/buildings-sampled.geojson`                  | Sampling                 | The buildings, with their characteristics       |
| `building.yml`, `artifacts.yml`, `manifest*.yml` | Model Execution          | GloBI's run files                               |

`components-lib.db` is a binary file, so **Project Files** cannot show or download it. It is in the project folder.

---

## Part B: start from ResStock

ResStock™ is NREL's model of homes in the United States. It lists the options that real homes have, for example `Wood Stud, R-13` walls or an `80% AFUE` furnace. sbem-ui includes a component library converted from ResStock v3.4.0, so you select ResStock's options and their values come with them.

!!! note "ComStock"

    Only ResStock (residential) is available. ComStock (commercial buildings) is not supported yet.

### B1. Create the project and load the buildings

1. Click **Switch project**, then **Create new**.
2. **Project name**: `My ResStock model`. **Component library**: **Derived from ResStock™ v3.4.0 (residential)**. **Folder path**: a folder in GloBI's `inputs/`, for example `.../globi/inputs/my-resstock-model`.
3. Click **Create project**.
4. On **GIS Cleaning**, click **Use sample buildings (100)**, then **Validate**, as in [step A2](#a2-load-the-buildings).

### B2. Select ResStock options

Click **Building Characteristics**.

1. Under **From ResStock v3.4.0**, click **Insulation Wall** (46 options). Select `Wood Stud, Uninsulated`, `Wood Stud, R-13` and `Wood Stud, R-19`. Click **Add with 3 options**.
2. The sample buildings do not record wall insulation, so select **Estimate it**. Keep **Even split** and click **Generate the odds**. Each building now has a one-in-three chance of each wall.

   With real data, set the shares that your region has. **Depends on** makes the odds depend on another characteristic, for example the age band.

3. Click **Add**, then **From ResStock v3.4.0**, then **HVAC Heating Efficiency** (51 options). Select `Fuel Furnace, 80% AFUE` and `ASHP, SEER 15, 9.0 HSPF`. Click **Add with 2 options**, then **Estimate it**, then **Generate the odds**.
4. Optionally, open **How ResStock's values were converted**. For example, R-values are multiplied by 0.1761 to get SI units, ACH50 is divided by 20 for air leakage, and SEER or HSPF is multiplied by 0.293 for efficiency.
5. Click **Save**. Both characteristics show **estimated**.

ResStock covers nine characteristics: wall, ceiling and roof insulation, windows, air leakage, heating, cooling, heating setpoint and water heater. All other parts (loads, schedules, ventilation) use the starter building.

### B3. Check and adapt the components

Click **Component Map**. It shows **2 vary · 21 default · ✓ 100 buildings run**. **Walls** and **Heating** already vary by your two characteristics, and you do not build anything.

1. Click **Walls**. The U-values are about 1.67 (uninsulated), 0.50 (R-13) and 0.37 (R-19) W/m²K.
2. Click **Heating**. The furnace is `NaturalGas, COP 0.8`. The heat pump is `Electricity, COP` about 2.64.
3. To adapt a value, open the record in **Component Library** and edit it. For example, change the U-value of the R-19 wall. The converted records are ordinary components. A change applies to every building that uses the record.
4. Or, in a row of **Component Map**, select a different ResStock record.
5. Click **Save**.

### B4. Optional: plan a retrofit

1. Click **Retrofits**, then **Add package**. **Package name**: `Insulate walls`.
2. **Characteristic to change**: `Insulation Wall`. **Change it to**: `Wood Stud, R-19`. Click **Add**, then **Save**.

### B5. Choose the buildings to simulate

The characteristics are estimated, so simulate each building several times, each time with a different draw.

1. Click **Sampling**. The page shows `Drawn each time: Insulation Wall, HVAC Heating Efficiency`.
2. Set **Draws per building** to `3`. The page shows `100 buildings × 3 draws = 300 simulations`.
3. Click **Write sampled buildings**. The page shows `Wrote 300 rows`.

### B6. Run one building and the batch

1. Click **Model Execution**. In **Example building (one test run)**, set **Insulation Wall** to `Wood Stud, Uninsulated` and **HVAC Heating Efficiency** to `Fuel Furnace, 80% AFUE`.
2. Click **Generate globi files**, then **Run this example**.
3. Set **Insulation Wall** to `Wood Stud, R-19` and click **Run this example** again. Heating decreases by about a fifth (in the sbem-ui workshop, from about 236 to 192 kWh/m²).
4. For the batch run, do [step A8](#a8-run-the-100-buildings) with this project's manifests.

Do not compare these results with Part A. All the parts that ResStock does not cover come from a different starting building.

---

## Troubleshooting

??? problem "A characteristic shows a red **no value** bar"

    **Cause:** a range does not cover some values, or a value of the column is not mapped yet.

    **Fix:** extend the ranges, or map the remaining values in **Value mapping**, until the bar disappears.

??? problem "The Component Map badge shows **✕ doesn't run**"

    **Cause:** some buildings have no component for a part. Usually, a row of a part has no selection.

    **Fix:** click the badge. It names the part and the number of buildings. Select a component for that row, then click **Save**.

??? problem "`1 validation error for ZoneHVACComponent`"

    **Cause:** a heating row uses a cooling system (a **ThermalSystem** record whose **ConditioningType** is `Cooling`).

    **Fix:** in **Component Map**, open **Heating** and select a record whose **ConditioningType** is `Heating` for each row. Then click **Save**.

??? problem "**Make it** says that a material is missing"

    **Cause:** the project uses the **Empty** library, which has no materials.

    **Fix:** create the project again with the **GloBI starter library** or the ResStock library.

??? problem "**Generate globi files** is grey"

    **Cause:** the component map is not saved.

    **Fix:** click **Save** on **Component Map**.

??? problem "The page says that only `building.yml` was written"

    **Cause:** no buildings are saved for the batch run.

    **Fix:** on **Sampling**, click **Write sampled buildings**. Then click **Generate globi files** again.

??? problem "The retrofit run gives the same results as Baseline"

    **Cause:** the example building still has `Scenario` set to `Baseline`, or the files were not generated again.

    **Fix:** set `Scenario` to the package, then click **Run this example** (or **Generate globi files** and run the command again).

??? problem "`No such file or directory` for the model files when using `make cli`"

    **Cause:** the project is not in GloBI's `inputs/` folder. Docker can only see `inputs/`, `outputs/`, `examples/` and `tests/data/e2e/`.

    **Fix:** create the project in `inputs/`, or move its folder there and open it again with **Open existing**.
