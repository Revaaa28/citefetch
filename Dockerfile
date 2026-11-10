FROM python:3.12-slim

WORKDIR /app

# Dependencies first for layer caching. The agent also has a stdlib (urllib)
# fallback, so it still runs if `requests` is unavailable at runtime.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY run.py cli.py ./
COPY data ./data

# Batch contract: reads /app/data/inputs/queries.json, writes JSONL to stdout.
ENTRYPOINT ["python3", "/app/run.py"]
