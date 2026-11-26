"""Model calls for evaluation: Codex CLI, read-only, strict JSON, closed schema.

Rules (unchanged from the historical evaluator):

* the judge/planner runs read-only inside the supplied input directory;
* the reply must be one JSON object (no duplicate keys, no NaN/Infinity) that
  matches the closed schema exactly — the schema is never relaxed;
* at most one bounded format retry, sharing the original deadline; both raw
  replies are kept and malformed output never becomes a verdict;
* CLI host / transport outages are ``HarnessError``, never a product verdict;
* no model substitution and no fallback model.

Every call writes ``<calls_dir>/<name>[_NNN]/`` with prompt.txt, schema.json,
events.jsonl, stderr.log, response.json, invocation.json, and the first
folder of a call gets ``accepted_response.json`` pointing at the reply used.
"""
from __future__ import annotations

from ...model_config import JUDGE_MODEL

import hashlib
from contextlib import ExitStack
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from .paths import write_json

READ_ONLY_INSTRUCTIONS = """Evaluation invocation constraints:
Use only read-only shell exec to inspect the supplied delivery and evidence files.
Do not invoke MCP tools, connectors, plugins, skills, subagents, or other tools.
Do not discover or read framework/plugin instructions or unrelated repositories.
Use bounded reads and searches within the supplied task paths; avoid repeated reads
and broad recursive listings. Do not write files or run games, builds, or installers.
Return only the JSON required by the supplied schema. Never invent observations,
evidence references, missing verdicts, or successful runtime behavior.

"""
DEFAULT_MODEL = JUDGE_MODEL
SCRUBBED_ENV_WORDS = ('DASHSCOPE', 'AWS_SECRET', 'ANTHROPIC_API', 'GEMINI_API')
TRANSPORT_FAILURES = ('timed out negotiating with the code-mode host',
                      'code-mode host is disabled',
                      'gRPC code-mode host timed out waiting for session opening response')

# --- schema builders -------------------------------------------------------
S = {'type': 'string'}
N = {'type': 'number'}
I = {'type': 'integer'}
B = {'type': 'boolean'}


def obj(properties: dict) -> dict:
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def arr(items: dict, **limits) -> dict:
    return {'type': 'array', 'items': items, **limits}


def enum(*values: str) -> dict:
    return {'type': 'string', 'enum': list(values)}


