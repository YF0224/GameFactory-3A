"""Explicit, reproducible judge selection; never stores credentials."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
import struct
import zlib
from collections.abc import MutableMapping
from typing import Any
from urllib.parse import urlparse

PROFILE_NAME = "dashscope-whitebox"
PROFILE_ID = "dashscope-whitebox-2026-10-18-v2"
AUDIO_MODEL = "qwen3.8-omni-flash"  # Documented alias; not a pinned snapshot.
# Official model list checked 2026-10-18. No moving alias or silent fallback.
PINNED_MODEL = "qwen3.7-plus-2026-05-26"
FROZEN_ENV = {
    "A3GAME_VLM_MODEL": PINNED_MODEL,
    "A3GAME_VLM_TEMPERATURE": "0",
    "A3GAME_VLM_MAX_TOKENS": "8192",
    "A3GAME_VLM_TIMEOUT_S": "180",
    "A3GAME_VLM_ENABLE_THINKING": "false",
    "A3GAME_AUDIO_JUDGE_MODEL": AUDIO_MODEL,
    "A3GAME_AUDIO_JUDGE_TEMPERATURE": "0",
    "A3GAME_AUDIO_JUDGE_MAX_TOKENS": "4096",
    "A3GAME_AUDIO_JUDGE_TIMEOUT_S": "180",
}


def load_dashscope_key_file(path: Path, env: MutableMapping[str, str] | None = None) -> bool:
    """Read a plain key or DASHSCOPE_API_KEY=key without evaluating file text.

    Existing explicit keys win. Never include file contents in an exception.
    """
    env = os.environ if env is None else env
    if env.get("DASHSCOPE_API_KEY") or env.get("A3GAME_VLM_API_KEY"):
        return False
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8-sig").strip()
    match = re.fullmatch(r"(?:DASHSCOPE_API_KEY\s*=\s*)?[\"']?(sk-[A-Za-z0-9_.-]+)[\"']?", text)
    if not match:
        raise ValueError("DashScope key file must contain exactly one key; contents withheld")
    env["DASHSCOPE_API_KEY"] = match.group(1)
    return True


def configure_dashscope_whitebox(
    env: MutableMapping[str, str] | None = None,
    *, require_ready: bool = True,
) -> dict[str, Any]:
    """Apply a pinned profile, rejecting conflicting settings before mutation.

    Endpoint is explicit: key/workspace/region must agree. An existing lane
    endpoint wins over DASHSCOPE_BASE_URL. Nothing loads or prints .env files.
    """
    env = os.environ if env is None else env
    for key, value in FROZEN_ENV.items():
        if env.get(key) and env[key] != value:
            raise ValueError(f"{key} conflicts with {PROFILE_ID}; unset it or "
                             "run without --judge-profile")
    endpoint = (env.get("A3GAME_VLM_BASE_URL")
                or env.get("DASHSCOPE_BASE_URL") or "").rstrip("/")
    if not endpoint and env.get("DASHSCOPE_WORKSPACE_ID"):
        workspace = env["DASHSCOPE_WORKSPACE_ID"]
        if not all(c.isascii() and (c.isalnum() or c == "-") for c in workspace):
            raise ValueError("invalid DASHSCOPE_WORKSPACE_ID")
        endpoint = (f"https://{workspace}.cn-beijing.maas.aliyuncs.com"
                    "/compatible-mode/v1")
    if endpoint:
        parsed = urlparse(endpoint)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.query or parsed.fragment
                or not parsed.hostname
                or not parsed.hostname.endswith(".aliyuncs.com")
                or parsed.path != "/compatible-mode/v1"):
            raise ValueError("profile requires a DashScope HTTPS compatible-mode/v1 "
                             "base URL without credentials or query parameters")
    audio_endpoint = env.get("A3GAME_AUDIO_JUDGE_BASE_URL")
    if audio_endpoint and audio_endpoint.rstrip("/") != endpoint:
        raise ValueError("audio endpoint conflicts with whitebox profile endpoint")
    key_present = bool(env.get("A3GAME_VLM_API_KEY") or env.get("DASHSCOPE_API_KEY"))
    if require_ready and (not endpoint or not key_present):
        missing = []
        if not key_present:
            missing.append("DASHSCOPE_API_KEY (or A3GAME_VLM_API_KEY)")
        if not endpoint:
            missing.append("DASHSCOPE_BASE_URL (or DASHSCOPE_WORKSPACE_ID for Beijing)")
        raise ValueError("judge configuration missing: " + "; ".join(missing))
    env.update(FROZEN_ENV)
    if endpoint:
        env["A3GAME_VLM_BASE_URL"] = endpoint
        env["A3GAME_AUDIO_JUDGE_BASE_URL"] = endpoint
    return {
        "profile": PROFILE_ID,
        "model": PINNED_MODEL,
        "endpoint": endpoint or None,
        "api_key_present": key_present,
        "ready_to_connect": bool(endpoint and key_present),
        "temperature": 0,
        "enable_thinking": False,
        "max_tokens": 8192,
        "timeout_s": 180,
        "columns": ["C1", "C2", "C3", "Q", "G", "P", "CH"],
        "current_inputs": ["screenshots", "text", "selected_source_files", "recorded_game_audio"],
        "audio_connected": True,
        "audio_model": AUDIO_MODEL,
        "audio_model_is_moving_alias": True,
        "audio_strategy": "per_trial_model_observations_then_rubric_judge",
        "human_scoring": False,
    }


def _red_png() -> str:
    """Generate a 64x64 red PNG without optional imaging dependencies."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 64) * 64))
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def check_dashscope_judge() -> dict[str, Any]:
    """One paid API request; synthetic capability check, not a game score."""
    from models.reasoning.judges import VLMJudgeModel

    config = configure_dashscope_whitebox()
    response = VLMJudgeModel().judge(
        prompt=(
            "Capability check. Return only JSON with a checks array. Each item "
            "must have id, status (PASS/FAIL/UNKNOWN), evidence (nonempty list of "
            "strings). Check image: the attached image is uniformly red. "
            "Check code: the supplied function returns 3 for add(1,2): "
            "def add(a,b): return a+b. "
            "Check audio: the game plays a sound on collision. No audio, game "
            "recording or collision trace is provided. Unobserved claims must "
            "be UNKNOWN; do not infer sound from image or code. "
            "Use exactly the ids image, code, audio."),
        images_b64=[_red_png()],
    )
    try:
        body = json.loads(response.text)
        checks = body["checks"]
        if not isinstance(checks, list) or len(checks) != 3:
            raise ValueError("expected three checks")
        statuses: dict[str, str] = {}
        for item in checks:
            identifier = item["id"]
            if identifier in statuses:
                raise ValueError("duplicate check")
            evidence = item["evidence"]
            if (not isinstance(evidence, list) or not evidence
                    or any(not isinstance(e, str) or not e.strip() for e in evidence)):
                raise ValueError("missing evidence")
            statuses[identifier] = item["status"]
        if statuses != {"image": "PASS", "code": "PASS", "audio": "UNKNOWN"}:
            raise ValueError("capability verdicts do not match supplied evidence")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"judge preflight failed: {exc}") from exc
    return {"status": "passed", "kind": "synthetic_capability_check",
            "game_evaluated": False, "configuration": config,
            "checks": checks, "provenance": response.provenance}


