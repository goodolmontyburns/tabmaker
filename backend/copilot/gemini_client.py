import os
import json
import base64
import subprocess
from typing import List, Dict, Any, Optional
import certifi
import httpx

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


def _load_dotenv_if_present() -> None:
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv_if_present()


class GeminiClient:
    """
    Unified Gemini 4 client supporting:
    1. Google AI Studio / Gemini Developer API (`GEMINI_API_KEY`, uses prepaid Gemini API credits)
    2. Vertex AI `locations/global` via ADC / gcloud OAuth token
    """

    DEFAULT_FAST_MODEL = "gemini-4-argon"
    DEFAULT_PRO_MODEL = "gemini-4-carbon"

    def __init__(self, api_key: Optional[str] = None, project_id: Optional[str] = None):
        raw_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        self.api_key = "".join(str(raw_key).split()).strip("\"'")
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT") or "tabmaker-studio-2026"
        self.location = os.environ.get("VERTEX_LOCATION", "global")
        self.model_name = self.DEFAULT_FAST_MODEL

    def get_auth_token(self) -> str:
        # 1. Try google-auth ADC first
        try:
            import google.auth
            import google.auth.transport.requests
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(google.auth.transport.requests.Request())
            if creds.token:
                return creds.token
        except Exception:
            pass

        # 2. Fallback to gcloud CLI access token
        try:
            env = os.environ.copy()
            env["CLOUDSDK_METRICS_ENVIRONMENT"] = (
                f"{env.get('CLOUDSDK_METRICS_ENVIRONMENT', '')} datacloud.antigravity".strip()
            )
            return subprocess.check_output(
                ["gcloud", "auth", "print-access-token"],
                stderr=subprocess.DEVNULL,
                env=env,
                timeout=8,
            ).decode().strip()
        except Exception:
            return ""

    def has_valid_key(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5) or bool(self.get_auth_token())

    def set_api_key(self, key: str) -> None:
        self.api_key = "".join(str(key).split()).strip("\"'")

    def _build_candidates(self, model: Optional[str]) -> List[str]:
        target = model or self.model_name
        if target in ("gemini-4-carbon", "gemini-2.5-pro"):
            pool = [target, "gemini-4-carbon", "gemini-4-argon", "gemini-3.8-flash", "gemini-2.5-pro"]
        else:
            pool = [target, "gemini-4-argon", "gemini-4-hydrogen", "gemini-3.8-flash", "gemini-2.5-flash"]
        seen = set()
        return [m for m in pool if not (m in seen or seen.add(m))]

    def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        image_bytes_list: Optional[List[bytes]] = None,
        audio_bytes: Optional[bytes] = None,
        audio_mime: str = "audio/wav",
        model: Optional[str] = None,
        temperature: float = 0.0,
        response_mime_type: str = "application/json",
    ) -> Dict[str, Any]:
        model_candidates = self._build_candidates(model)

        parts: List[Dict[str, Any]] = []
        if audio_bytes:
            parts.append({
                "inlineData": {
                    "mimeType": audio_mime,
                    "data": base64.b64encode(audio_bytes).decode("utf-8"),
                }
            })

        if image_bytes_list:
            for img_b in image_bytes_list:
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": base64.b64encode(img_b).decode("utf-8"),
                    }
                })

        parts.append({"text": prompt})
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": response_mime_type,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        last_error = ""
        ca_bundle = certifi.where()

        # 1. Google AI Studio / Gemini API Key (draws from prepaid Gemini API credits)
        if self.api_key and len(self.api_key) > 5:
            for m in model_candidates:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
                    headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
                    with httpx.Client(verify=ca_bundle, timeout=150.0) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            cands = data.get("candidates", [])
                            if cands:
                                text_parts = cands[0].get("content", {}).get("parts", [])
                                raw_text = "".join(p.get("text", "") for p in text_parts)
                                return {"success": True, "raw_text": raw_text, "model_used": m, "provider": "gemini_api"}
                        last_error = f"AI Studio {m} -> {resp.status_code}: {resp.text[:240]}"
                except Exception as e:
                    last_error = str(e)
                    continue

        # 2. Vertex AI locations/global using ADC / gcloud token
        token = self.get_auth_token()
        if token and self.project_id:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            for m in model_candidates:
                for loc in (self.location, "global"):
                    try:
                        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
                        url = (
                            f"https://{host}/v1/projects/{self.project_id}/locations/{loc}"
                            f"/publishers/google/models/{m}:generateContent"
                        )
                        with httpx.Client(verify=ca_bundle, timeout=180.0) as client:
                            resp = client.post(url, headers=headers, json=payload)
                            if resp.status_code == 200:
                                data = resp.json()
                                cands = data.get("candidates", [])
                                if cands:
                                    text_parts = cands[0].get("content", {}).get("parts", [])
                                    raw_text = "".join(p.get("text", "") for p in text_parts)
                                    return {
                                        "success": True,
                                        "raw_text": raw_text,
                                        "model_used": m,
                                        "provider": f"vertex_{loc}",
                                    }
                            last_error = f"Vertex {loc}/{m} -> {resp.status_code}: {resp.text[:240]}"
                    except Exception as e:
                        last_error = str(e)
                    if loc == "global":
                        break

        return {
            "success": False,
            "error": f"Gemini API request failed: {last_error or 'No valid credentials found'}",
            "raw_text": "",
        }
