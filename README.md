# IBMA WireWalker Processor

Processes IBMA WireWalker NetCDF files into EMSO/CF-compliant raw (trajectory)
and processed (timeSeriesProfile, depth-binned) datasets, and serves both
through a local ERDDAP instance.

See `AGENTS.md` for the processing/averaging rules this script follows.

## Prerequisites

- Python 3.10+
- Docker + the `docker compose` plugin (for the ERDDAP container)

## 1. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start a fresh ERDDAP container

This resets `erddap/conf/datasets.xml` to the default (no datasets configured)
and (re)starts the container.

```bash
cd erddap
./setup.sh
cd ..
```

ERDDAP will be reachable at http://localhost:8080/erddap/ once it finishes
starting up (first boot can take a minute or two).

## 3. Process the example dataset

`examples/15day1clean_sample.nc` is a 2-day subset of the full WireWalker
deployment (`examples/15day1clean.nc`, 15 days, ~320MB), kept under 100MB so
it can be committed to the repo.

```bash
python3 wirewalker_processor.py examples/15day1clean_sample.nc dataset_raw.nc dataset_processed.nc
```

This creates `dataset_raw.nc` (trajectory) and `dataset_processed.nc`
(timeSeriesProfile, 1m depth bins by default — use `--depth-bin` to change it).

## 4. Copy the datasets into ERDDAP's data folders

```bash
cp dataset_raw.nc erddap/datasets/raw/
cp dataset_processed.nc erddap/datasets/processed/
```

## 5. Configure the two datasets in ERDDAP

`erddap_setup.py` wraps `emso_metadata_harmonizer.erddap_config()`: it reads
the NetCDF file's EMSO-compliant metadata and appends the matching dataset
entry to `erddap/conf/datasets.xml`. The third argument is the path ERDDAP
sees *inside the container* (see the `./datasets:/datasets:ro` mount in
`erddap/docker-compose.yaml`), not the host path used in step 4.

```bash
python3 erddap_setup.py erddap/datasets/raw/dataset_raw.nc ibma_wirewalker_raw /datasets/raw
python3 erddap_setup.py erddap/datasets/processed/dataset_processed.nc ibma_wirewalker_processed /datasets/processed
```

## 6. Reload ERDDAP

```bash
cd erddap
docker compose restart
cd ..
```

Browse the two datasets at:

- http://localhost:8080/erddap/tabledap/ibma_wirewalker_raw.html
- http://localhost:8080/erddap/tabledap/ibma_wirewalker_processed.html