def check_dashscope_audio() -> dict[str, Any]:
    """One paid request with an explicitly synthetic tone, not gameplay evidence."""
    import io
    import math
    import wave
    from models.reasoning.judges import AudioJudgeModel
    config = configure_dashscope_whitebox()
    memory = io.BytesIO()
    with wave.open(memory, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 16000)))
                                 for i in range(32000)))
    response = AudioJudgeModel().judge(
        prompt=('This is a synthetic capability check, not a game. Listen to the actual attachment. '
                'Return only JSON: {"audible_tone": true/false, "has_speech": true/false, '
                '"game_collision_proven": "UNKNOWN|PASS|FAIL"}. '
                'No gameplay or collision observation was provided; do not infer it from the tone.'),
        audio_b64=[("wav", base64.b64encode(memory.getvalue()).decode("ascii"))])
    try:
        body = json.loads(response.text)
        if not (body.get("audible_tone") is True and body.get("has_speech") is False
                and body.get("game_collision_proven") == "UNKNOWN"):
            raise ValueError("audio verdicts do not match supplied evidence")
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError("audio judge preflight failed: invalid capability verdicts") from exc
    return {"status": "passed", "kind": "synthetic_audio_capability_check",
            "game_evaluated": False, "model": config["audio_model"],
            "checks": body, "provenance": response.provenance}
