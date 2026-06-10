from fastapi import FastAPI

from pipeline.pipeline import run_pipeline

app = FastAPI()


@app.post("/pipeline/run")
async def pipeline_run():
    return await run_pipeline()


@app.get("/health")
async def health():
    return {"status": "ok"}
