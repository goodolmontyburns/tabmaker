import os
import ssl
import json
import re
import base64
from typing import List, Dict, Any, Optional
import certifi
import httpx

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()
os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = certifi.where()
os.environ.pop("SSL_CERT_DIR", None)
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
httpx._config.DEFAULT_CA_BUNDLE_PATH = certifi.where()

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

import subprocess

class GeminiClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        self.api_key = re.sub(r"[\s\'\"]", "", str(self.api_key)).strip()
        self.project_id = os.environ.get("GCP_PROJECT") or "vinovault-492104"
        self.location = "us-central1"
        self.model_name = "gemini-2.5-flash"

    def get_auth_token(self) -> str:
        try:
            return subprocess.check_output(["gcloud", "auth", "print-access-token"], stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return ""

    def has_valid_key(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5) or bool(self.get_auth_token())

    def set_api_key(self, key: str):
        self.api_key = re.sub(r"[\s\'\"]", "", str(key)).strip()

    def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        image_bytes_list: Optional[List[bytes]] = None,
        audio_bytes: Optional[bytes] = None,
        audio_mime: str = "audio/wav",
        model: Optional[str] = None,
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """Calls Gemini API via Google AI Studio or Vertex AI with text prompt, optional audio waveform, and image frames."""
        target_model = model or self.model_name
        model_candidates = [target_model, "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.7-flash", "gemini-1.5-flash"]
        seen = set()
        model_candidates = [c for c in model_candidates if not (c in seen or seen.add(c))]

        # Build parts list
        parts: List[Dict[str, Any]] = []
        if audio_bytes:
            b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
            parts.append({
                "inlineData": {
                    "mimeType": audio_mime,
                    "data": b64_audio
                }
            })

        if image_bytes_list:
            for img_b in image_bytes_list:
                b64_str = base64.b64encode(img_b).decode('utf-8')
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": b64_str
                    }
                })

        parts.append({"text": prompt})
        contents = [{
            "role": "user",
            "parts": parts
        }]

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json"
            }
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        last_error = ""

        # 1. Try Google AI Studio if API key provided
        if self.api_key and len(self.api_key) > 5:
            for m in model_candidates:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
                    with httpx.Client(verify=False, timeout=120.0) as client:
                        resp = client.post(url, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            candidates_out = data.get("candidates", [])
                            if candidates_out:
                                text_parts = candidates_out[0].get("content", {}).get("parts", [])
                                raw_text = "".join([p.get("text", "") for p in text_parts])
                                return {
                                    "success": True,
                                    "raw_text": raw_text,
                                    "model_used": m
                                }
                except Exception as e:
                    last_error = str(e)
                    continue

        # 2. Try Google Cloud Vertex AI using gcloud ADC OAuth Token
        print("[GEMINI DEBUG] Fetching auth token...")
        token = self.get_auth_token()
        print(f"[GEMINI DEBUG] Token obtained: {bool(token)}")
        if token:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            vertex_candidates = [target_model, "gemini-2.5-flash", "gemini-2.5-pro"]
            seen_v = set()
            vertex_candidates = [c for c in vertex_candidates if not (c in seen_v or seen_v.add(c))]
            for m in vertex_candidates:
                try:
                    url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{m}:generateContent"
                    print(f"[GEMINI DEBUG] Calling Vertex AI model {m} (timeout=180s)...")
                    with httpx.Client(verify=False, timeout=180.0) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        print(f"[GEMINI DEBUG] Model {m} response status: {resp.status_code}")
                        if resp.status_code == 200:
                            data = resp.json()
                            candidates_out = data.get("candidates", [])
                            if candidates_out:
                                text_parts = candidates_out[0].get("content", {}).get("parts", [])
                                raw_text = "".join([p.get("text", "") for p in text_parts])
                                return {
                                    "success": True,
                                    "raw_text": raw_text,
                                    "model_used": m
                                }
                        else:
                            last_error = f"{resp.status_code}: {resp.text}"
                            print(f"[GEMINI DEBUG] Error response: {last_error[:200]}")
                except Exception as e:
                    last_error = str(e)
                    print(f"[GEMINI DEBUG] Exception for {m}: {last_error}")
                    continue

        return {
            "success": False,
            "error": f"Gemini API request failed: {last_error or 'No valid credentials found'}",
            "raw_text": ""
        }
