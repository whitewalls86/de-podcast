from fastapi import FastAPI, HTTPException

from pipeline.pipeline import run_pipeline

app = FastAPI()


@app.post("/pipeline/run")
async def pipeline_run():
    result = await run_pipeline()
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
