# Use cases

GloBI produces detailed building energy outputs, for example `EnergyAndPeak.pq`. You can use these results for many types of analysis: policy and retrofit comparisons, adoption and willingness-to-pay (WTP) models, emissions accounting, and other fleet-scale workflows.

## Why this is a separate repository

The **WTP** workflow needs many inputs that GloBI does not make: retrofit cost and incentive tables, energy prices, adoption curves, emissions-factor trajectories, demographic data for propensity models, and Monte Carlo settings. A separate repository, **[globi-use-cases](https://github.com/daryaguettler/globi-use-cases)**, holds these tools. This keeps the GloBI install small, and lets the analyses change on their own release cycle.

Other downstream use cases are in the same repository, with the analysis tools, sample inputs in `data/inputs/`, and the Streamlit apps.

## What you will find there

The [globi-use-cases](https://github.com/daryaguettler/globi-use-cases) repository has tools and a Streamlit app for:

1. **Energy and policy impacts:** compare baseline and retrofit scenario files (one pair for each year) for energy and peak differences.
2. **Propensity:** calculate the acceptance probability of each building (residential logit with census demographics; commercial NPV threshold).
3. **Uptake:** apply adoption curves from JSON, so that buildings adopt over time from propensity and curve targets.
4. **Emissions:** combine the adopted floor area and fuel mix with emissions-factor trajectories that you can edit.

In the main app, you upload results, set the configuration, select adoption curves, edit emissions, and run the full pipeline with charts and tables. The sample inputs in `data/inputs/` let you use the app without new GloBI runs.

For the full feature list, the scenario editor, Docker options, the data layout and the `split_scenarios.py` tool, see the [README](https://github.com/daryaguettler/globi-use-cases/blob/main/README.md) of that repository.

## Download the repository

Clone the repository with Git. Git lets you get updates later with `git pull`.

```bash
git clone https://github.com/daryaguettler/globi-use-cases.git
cd globi-use-cases
```

You can also download a ZIP file from the **Code** menu on GitHub. Extract it, then `cd` into the extracted folder.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker Desktop, to run the app in Docker with `make run`

## Set up the environment

To run the app on your computer (not in Docker), install the Python environment from the repository root:

```bash
uv sync
```

The Makefile sets `PYTHONPATH=src`, so that the `app` and `use_cases` imports work. Use the `make` targets below, or set `PYTHONPATH` yourself.

## Run the analysis app

To run the app in Docker and open it in your browser:

```bash
make run
```

To run the app on your computer without Docker:

```bash
make run-local
```

`make run-local` is the same as:

```bash
PYTHONPATH=src uv run streamlit run src/app/wtp_app.py
```

Open the URL that Streamlit prints. The default is [http://localhost:8502](http://localhost:8502), so the app can run at the same time as the GloBI results dashboard (port 8501).

The workflow in the app:

1. Upload pairs of baseline and scenario `EnergyAndPeak.pq` files.
2. Set the costs and options in the sidebar.
3. Select the adoption curves and emissions trajectories.
4. Run the pipeline and look at the results.

To edit adoption curves and emissions trajectories in a separate app, run `make editor`. To build and run the Docker image directly, run `make docker-build`, then `make docker-run`.
