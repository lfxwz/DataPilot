# DataPilot

DataPilot is an auditable data-analysis workbench that turns natural-language questions into
SQL, deterministic or isolated Python analysis, charts, and evidence-backed reports.

> Project status: development preview. The current development layout runs the frontend,
> PostgreSQL, and the shared Python analysis runtime in Docker. FastAPI runs on the host for
> convenient debugging and hot reload.

## Current architecture

```text
Browser http://127.0.0.1:5173
  -> web container
  -> FastAPI on Windows http://127.0.0.1:8000
       -> PostgreSQL container
       -> persistent Python runtime container
```

The Python runtime includes NumPy, pandas, SciPy, scikit-learn, statsmodels, Plotly,
Matplotlib, Seaborn, Polars, PyArrow, XGBoost, LightGBM, CPU-only PyTorch, OpenPyXL,
SymPy, and NetworkX. Each generated analysis runs in a fresh Python process inside the
persistent container.

## Requirements

- Windows 10/11 with PowerShell
- Docker Desktop with Linux containers
- Python 3.11 or 3.12; Conda is recommended for development
- An OpenAI-compatible model API key
- Optional: Kaggle credentials for the full Olist public dataset

## First-time setup

Create the local Python environment:

```powershell
conda create -n datapilot python=3.11 -y
conda activate datapilot
Set-Location path\to\DataPilot
python -m pip install -e ".[dev,postgres,data]"
Copy-Item .env.example .env
```

Edit `.env` and provide the model settings. The simplest local configuration is:

```env
DATAPILOT_LLM_BASE_URL=https://api.deepseek.com
DATAPILOT_LLM_API_KEY=replace-with-your-key
DATAPILOT_LLM_MODEL=deepseek-v4-flash
```

Never commit `.env` or any credential file. DataPilot also supports loading a literal key from
an external file through `DATAPILOT_LLM_CREDENTIALS_FILE`.

## Start with prebuilt Docker images

The development-preview images are published on Docker Hub:

- `docker.io/luyukang/datapilot-web:dev`
- `docker.io/luyukang/datapilot-postgres:dev`
- `docker.io/luyukang/datapilot-python-runtime:dev`

Pull and start them without building locally:

```powershell
Set-Location path\to\DataPilot
.\start.ps1
```

On the first run, the script creates `.venv`, installs the host-side backend, pulls the three
published images, starts the containers, and runs FastAPI in the foreground. If `.env` does not
exist, the script creates it and asks you to add your model API settings before continuing.
It also verifies that the selected Python interpreter is version 3.11 or 3.12.

The current release layout still runs FastAPI on the host. Keep the PowerShell window open while
using DataPilot. The equivalent manual backend command is:

```powershell
conda activate datapilot
Set-Location path\to\DataPilot
python -m uvicorn datapilot.main:app --reload
```

Open the workbench at <http://127.0.0.1:5173>.

Stop the release containers with:

```powershell
.\stop.ps1
```

Use `.\start.ps1 -SkipPull` when the required images are already present and you do not want to
check Docker Hub for updates.

After placing all nine Olist CSV files under `data/raw/olist`, initialize or refresh the demo
dataset with:

```powershell
.\start.ps1 -SkipPull -LoadOlist
```

`-LoadOlist` truncates and reloads the Olist tables in one transaction. Omit it during ordinary
startup so existing data is left unchanged.

## Start from source for development

Start Docker Desktop, then run:

```powershell
Set-Location path\to\DataPilot
docker compose up -d
```

The source-based Compose project starts exactly three services:

- `web`: production frontend at `http://127.0.0.1:5173`
- `postgres`: local PostgreSQL at `127.0.0.1:5432`
- `python-runtime`: shared isolated analysis environment

Start the backend in a second PowerShell window:

```powershell
conda activate datapilot
Set-Location path\to\DataPilot
python -m uvicorn datapilot.main:app --reload
```

Open:

- Workbench: <http://127.0.0.1:5173>
- API documentation: <http://127.0.0.1:8000/docs>

The frontend is already built into its container. Do not run `npm install` or `npm run dev`
for normal use.

## Stop the project

Press `Ctrl+C` in the backend window, then run:

```powershell
Set-Location path\to\DataPilot
docker compose stop
```

The PostgreSQL volume is retained. `docker compose down -v` deletes the local database and
should only be used when the data is disposable.

## Frontend development

Frontend source remains under `web/`. After a source change, rebuild only the frontend:

```powershell
Set-Location path\to\DataPilot
docker compose up -d --build web
```

Then refresh <http://127.0.0.1:5173>. Docker reuses the npm dependency layer while
`package.json` and `package-lock.json` remain unchanged.

## Olist public dataset

Raw Olist files are excluded from Git and remain governed by their original
CC BY-NC-SA 4.0 dataset terms. Download and load them with:

```powershell
conda activate datapilot
Set-Location path\to\DataPilot
python scripts\download_olist.py
docker compose --profile data run --rm olist-loader
```

The loader validates all expected CSV headers and imports the tables in one transaction.

## Run an analysis

Use the workbench, Swagger, or the command-line client:

```powershell
conda activate datapilot
Set-Location path\to\DataPilot
python scripts\run_agent.py "统计不同订单状态的订单数量，并说明主要发现"
```

The main endpoint is:

```text
POST /api/v1/agent/analyze
```

Run history and reports are available at:

```text
GET /api/v1/agent/runs
GET /api/v1/agent/runs/{run_id}
GET /api/v1/agent/runs/{run_id}/report
```

## Security boundary

- Model credentials are resolved only by the backend and are never passed to generated code.
- PostgreSQL uses separate owner, read-only query, and metadata roles.
- Generated Python receives bounded query records rather than database credentials.
- The analysis container has no network, a read-only root filesystem, dropped capabilities,
  and CPU, memory, and process limits.
- Development policy switches must not be treated as production authorization controls.

See [SECURITY.md](SECURITY.md) for the full boundary and reporting policy.

## Quality checks

Backend:

```powershell
python -m ruff check . --no-cache
python -m ruff format --check . --no-cache
python -m mypy
python -m pytest -q -p no:langsmith_plugin
```

Frontend checks run in a clean Node environment or during the image build:

```powershell
Set-Location path\to\DataPilot\web
npm ci
npm run lint
npm test
```

Compose validation:

```powershell
Set-Location path\to\DataPilot
docker compose config --quiet
```

## Contact

For questions or feedback, contact [yukang.lu@outlook.com](mailto:yukang.lu@outlook.com).

## License

DataPilot source code is licensed under the [Apache License 2.0](LICENSE). The Olist dataset
is excluded from this license and is not distributed in this repository.
