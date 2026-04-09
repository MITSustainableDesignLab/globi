# Use cases

Globi produces detailed building energy outputs (for example `EnergyAndPeak.pq` parquets and related artifacts). Those results can support many kinds of analysis: policy and retrofit comparisons, adoption and willingness-to-pay modeling, emissions accounting, and other workflows that build on fleet-scale simulation.

**Those downstream use cases are maintained in a separate repository** so this core globi codebase stays focused on simulation, visualization, and shared tooling. Analysis-specific apps, sample data layouts, and pipeline code for WTP, adoption curves, and emissions live here:

**[github.com/daryaguettler/globi-use-cases](https://github.com/daryaguettler/globi-use-cases)**

## What you will find there

The [globi-use-cases](https://github.com/daryaguettler/globi-use-cases) repo includes tools and a Streamlit app for:

1. **Energy and policy impacts** - Compare baseline vs retrofit scenario parquets (per year) for energy and peak differences.
2. **Propensity** - Per-building acceptance probabilities (residential logit with census-backed demographics; commercial NPV threshold).
3. **Uptake** - Adoption curves from JSON so buildings adopt over time from propensity and curve targets.
4. **Emissions** - Adopted floor area and fuel mix with editable emissions-factor trajectories.

The main UI covers upload, configuration, curve selection, emissions editing, and a full pipeline run with charts and tables. Bundled sample inputs under `data/inputs/` let you explore the app without new globi runs.

For the full feature list, scenario editor, Docker, data layout table, and `split_scenarios.py` usage, see that repository's [README](https://github.com/daryaguettler/globi-use-cases/blob/main/README.md).

## Download the repository

Clone with Git (recommended so you can pull updates):

```bash
git clone https://github.com/daryaguettler/globi-use-cases.git
cd globi-use-cases
```

Alternatively, download a ZIP from the repo's **Code** menu on GitHub and extract it, then `cd` into the extracted folder.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) as the package manager

## Set up the environment

From the repository root:

```bash
uv sync
```

The project's Makefile sets `PYTHONPATH=src` for local runs so `app` and `use_cases` imports resolve; prefer the Make targets below unless you set `PYTHONPATH` yourself.

## Run the analysis app

```bash
make run
```

Equivalent:

```bash
PYTHONPATH=src uv run streamlit run src/app/wtp_app.py
```

Open the URL Streamlit prints (by default [http://localhost:8501](http://localhost:8501)).

High-level flow in the app: upload baseline and scenario `EnergyAndPeak.pq` pairs, configure costs and options in the sidebar, choose adoption curves and emissions trajectories, then run the pipeline and review results.

Optional: a separate scenario editor UI is available with `make editor`. For Docker, use `make docker-build` and `make docker-run` as described in the upstream README.
