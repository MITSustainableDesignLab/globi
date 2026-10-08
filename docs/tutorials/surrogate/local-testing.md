# Test the surrogate pipeline locally

GloBI can replace EnergyPlus with a machine-learned _surrogate_: a regressor trained on
simulations of buildings whose uncertain attributes (semantic fields, window-to-wall
ratio, floor-to-floor height, ...) are drawn from **priors**, rather than fixed by the
GIS data. In production this runs as the `iterative_training` Hatchet workflow with
results on S3.

This page describes the **local harness** in `globi.validation`, which runs the same
stages in-process on one machine (no Hatchet server, no S3), on a small sample, and
then **validates** the surrogate against the standard _deterministic_ GloBI run — the
same buildings simulated with EnergyPlus using exactly the semantic field values in the
GIS data.

The local harness is a **plumbing test**: it proves that prior-sampled training specs
and GIS-defined hold-out specs go through the real runnable to the same feature index,
and that a trained surrogate can predict the hold-out. At the sizes that run on a
laptop the metrics are noise; a hold-out validation worth reading is an at-scale run on
the Hatchet stack (see below).

## The pipeline, stage by stage

| Stage       | Hatchet task (`pipelines/training.py`)                    | Local equivalent (`globi.validation.local_runner`)                                                                                                                                            |
| ----------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Sample   | `create_simulations`                                      | `sample_training_specs` — pick rows of the GIS _context_ (stratified by weather file) and fill in prior-sampled attributes with `Priors.sample`; validate each row into a `GloBIBuildingSpec` |
| 2. Simulate | scythe scatter/gather of `simulate_globi_building`        | `simulate_specs_locally` — runs the registered task in-process via `mock_run`, with a per-spec parquet cache and optional worker processes                                                    |
| 3. Combine  | `combine_results`                                         | `combine_with_previous` — append this iteration's results to the growing simulation cache                                                                                                     |
| 4. Train    | `start_training` → `train_regressor_with_cv_fold` × folds | `train_folds_locally` — one `TrainFoldSpec.train()` per fold, saving `regressor` + `transforms.yml`                                                                                           |
| 5. Evaluate | `evaluate_training`                                       | fold-averaged test metrics (`fold_test_averages`) + `ConvergenceThresholdsByTarget.run`                                                                                                       |
| 6. Recurse  | `transition_recursion`                                    | the loop in `run_local_iterative_training`: stop when converged or at `max_iters`, else bump `current_iter` and go to 1                                                                       |
| 7. Finalize | `finalize`                                                | `summary.yml` + `combined_metrics/`                                                                                                                                                           |

Features are the result frame's **index** (every scalar `GloBIBuildingSpec` field plus
`computed_features`: `feature.geometry.*`, `feature.semantic.*`,
`feature.extra_spaces.*`); targets are the flattened result **columns**, named
`<key>/<Measurement>/<Aggregation>/<Meter>` (e.g.
`EnergyAndPeakAnnual/Energy/Raw/Heating`, kWh/m²).

## Quick start (no EnergyPlus needed)

The `dummy_simulation` runnable is an analytic stand-in for EnergyPlus; the whole loop
runs in well under a minute for all three backends:

```bash
uv sync --all-extras          # xgboost, lightgbm, torch
make surrogate-local          # == globi tests surrogate-local --config tests/data/surrogate_local/validation-dummy.yml
make surrogate-validate
```

## Real run on the e2e test region

`tests/data/surrogate_local/validation-e2e.yml` uses the 1000-building test region in
`tests/data/e2e/`. EnergyPlus must be installed locally (see `energyplus_versions.json`)
and the Boston EPW is downloaded once.

```bash
make surrogate-local    SURROGATE_CONFIG=tests/data/surrogate_local/validation-e2e.yml SURROGATE_WORKERS=4
make surrogate-validate SURROGATE_CONFIG=tests/data/surrogate_local/validation-e2e.yml SURROGATE_WORKERS=4
```

The profile is 16 training + 4 validation simulations (≈30 s with 4 workers on a
laptop). The simulation cache (keyed on the spec _and the contents_ of the db /
semantic fields / component map files) makes re-runs incremental.

### What happens