class HarnessError(RuntimeError):
    """Tool/transport failure. Never scored as a product result."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f'duplicate JSON key {key!r}')
        out[key] = value
    return out


def _reject_constant(value):
    raise ValueError(f'non-standard JSON constant {value}')


def parse_strict(raw: bytes):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def validate_schema(value, schema, path='$', _root=None):
    """Validate the closed JSON-schema subset produced by the builders above."""
    _root = schema if _root is None else _root
    if '$ref' in schema:
        target = schema['$ref']
        if not target.startswith('#/$defs/'):
            raise ValueError(f'{path}: unsupported schema reference')
        return validate_schema(value, _root['$defs'][target[len('#/$defs/'):]], path, _root)
    if 'anyOf' in schema:
        for variant in schema['anyOf']:
            try:
                return validate_schema(value, variant, path, _root)
            except ValueError:
                pass
        raise ValueError(f'{path}: value does not match any allowed schema variant')
    typ = schema['type']
    if isinstance(typ, list):
        for variant in typ:
            try:
                return validate_schema(value, dict(schema, type=variant), path, _root)
            except ValueError:
                pass
        raise ValueError(f'{path}: value does not match allowed types {typ}')
    checks = {'null': value is None, 'object': isinstance(value, dict), 'array': isinstance(value, list),
              'string': isinstance(value, str), 'boolean': isinstance(value, bool),
              'integer': isinstance(value, int) and not isinstance(value, bool),
              'number': isinstance(value, (int, float)) and not isinstance(value, bool)}
    if typ not in checks:
        raise ValueError(f'{path}: unsupported schema type {typ}')
    if not checks[typ]:
        raise ValueError(f'{path}: expected {typ}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: invalid enum value')
    if typ == 'string' and 'pattern' in schema and re.search(schema['pattern'], value) is None:
        raise ValueError(f'{path}: string does not match pattern')
    if typ in ('integer', 'number'):
        if 'minimum' in schema and value < schema['minimum']:
            raise ValueError(f'{path}: below minimum')
        if 'maximum' in schema and value > schema['maximum']:
            raise ValueError(f'{path}: above maximum')
    if typ == 'object':
        if set(value) != set(schema['properties']):
            missing = sorted(set(schema['properties']) - set(value))
            extra = sorted(set(value) - set(schema['properties']))
            raise ValueError(f'{path}: missing or unexpected keys; missing={missing}, unexpected={extra}')
        for key, child in schema['properties'].items():
            validate_schema(value[key], child, f'{path}.{key}', _root)
    if typ == 'array':
        if 'minItems' in schema and len(value) < schema['minItems']:
            raise ValueError(f'{path}: fewer than minItems {schema["minItems"]}')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise ValueError(f'{path}: more than maxItems {schema["maxItems"]}')
        for i, child in enumerate(value):
            validate_schema(child, schema['items'], f'{path}[{i}]', _root)


def _new_folder(calls_dir: Path, name: str) -> Path:
    folder = calls_dir / name
    n = 2
    while folder.exists():
        folder = calls_dir / f'{name}_{n:03d}'
        n += 1
    folder.mkdir(parents=True)
    return folder


TRANSPORT_RETRIES = int(os.environ.get('A3GAME_TRANSPORT_RETRIES', 3))
TRANSPORT_RETRY_WAIT_S = int(os.environ.get('A3GAME_TRANSPORT_RETRY_WAIT_S', 120))


def _transport_failure(folder: Path):
    lines = (folder / 'stderr.log').read_text(errors='replace').splitlines()
    hits = [{'line': i, 'text': t} for i, t in enumerate(lines, 1)
            if any(p in t for p in TRANSPORT_FAILURES)]
    return hits or None


def _retry_suffix(kind: str, error: str, raw: bytes, response_path: Path) -> str:
    if kind == 'json':
        return ('\nYour previous response was not valid JSON: ' + error
                + '\nThe original response is preserved at ' + str(response_path)
                + '. Return exactly one complete JSON object matching the supplied schema. '
                'Do not invent missing verdicts or observations; no markdown or commentary.')
    return ('\nYour previous JSON failed the closed output schema or validator: ' + error
            + '\nPREVIOUS_RESPONSE_BEGIN\n' + raw.decode('utf-8', errors='replace') + '\nPREVIOUS_RESPONSE_END'
            '\nCopy every valid field unchanged and fix only what was named. Return a complete replacement '
            'JSON object with exactly the schema keys. Do not redo the analysis, invent observations or claim PASS.')


def _claude_executable() -> str:
    import shutil
    return os.environ.get('A3GAME_CLAUDE_EXECUTABLE') or shutil.which('claude') or str(Path.home() / '.local/bin/claude')


def _claude_command(model: str, schema: dict, read_dirs) -> list:
    """Claude Code print mode: read-only tools only, schema-constrained output."""
    cmd = [_claude_executable(), '-p', '--output-format', 'json', '--model', model,
           '--json-schema', json.dumps(schema, ensure_ascii=False), '--tools', 'Read,Grep,Glob',
           '--settings', json.dumps({'sandbox': {'enabled': False}})]
    for d in read_dirs:
        cmd += ['--add-dir', str(d)]
    return cmd


def _claude_response(folder: Path, model: str) -> None:
    """Write the structured reply to response.json; reject a reply served by another model."""
    try:
        result = json.loads((folder / 'events.jsonl').read_text(errors='replace'))
    except ValueError as exc:
        raise HarnessError(f'claude output is not one JSON result object; see {folder}') from exc
    served = sorted((result.get('modelUsage') or {}).keys())
    write_json(folder / 'served_models.json', {'requested': model, 'served': served})
    if served and not any(m == model or m.startswith(model) for m in served):
        raise HarnessError(f'requested {model} but the reply was served by {served} (routing); see {folder}')
    if result.get('is_error') or str(result.get('subtype', '')).startswith('error'):
        raise HarnessError(f'claude call failed ({result.get("subtype")}); see {folder}/events.jsonl')
    reply = result.get('structured_output')
    if reply is None:
        text = str(result.get('result', '')).strip()
        if text.startswith('```'):
            text = text.strip('`').split('\n', 1)[-1]
        (folder / 'response.json').write_text(text, encoding='utf-8')
    else:
        (folder / 'response.json').write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')


def call_model(calls_dir: Path, *, name: str, prompt: str, schema: dict, cwd: Path,
               model: str = DEFAULT_MODEL, images=(), timeout: int = 480,
               max_attempts: int = 2, validator=None, executable: str = 'codex', read_dirs=None):
    """Run one read-only model call and return the validated JSON result.

    ``gpt-*`` models run through the Codex CLI (read-only sandbox, images attached);
    ``claude-*`` models through Claude Code print mode (Read/Grep/Glob only; image
    files are read with the Read tool; the served model is checked against the request)."""
    if max_attempts not in (1, 2):
        raise ValueError('max_attempts must be 1 or 2')
    claude = model.startswith('claude')
    read_dirs = list(read_dirs) if read_dirs is not None else [Path(cwd).resolve().parent]
    calls_dir, cwd, images = Path(calls_dir), Path(cwd), tuple(Path(i) for i in images)
    effort = os.environ.get('A3GAME_SOL_REASONING_EFFORT', 'medium').strip() or 'medium'
    env = dict(os.environ) if claude else {   # codex: keep unrelated provider secrets out of the judge
        k: v for k, v in os.environ.items() if not any(w in k.upper() for w in SCRUBBED_ENV_WORDS)}
    deadline = time.monotonic() + timeout
    inline_schema = not claude and os.environ.get('A3GAME_CODEX_INLINE_SCHEMA', '1') == '1'
    image_instructions = ('The attached images are direct visual inputs: inspect their actual pixels. '
                          'The shell-only restriction applies to tool calls, not to viewing these attachments. '
                          'Do not infer a frame observation from captions or action expectations. '
                          'If the attachments cannot be seen, report HARNESS_ERROR.\n\n') if images else ''
    base_prompt = READ_ONLY_INSTRUCTIONS + image_instructions + prompt
    if inline_schema:
        base_prompt += '\nReturn exactly one JSON object matching this complete schema. No markdown.\n' + json.dumps(schema, ensure_ascii=False)
    suffix, first = '', None
    # Explicit Stage3 recovery only: preserve every failed invocation and the original bounded
    # correction, then allow at most two *new* schema-guided attempts across all restarts.
    # No rejected reply becomes an accepted answer or a score.
    if os.environ.get('A3GAME_STAGE3_FORMAT_RECOVERY') == '1':
        base = calls_dir / name
        previous = ([base] if base.is_dir() else [])
        previous += sorted(p for p in calls_dir.glob(name + '_[0-9][0-9][0-9]') if p.is_dir())
        if previous and not (base / 'accepted_response.json').is_file():
            failures = [p for p in previous if (p / 'schema_error.json').is_file()
                        or (p / 'parse_error.json').is_file()]
            if len(failures) == len(previous):
                if len(failures) >= 4:
                    raise HarnessError(f'four schema/JSON attempts exhausted; see {failures[-1]}')
                last = failures[-1]
                kind = 'schema' if (last / 'schema_error.json').is_file() else 'json'
                error = json.loads((last / f'{kind}_error.json').read_text())['error']
                raw = (last / 'response.json').read_bytes()
                suffix = _retry_suffix(kind, error, raw, last / 'response.json')
                if kind == 'schema':
                    if '$.checks: expected object' in error and 'checks' in schema.get('properties', {}):
                        ids = list(schema['properties']['checks']['properties'])
                        suffix += ('\nCRITICAL OUTPUT SHAPE: checks must be a JSON OBJECT, not an array: '
                                   '{"checks": {"' + ids[0] + '": { ... }}}. Include every exact id '
                                   'from the output schema once; preserve all supported observations.')
                    if 'steps[' in error and 'probes' in schema.get('properties', {}):
                        suffix += ('\nCRITICAL STEP SHAPE: obey each allowed variant in the schema. '
                                   'Timed steps require duration_ms within the schema maximum; '
                                   'split longer waits into multiple uniquely named steps. '
                                   'Do not fabricate new gameplay observations.')
                first = base
                max_attempts = min(max_attempts, 4 - len(failures))
    transport_retries = 0
    attempt = -1
    while attempt + 1 < max_attempts:
        attempt += 1
        folder = _new_folder(calls_dir, name)
        first = first or folder
        submitted = base_prompt + suffix
        (folder / 'prompt.txt').write_text(submitted, encoding='utf-8')
        write_json(folder / 'schema.json', schema)
        write_json(folder / 'images.json', [{'path': str(p), 'sha256': sha256_bytes(p.read_bytes())}
                                            for p in images])
        submitted_images = images
        if images and not claude and os.environ.get('A3GAME_LOSSLESS_IMAGES') == '1':
            from ..evidence.image_transport import lossless_images
            submitted_images = lossless_images(folder, images)
        output = folder / 'response.json'
        if claude:
            if images:
                submitted += ('\nIMAGES (read every file below with the Read tool before judging; '
                              'cite frames by their FRAME id, not the file):\n'
                              + '\n'.join(str(i) for i in images) + '\n')
                (folder / 'prompt.txt').write_text(submitted, encoding='utf-8')
            image_dirs = sorted({str(Path(i).resolve().parent) for i in images})
            cmd = _claude_command(model, schema, [*read_dirs, *image_dirs])
        else:
            if executable == 'codex' and os.environ.get('A3GAME_CODEX_EXECUTABLE'):
                executable = os.environ['A3GAME_CODEX_EXECUTABLE']     # pinned CLI (e.g. a known-good version)
            cmd = [executable, '--ask-for-approval', 'never', 'exec', '--model', model,
                   '-c', 'model_reasoning_effort=' + json.dumps(effort),
                   '-c', 'model_max_tokens=32768',
                   '--sandbox', 'read-only', '--ephemeral', '--ignore-rules',
                   '--skip-git-repo-check',
                   '-C', str(cwd), '--json', '--color', 'never',
                   '-o', str(output)]
            if not inline_schema:
                cmd += ['--output-schema', str(folder / 'schema.json')]
            # '--image <FILE>...' takes any number of values: a bare trailing '-' was read as an image
            # ("Codex could not read the local image at `-`", shown to the model). One value per flag via
            # '=' and '--' before stdin's '-' (verified with codex-cli 0.166.0, 2026-11-11).
            for image in submitted_images:
                cmd.append(f'--image={image}')
            cmd += ['--', '-']
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            write_json(folder / 'invocation.json', {'model_requested': model, 'status': 'TIMEOUT',
                                                    'attempt': attempt + 1, 'reason': 'deadline exhausted'})
            raise HarnessError(f'model call deadline exhausted; see {folder}')
        started = time.monotonic()
        original_transport = (not claude and images and model == JUDGE_MODEL
                              and os.environ.get('A3GAME_ORIGINAL_IMAGE_TRANSPORT') == '1')
        if original_transport:
            from .original_image_transport import invoke
            try:
                invoke(folder, prompt=submitted, schema=schema, cwd=cwd, model=model,
                       originals=images, images=submitted_images, executable=executable,
                       env=env, timeout=remaining, effort=effort)
            except Exception as exc:
                raise HarnessError(f'original image transport failed; see {folder}: {exc}') from exc
            proc = subprocess.CompletedProcess(cmd, 0)
        else:
            with ExitStack() as stack, (folder / 'events.jsonl').open('w') as out, (folder / 'stderr.log').open('w') as err:
                if not claude and images and os.environ.get('A3GAME_GZIP_REQUESTS') == '1':
                    from ..evidence.request_transport import configured_upstream, gzip_proxy
                    provider, upstream = configured_upstream(env)
                    local = stack.enter_context(gzip_proxy(folder / 'http_transport', upstream=upstream, timeout=remaining))
                    cmd[1:1] = ['-c', f'model_providers.{provider}.base_url=' + json.dumps(local)]
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=cwd,
                                        text=True, env=env, start_new_session=True)
                try:
                    proc.communicate(submitted, timeout=remaining)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=10)
                    write_json(folder / 'invocation.json', {'model_requested': model, 'status': 'TIMEOUT',
                                                            'attempt': attempt + 1,
                                                            'seconds': round(time.monotonic() - started, 2)})
                    raise HarnessError(f'model call timeout; see {folder}')
        if claude and proc.returncode == 0:
            _claude_response(folder, model)
        meta = {'model_requested': model, 'schema_transport': 'inline_strict_local' if inline_schema else 'structured_output', 'command': [c if len(c) < 2000 else '<schema.json>' for c in cmd],
                'exit_code': proc.returncode,
                'seconds': round(time.monotonic() - started, 2), 'attempt': attempt + 1,
                'response_present': output.is_file(), 'retry_of': str(first) if attempt else None}
        if original_transport:
            meta.update(json.loads((folder / 'invocation.json').read_text()))
        transport = _transport_failure(folder)
        if transport:
            meta['status'] = 'HARNESS_ERROR'
            write_json(folder / 'tool_transport_error.json', {'failure_layer': 'cli_tool_transport',
                                                              'diagnostics': transport})
        write_json(folder / 'invocation.json', meta)
        if transport:
            # The CLI's own tool host timed out (no answer from the model side is at fault): the call is kept on
            # disk and sent again unchanged, after a pause, up to TRANSPORT_RETRIES times; it does not use up the
            # bounded correction attempt.
            if transport_retries < TRANSPORT_RETRIES:
                transport_retries += 1
                time.sleep(TRANSPORT_RETRY_WAIT_S * transport_retries)
                attempt -= 1
                continue
            raise HarnessError(f'CLI tool transport unavailable; see {folder}')
        if proc.returncode != 0 or not output.is_file():
            raise HarnessError(f'model CLI failed (no substitution); see {folder}/stderr.log')

        raw = output.read_bytes()
        try:
            result = parse_strict(raw)
        except ValueError as exc:
            write_json(folder / 'parse_error.json', {'response_sha256': sha256_bytes(raw), 'error': str(exc)})
            if attempt + 1 < max_attempts:
                suffix = _retry_suffix('json', str(exc), raw, output)
                continue
            raise HarnessError(f'invalid JSON after one bounded retry; see {folder}') from exc
        try:
            validate_schema(result, schema)
            if validator is not None:
                validator(result)
        except ValueError as exc:
            write_json(folder / 'schema_error.json', {'response_sha256': sha256_bytes(raw), 'error': str(exc)})
            if attempt + 1 < max_attempts:
                suffix = _retry_suffix('schema', str(exc), raw, output)
                continue
            raise HarnessError(f'schema/validator rejected reply after one bounded retry; see {folder}') from exc
        write_json(first / 'accepted_response.json', {
            'path': os.path.relpath(output, first), 'sha256': sha256_bytes(raw), 'attempt': attempt + 1})
        return result
    raise AssertionError('unreachable')


def accepted_response(calls_dir: Path, name: str) -> dict | None:
    """Reload a previously accepted reply (SHA-checked) so finished calls are reused."""
    folder = Path(calls_dir) / name
    pointer = folder / 'accepted_response.json'
    if not pointer.is_file():
        return None
    binding = json.loads(pointer.read_text())
    path = (folder / binding['path']).resolve()
    if not path.is_relative_to(Path(calls_dir).resolve()) or not path.is_file():
        raise ValueError('accepted response escapes calls dir or is missing')
    raw = path.read_bytes()
    if sha256_bytes(raw) != binding['sha256']:
        raise ValueError('accepted response SHA256 mismatch')
    return parse_strict(raw)
