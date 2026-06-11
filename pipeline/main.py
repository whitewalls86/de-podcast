from pathlib import Path

from fastapi import FastAPI, HTTPException

from pipeline.admin import router as admin_router
from pipeline.pipeline import run_pipeline

app = FastAPI()
app.state.sources_path = Path("sources.json")
app.state.last_run_path = Path("data/last_run.json")

app.include_router(admin_router)


@app.post("/pipeline/run")
async def pipeline_run():
    result = await run_pipeline()
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