1. `n_test` buildings are chosen at random from the GIS data and **held out**
   (`<workdir>/holdout.json`). They never enter the training context. The file also
   records the settings that chose them (`seed`, `n_test`, manifest, GIS/semantic
   fields hash); running with different settings against the same `workdir` is an
   error, since re-drawing the hold-out after training would let training buildings
   leak into the validation set. Change `n_test`/`seed` together with `workdir`.
2. The remaining buildings become the training **context** (`context.parquet`):
   footprint geometry, neighbours, floors and weather file only. Semantic fields, wwr,
   f2f height, basement/attic are stripped and re-sampled from priors
   (`default_priors_from_semantic_fields`: uniform over each categorical field's
   options, uniform over `[Min, Max]` for numeric fields).
3. Training runs as above, one surrogate per configured backend, into
   `<workdir>/training/<backend>/`.
4. The validation step simulates the held-out buildings **deterministically** (semantic fields
   exactly as in the GIS data, no priors) and predicts them with the ensemble of fold
   models. Outputs in `<workdir>/validation/<backend>/`:
   - `report.md` — global metrics (MAE/RMSE/R²/CV(RMSE)/nMBE/MAPE), area-weighted stock
     totals, per-fold vs ensemble, and breakdowns by every `feature.semantic.*` column;
   - `per_building.parquet`, `predictions.parquet`, `metrics_*.parquet`,
     `aggregate.parquet`.

Categorical values that appear in the validation set but never in training are flagged
(`has_unseen_category`) and metrics are additionally reported on the seen-only subset.

## Configuration

`LocalValidationConfig` (`globi.validation.config`) is a small yaml; see the two fixtures
for annotated examples. Notable knobs:

- `backends`: a list of `ml_backend: xgb | lgb | nn` entries with their `hp` / `trainer`
  configs — one surrogate is trained per entry.
- `n_per_iter`, `min_per_stratum`, `max_iters`, `n_folds`, `thresholds`.
- `targets_globs` (default `EnergyAndPeakAnnual/Energy/Raw/*`).
- `exclude_columns` (default `building_id`, `rotated_rectangle`, `height`).

## Pitfalls worth knowing

- **Leaky index columns.** `rotated_rectangle` and `building_id` are unique per building
  and would be index-encoded as categorical features; `height` is not used by the
  simulator (it derives from `f2f_height × num_floors`). Keep them in `exclude_columns`.
- **Targets must share an index.** Restrict `targets_globs` to one result key
  (`EnergyAndPeakAnnual/...`); mixing in the monthly `EnergyAndPeak` frame or overheating
  frames fails the "identical indices" check in `TrainFoldSpec.combined_data`.
- **NN batch size.** The NN trainer drops incomplete batches (train _and_ validation).
  With tiny data, `batch_size` must be smaller than the rows in one fold or the model
  early-stops untrained.
- **LightGBM on small data.** Set `hp.min_data_in_leaf` (lightgbm's default of 20
  yields near-constant predictions on tens of samples).
- **Basement/attic priors.** With `fixed_basement_attic: true` (default) the
  `GloBIBuildingSpec` validators are deterministic; otherwise attic height / use
  fractions are drawn from numpy's global RNG (seeded by the harness).
- **Hatchet env.** Importing `globi.pipelines` builds a Hatchet client; the harness
  (and `tests/conftest.py`) populates offline-safe defaults from
  `.env.local.host.hatchet.example` when the variables are unset.

## Running the real workflow on the local docker stack

The Hatchet workflow itself can be exercised with docker + hatchet-lite + localstack S3
(no AWS account):

```bash
make hatchet-token && make engine   # hatchet-lite, localstack, fanout + simulation workers
make training-native                # a training worker on the host (the compose `training`
                                    # service requests a GPU; the host worker just carries
                                    # the HAS_GPU label and falls back to CPU)
make cli-native tests surrogate-stack-manifest -- --config tests/data/surrogate_local/validation-e2e.yml --out outputs/surrogate-stack/training.yml
make cli-native submit surrogate -- --path outputs/surrogate-stack/training.yml
```

`surrogate-stack-manifest` uploads the context, component library, semantic fields and
component map to the configured scythe bucket and writes a `ProgressiveTrainingSpec`
with s3 references; the run then proceeds exactly as in production. Progress is visible
in the Hatchet UI (see _Simulation Tasking_).

## Tests

```bash
uv run pytest                          # fast: dummy runnable, all backends (~45 s)
uv run pytest --run-energyplus         # + the EnergyPlus-backed smoke run (~90 s total)
```
