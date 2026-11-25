import os
import base64
import subprocess
from typing import Dict, Any, Optional, Tuple
import certifi
import httpx


def _get_identity_token(audience: str) -> str:
    """Fetches Google Cloud Run OIDC ID token using google-auth or gcloud CLI."""
    # 1. google-auth (service account / metadata server / authorized_user if supported)
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        auth_req = google.auth.transport.requests.Request()
        tok = google.oauth2.id_token.fetch_id_token(auth_req, audience)
        if tok:
            return tok
    except Exception:
        pass

    # 2. Local developer gcloud user credentials
    try:
        env = os.environ.copy()
        env["CLOUDSDK_METRICS_ENVIRONMENT"] = (
            f"{env.get('CLOUDSDK_METRICS_ENVIRONMENT', '')} datacloud.antigravity".strip()
        )
        tok = subprocess.check_output(
            ["gcloud", "auth", "print-identity-token"],
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=10,
        ).decode().strip()
        if tok:
            return tok
    except Exception:
        pass
    return ""


def call_cloud_gpu_worker(
    audio_path: str,
    worker_url: str,
    target_fret: Optional[int] = None,
    solo_mode: bool = True,
    transcriber: Optional[str] = None,
    timeout: float = 300.0,
) -> Tuple[Dict[str, Any], Optional[bytes], Optional[bytes]]:
    """
    Sends cropped audio to the stateless Cloud Run NVIDIA L4 GPU worker (/analyze).
    Returns (analysis_json, guitar_stem_wav_bytes, backing_stem_wav_bytes).
    """
    base_url = worker_url.rstrip("/")
    endpoint = f"{base_url}/analyze"

    headers: Dict[str, str] = {}
    token = _get_identity_token(base_url)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    chosen_transcriber = transcriber or os.environ.get("CLOUD_TRANSCRIBER", "hybrid")
    data = {
        "solo_mode": "true" if solo_mode else "false",
        "transcriber": chosen_transcriber,
    }
    if target_fret is not None:
        data["target_fret"] = str(int(target_fret))

    with open(audio_path, "rb") as f:
        files = {"file": ("cropped.wav", f, "audio/wav")}
        with httpx.Client(verify=certifi.where(), timeout=timeout) as client:
            resp = client.post(endpoint, headers=headers, data=data, files=files)
            resp.raise_for_status()
            payload = resp.json()

    guitar_bytes = (
        base64.b64decode(payload["guitar_stem_b64"]) if payload.get("guitar_stem_b64") else None
    )
    backing_bytes = (
        base64.b64decode(payload["backing_stem_b64"]) if payload.get("backing_stem_b64") else None
    )
    return payload, guitar_bytes, backing_bytes
