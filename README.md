# NYS EV Adoption & Infrastructure Analysis

Data collection and analytical pipeline analyzing regional electric vehicle uptake against public charging infrastructure across all 62 New York State counties.

## Project Structure

```text
├── data/
│   ├── raw/                  # Immutable raw API JSON payloads and Census boundaries (hidden)
│   └── curated/
│       ├── parquet/          # Curated columnar Parquet tables
│       └── duckdb/           # Relational DuckDB database (ev_infrastructure.duckdb)
├── metadata/                 # Frictionless Data Package catalog, schemas, and SHA-256 digests
├── scripts/
│   ├── ingest/               # Raw API extraction and integrity verification scripts
│   ├── transform/            # Spatial processing and curated build pipeline
│   └── analysis/             # Programmatic figures and summary statistics generation
└── reports/                  # Generated figures and analytical output tables
```

## Setup & Environment

Create and activate an isolated Conda environment, then install required dependencies:

```bash
conda env create -f environment.yml
conda activate nys-ev-analysis
```

## Querying Collected Data

The repository already tracks the curated and validated DuckDB database at `data/curated/duckdb/ev_infrastructure.duckdb`. In order to query the verified tables or run the analysis scripts, no API keys or ingestion runs are required.

Query the county view directly in Python (such as follows):

```python
import duckdb

con = duckdb.connect("data/curated/duckdb/ev_infrastructure.duckdb", read_only=True)

print(con.execute("SELECT * FROM county_infrastructure_summary LIMIT 10;").df())
con.close()
```

To re-generate the figures and summary tables from the curated layer:

```bash
python scripts/analysis/descriptive_analysis.py
```

## Full Pipeline Replication (From Raw APIs)

Follow these steps only if the intent is to re-fetch raw data from the upstream API endpoints and rebuild the curated datasets from scratch.

### 1. Configure API Credentials

The NLR/AFDC ingestion script requires an API key obtained from [developer.nlr.gov](https://developer.nlr.gov/). Create a `.env` file in the root repository directory:

```bash
echo "NLR_API_KEY=_actual_api_key_" > .env
```

`.env` is listed in `.gitignore` to prevent credential exposure.

### 2. Execute Ingestion & Transformation

```bash
# Ingest raw payloads (cached locally with transactional checksum verification)
python scripts/ingest/ingest_nlr.py
python scripts/ingest/ingest_nyserda.py
python scripts/ingest/ingest_boundaries.py

# Transform and compile into Parquet/DuckDB (use --force to bypass curated lock)
python scripts/transform/transform_pipeline.py --force

# Run descriptive analysis
python scripts/analysis/descriptive_analysis.py
```