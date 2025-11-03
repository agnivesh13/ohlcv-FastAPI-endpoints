# ohlcv-FastAPI-endpoints

> FastAPI microservice for exposing OHLCV (Open/High/Low/Close/Volume) data stored in S3 and related utilities (presigned URLs, partitioned listing, simple transformations).

---

## Project overview

This repository contains a small, production-minded FastAPI app that provides HTTP endpoints to read, list, and upload OHLCV datasets stored on Amazon S3. It is intended as a building block for data pipelines, backtests, dashboards, or any service that needs programmatic access to partitioned OHLCV time-series data.

Typical use-cases:

* Retrieve Parquet/CSV OHLCV files by partition (year/month/day/timeframe).
* Generate presigned S3 URLs for direct upload/download.
* List available symbols and partitions.
* Serve lightweight time-window queries by streaming or returning aggregated frames.

> **Note:** The repo targets a modular design so you can swap out the storage backend (S3) or extend parsing logic (e.g., adjust for corporate actions) easily.

---

## Features

* FastAPI endpoints for common OHLCV operations
* S3 integration (boto3) with configurable bucket/prefix
* Presigned URL generation for secure direct S3 uploads/downloads
* Partitioned listing helpers (year/month/day/timeframe/symbol)
* Example request/response shapes and cURL snippets
* Ready for running locally via `uvicorn` or containerized with Docker

---

## Getting started

### Prerequisites

* Python 3.10+ (recommended)
* pip
* AWS credentials (access key & secret) configured via environment variables or AWS config files
* (Optional) Docker

### Clone

```bash
git clone https://github.com/agnivesh13/ohlcv-FastAPI-endpoints.git
cd ohlcv-FastAPI-endpoints
```

### Virtual environment & install

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.\.venv\Scripts\activate     # Windows (PowerShell)

pip install --upgrade pip
pip install -r requirements.txt
```

If `requirements.txt` is not present, typical packages are:

```
fastapi
uvicorn[standard]
boto3
pydantic
pandas
pyarrow
python-multipart    # if supporting file uploads
```

---

## Configuration

The app reads configuration from environment variables. Example `.env` (do **not** commit secrets):

```
# AWS
AWS_ACCESS_KEY_ID=YOUR_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET
AWS_REGION=ap-south-1
S3_BUCKET=ohlcv-pipeline
S3_BASE_PREFIX=ohlcv/processed

# FastAPI
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=info

# Optional
DEFAULT_TIMEFRAME=5m
```

> For local development you can use `python-dotenv` to load `.env` into the environment.

---

## Running locally

Start the FastAPI app with Uvicorn:

```bash
uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8000} --reload
```

Visit the interactive docs at `http://localhost:8000/docs` (Swagger UI) or the OpenAPI JSON at `http://localhost:8000/openapi.json`.

---

## API endpoints (examples)

> **These are example endpoint shapes** — match them to the implementation in `app/`.

### Health check

`GET /health`

Response:

```json
{ "status": "ok" }
```

### List symbols

`GET /symbols`

Query params (optional): `prefix`, `limit`

Response: `[{"symbol":"NSE_CIPLA-EQ"}, ...]`

### List partitions for a symbol

`GET /symbols/{symbol}/partitions`

Response:

```json
{
  "symbol": "NSE_CIPLA-EQ",
  "partitions": [
    {"year":2025, "month":11, "day":3, "timeframe":"15m", "s3_path":"s3://..."},
    ...
  ]
}
```

### Get a file or object metadata

`GET /object?path=s3://ohlcv-pipeline/processed/timeframe=15m/exchange=NSE/symbol=NSE_CIPLA-EQ/year=2025/month=11/day=03/part-00021-899d3b8a`

Returns presigned download URL or streams the object directly depending on query flags (`stream=true`).

### Generate presigned upload URL

`POST /presign/upload`

Body:

```json
{ "key":"processed/timeframe=15m/.../part-00000.parquet", "expires_in":3600 }
```

Response:

```json
{ "url": "https://s3...", "fields": {...} }
```

### Upload file (multipart)

`POST /upload` — accepts multipart form `file` and destination `key`.

---

## S3 path conventions (example)

This project assumes a partitioned S3 layout to simplify range queries and partitions discovery. Example layout:

```
s3://ohlcv-pipeline/processed/
  timeframe=5m/
    exchange=NSE/
      symbol=NSE_CIPLA-EQ/
        year=2025/month=11/day=03/part-00021-899d3b8a.parquet
```

Or alternatively (flat prefix style):

```
s3://ohlcv-pipeline/processed/timeframe=15m/exchange=NSE/symbol=NSE_CIPLA-EQ/year=2025/month=11/day=03/part-00021-899d3b8a
```

Adjust `S3_BASE_PREFIX` and path parsing logic in the code to match whichever convention you use.

---

## Docker

A simple `Dockerfile` (example):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t ohlcv-fastapi .
docker run -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... -p 8000:8000 ohlcv-fastapi
```

---

## Deployment suggestions

* **AWS ECS / Fargate** — containerize and run with a load balancer; attach task role with least-privilege permissions to read/write your S3 bucket.
* **AWS Elastic Beanstalk** — quick deploy from Docker or Python platform.
* **AWS Lambda + API Gateway** — possible for lightweight endpoints (use Lambda URLs or a single Lambda with API Gateway). Watch cold-starts and memory limits if reading large Parquet files.
* **EKS / Kubernetes** — for large-scale production systems with autoscaling requirements.

**IAM tip:** prefer using IAM roles for ECS tasks or EC2 instance profiles instead of long-lived access keys.

---

## Testing

* Unit-test S3 interactions using `moto` to mock S3 in CI.
* Add integration tests that run against a dedicated dev bucket with smaller datasets.

Example with pytest + moto:

```python
from moto import mock_s3
import boto3

@mock_s3
def test_presign():
    s3 = boto3.client('s3', region_name='ap-south-1')
    s3.create_bucket(Bucket='test-bucket')
    # ... test endpoint
```

---

## .gitignore suggestion

```
.env
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
*.sqlite3
*.log
.DS_Store
.idea/
.vscode/
*.pem
```

---

## Contributing

Contributions are welcome. Typical workflow:

1. Fork the repository
2. Create a feature branch
3. Add tests and documentation
4. Open a PR

---

## Roadmap / Ideas

* Endpoint to return merged OHLCV windows between time ranges (server-side aggregation)
* Precompute and store popular ticker-timeframe aggregates (e.g., hourly/daily) into a separate prefix
* Integration with a message queue (SNS/SQS/Kafka) to notify downstream services after successful file ingestion
* Websocket or SSE endpoint to stream live ticks

---

## License

Add a license file (e.g., MIT) if you want this repo to be open-source.

---

If you'd like, I can:

* create a `README.md` file in the repository (this file)
* add `requirements.txt` and a starter `Dockerfile`
* scaffold example endpoints in `app/main.py` and `app/s3_client.py`

Tell me which of the above you'd like me to add next.
