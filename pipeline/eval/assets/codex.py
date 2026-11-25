from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def _matches_type(value, expected):
    types = expected if isinstance(expected, list) else [expected]
    for kind in types:
        if kind == "null" and value is None:
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "array" and isinstance(value, list):
            return True
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
    return False


def validate_schema(value, schema, path="$" ):
    expected = schema.get("type")
    if expected is not None and not _matches_type(value, expected):
        raise ValueError(f"{path}: expected {expected}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is outside enum")
    if isinstance(value, dict):
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ValueError(f"{path}: missing required keys {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ValueError(f"{path}: unexpected keys {extra}")
        for key, child in properties.items():
            if key in value:
                validate_schema(value[key], child, f"{path}.{key}")
        extra_schema = schema.get("additionalProperties")
        if isinstance(extra_schema, dict):
            for key in set(value) - set(properties):
                validate_schema(value[key], extra_schema, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        if len(value) > schema.get("maxItems", float("inf")):
            raise ValueError(f"{path}: too many items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}: value below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path}: value above maximum")


def _redact(text):
    return re.sub(r"sk-[A-Za-z0-9._-]+", "[REDACTED]", text)


def call_codex(root, *, name, prompt, schema, model, images, timeout=600, max_attempts=1):
    if Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("Invalid model-call name")
    folder = Path(root) / "model_calls" / name
    folder.mkdir(parents=True, exist_ok=True)
    prompt_path = folder / "prompt.txt"
    schema_path = folder / "schema.json"
    events_path = folder / "events.jsonl"
    stderr_path = folder / "stderr.log"
    response_path = folder / "response.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    explicit_bin = os.environ.get("A3GAME_CODEX_BIN")
    bundled_bin = Path("/data2/home/xiaotianqi/.vscode-server/extensions/openai.chatgpt-26.1007.21434-linux-x64/bin/linux-x86_64/codex")
    executable = explicit_bin or shutil.which("codex") or (str(bundled_bin) if bundled_bin.is_file() else None)
    if not executable:
        raise RuntimeError("Codex CLI not found; set A3GAME_CODEX_BIN")
    env = os.environ.copy()
    env.setdefault("CODEX_HOME", "/data2/home/xiaotianqi/.codex")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cwd = Path(env.get("A3GAME_CODEX_CWD", "/data3/xiaotianqi/bench_runtime"))
    if not cwd.is_dir():
        raise RuntimeError(f"Codex working directory missing: {cwd}")

    command = [executable, "exec", "--model", model, "--sandbox", "read-only",
               "--ephemeral", "--skip-git-repo-check", "--output-schema", str(schema_path),
               "--json", "--color", "never", "--output-last-message", str(response_path)]
    image_paths = [Path(image).resolve() for image in images]
    for image in image_paths:
        if not image.is_file():
            raise FileNotFoundError(f"Judge image is missing: {image}")
        command.extend(["--image", str(image)])
    command.append("-")
    invocation = {"status": "running", "model": model, "timeout_seconds": timeout,
                  "max_attempts": max_attempts, "sandbox": "read-only",
                  "ephemeral": True, "images": [str(path) for path in image_paths],
                  "command": [Path(executable).name, *command[1:]]}
    (folder / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        result = subprocess.run(command, input=prompt, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, cwd=cwd, env=env,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        events_path.write_text(_redact(stdout), encoding="utf-8")
        stderr_path.write_text(_redact(stderr), encoding="utf-8")
        invocation.update(status="timeout", return_code=None)
        (folder / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise TimeoutError(f"Codex CLI timed out after {timeout}s") from exc
    events_path.write_text(_redact(result.stdout), encoding="utf-8")
    stderr_path.write_text(_redact(result.stderr), encoding="utf-8")
    invocation.update(status="completed" if result.returncode == 0 else "failed",
                      return_code=result.returncode)
    (folder / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Codex CLI exit={result.returncode}: {_redact(result.stderr)[-3000:]}")
    if not response_path.is_file():
        raise RuntimeError("Codex CLI exited successfully without a final response file")
    response_text = response_path.read_text(encoding="utf-8").strip()
    try:
        response = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex final response is not JSON: {exc}") from exc
    validate_schema(response, schema)
    accepted_path = folder / "accepted_response.json"
    accepted_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    invocation.update(status="accepted")
    (folder / "invocation.json").write_text(json.dumps(invocation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return response
