FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . pipeline/
RUN mkdir -p /app/data
CMD ["uvicorn", "pipeline.main:app", "--host", "0.0.0.0", "--port", "8001"]
