"""Provider-agnostic LLM client using only FREE options:
  gemini  – Google AI Studio free tier  (GEMINI_API_KEY)
  groq    – Groq free tier              (GROQ_API_KEY)
  openai  – any OpenAI-compatible endpoint, e.g. OpenRouter ':free' models (OPENAI_API_KEY + OPENAI_BASE_URL)
  ollama  – fully local, no key         (OLLAMA_HOST, default http://localhost:11434)
  none    – heuristic mode (no AI)
Choose with LLM_PROVIDER=auto|gemini|groq|openai|ollama|none."""
import json
import re

import requests

from .config import env

TIMEOUT = 60


class LLMError(Exception):
    pass


def provider():
    p = env("LLM_PROVIDER", "auto").lower()
    if p != "auto":
        return p
    if env("GEMINI_API_KEY"):
        return "gemini"
    if env("GROQ_API_KEY"):
        return "groq"
    if env("OPENAI_API_KEY") and env("OPENAI_BASE_URL"):
        return "openai"
    if env("OLLAMA_HOST") or env("OLLAMA_MODEL"):
        return "ollama"
    return "none"


def available():
    return provider() not in ("none", "")


def model_name():
    p = provider()
    return {
        "gemini": env("GEMINI_MODEL", "gemini-2.0-flash"),
        "groq": env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "openai": env("OPENAI_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "ollama": env("OLLAMA_MODEL", "llama3.2"),
    }.get(p, "")


def label():
    return f"{provider()}:{model_name()}" if available() else "none"


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception as e:
            raise LLMError(f"Model returned invalid JSON: {e}")
    raise LLMError("Model did not return JSON")


def complete_json(system, user, temperature=0.8):
    p = provider()
    try:
        if p == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name()}:generateContent"
            r = requests.post(url, headers={"x-goog-api-key": env("GEMINI_API_KEY")}, timeout=TIMEOUT, json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
            })
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        elif p in ("groq", "openai"):
            if p == "groq":
                base, key = "https://api.groq.com/openai/v1", env("GROQ_API_KEY")
            else:
                base, key = env("OPENAI_BASE_URL").rstrip("/"), env("OPENAI_API_KEY")
            r = requests.post(base + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
                              timeout=TIMEOUT, json={
                                  "model": model_name(), "temperature": temperature,
                                  "response_format": {"type": "json_object"},
                                  "messages": [{"role": "system", "content": system},
                                               {"role": "user", "content": user}]})
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"]
        elif p == "ollama":
            host = env("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
            r = requests.post(host + "/api/chat", timeout=300, json={
                "model": model_name(), "stream": False, "format": "json",
                "options": {"temperature": temperature},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            txt = r.json()["message"]["content"]
        else:
            raise LLMError("No LLM provider configured")
    except requests.RequestException as e:
        detail = ""
        if getattr(e, "response", None) is not None:
            detail = e.response.text[:200]
        raise LLMError(f"{p} request failed: {e} {detail}")
    return _extract_json(txt)
