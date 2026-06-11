FROM python:3.11-slim
WORKDIR /app

# System packages for NotebookLM browser automation + noVNC re-auth flow.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc novnc websockify \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "notebooklm-py[browser]" httpx
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . pipeline/
RUN mkdir -p /app/data /app/episodes
CMD ["uvicorn", "pipeline.main:app", "--host", "0.0.0.0", "--port", "8001"]
