FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV AUDIO_SEPARATOR_MODEL_DIR=/opt/models
ENV TORCH_HOME=/opt/models/torch
ENV HF_HOME=/opt/models/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    git-lfs \
    build-essential \
    && git lfs install \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /opt/models /opt/models/torch /opt/models/hf

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps basic-pitch>=0.3.2 && \
    pip install --no-cache-dir resampy scikit-learn mir_eval

# Pre-cache Beat This!, BS-Roformer-SW, TorchCREPE full, and YourMT3 weights into image
RUN python -c "from beat_this.inference import File2Beats; File2Beats(checkpoint_path='final0', device='cpu', dbn=False)"
RUN python -c "from audio_separator.separator import Separator; s = Separator(model_file_dir='/opt/models'); s.load_model(model_filename='BS-Roformer-SW.ckpt')"
RUN python -c "import torch, torchcrepe; x = torch.zeros(1, 16000); torchcrepe.predict(x, 16000, 160, 75, 1400, 'full', batch_size=64, device='cpu')"
RUN python -c "import io, numpy as np, pretty_midi; from mt3_infer import load_model; m = load_model('yourmt3', device='cpu'); res = m.transcribe(np.zeros(16000, dtype=np.float32), sr=16000); buf = io.BytesIO(); res.save(file=buf); buf.seek(0); pm = pretty_midi.PrettyMIDI(buf); print('YourMT3 + PrettyMIDI smoke test OK, tracks:', len(pm.instruments))"

COPY . ./cloud_worker

# End-to-end stereo pipeline smoke test verifying stem isolation, TorchCREPE stereo mono-mix, BasicPitch ONNX, and YourMT3
RUN python -c "import shutil, tempfile, numpy as np, soundfile as sf; from cloud_worker.pipeline import analyze_audio_pipeline; d=tempfile.mkdtemp(); t=np.linspace(0, 2.0, 88200); y=np.column_stack([0.3*np.sin(2*np.pi*392*t), 0.3*np.sin(2*np.pi*392*t)]).astype(np.float32); wav=f'{d}/cropped.wav'; sf.write(wav, y, 44100); res=analyze_audio_pipeline(wav, d); assert res['has_isolated_stem'] is True, f'Expected isolated stem, got {res[\"has_isolated_stem\"]}'; shutil.rmtree(d, ignore_errors=True); print('Full stereo pipeline smoke test OK! notes:', len(res['raw_notes']))"

EXPOSE 8080
CMD ["uvicorn", "cloud_worker.app:app", "--host", "0.0.0.0", "--port", "8080"]
