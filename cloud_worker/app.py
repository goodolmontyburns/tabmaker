import os
import shutil
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from cloud_worker.pipeline import warmup_models, analyze_audio_pipeline

app = FastAPI(title="TabMaker Cloud GPU Worker")


@app.get("/health")
def health():
    import torch
    return {
        "status": "ok",
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    solo_mode: bool = Form(True),
    target_fret: int = Form(8),
    transcriber: str = Form("hybrid"),
):
    work_dir = tempfile.mkdtemp(prefix="tabmaker_gpu_")
    try:
        in_wav = os.path.join(work_dir, "cropped.wav")
        with open(in_wav, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return analyze_audio_pipeline(
            in_wav,
            work_dir=work_dir,
            solo_mode=solo_mode,
            transcriber=transcriber,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPU analysis failed: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn
    warmup_models()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
