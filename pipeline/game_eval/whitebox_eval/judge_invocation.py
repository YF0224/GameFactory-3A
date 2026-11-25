"""Bind a saved judgment to the actual successful invocation after an explicit retry."""
from pathlib import Path
import re

from .codex import load_plan_json, saved_model_response
from .protocol import dump, sha


def _decoded_response(response):
    """Apply only the judge's lossless keyed-checks transport conversion."""
    if not isinstance(response, dict) or not isinstance(response.get('checks'), dict):
        return response
    checks = []
    for ident, check in response['checks'].items():
        if not isinstance(check, dict) or 'id' in check:
            raise ValueError('Keyed judgment contains an invalid check')
        checks.append({'id': ident, **check})
    return {**response, 'checks': checks}


def _same_judgment(response, raw):
    response = _decoded_response(response)
    if not isinstance(response, dict) or not isinstance(raw, dict):
        return response == raw
    # Key order has no meaning in JSON objects; list check IDs remain unique.
    def indexed(value):
        checks = value.get('checks')
        if not isinstance(checks, list):
            return value
        if any(not isinstance(c, dict) or not isinstance(c.get('id'), str) for c in checks):
            raise ValueError('Saved judgment has invalid check IDs')
        if len({c['id'] for c in checks}) != len(checks):
            raise ValueError('Saved judgment has duplicate check IDs')
        return {**value, 'checks': {c['id']: c for c in checks}}
    return indexed(response) == indexed(raw)


def response_for_judgment(root, name):
    root = Path(root)
    primary = root/'model_calls'/name
    # Existing accepted pointers remain authoritative; never hide a bad binding.
    if (primary/'accepted_response.json').exists():
        return saved_model_response(root, name)
    invocation = primary/'invocation.json'
    if not invocation.is_file():
        return saved_model_response(root, name)
    if load_plan_json(invocation).get('exit_code') == 0:
        if not (primary/'schema_error.json').is_file():
            return saved_model_response(root, name)
        # Exit zero does not make a closed-schema rejection an accepted verdict.
        from .judge_format_recovery import original_failure
        original_failure(primary)
    judgment_path = root/'judgments'/(name+'.json')
    if not judgment_path.is_file():
        return saved_model_response(root, name)
    raw = load_plan_json(judgment_path).get('raw')
    if not isinstance(raw, dict):
        raise ValueError('Saved judgment has no original model response: '+name)
    matches = []
    for folder in sorted(primary.parent.glob(name+'_*')):
        if not re.fullmatch(re.escape(name)+r'_\d{3,}', folder.name):
            continue
        if not (folder/'accepted_response.json').is_file() or not (folder/'invocation.json').is_file():
            continue
        if load_plan_json(folder/'invocation.json').get('exit_code') != 0:
            continue
        response = saved_model_response(root, folder.name)
        if not _same_judgment(load_plan_json(response), raw):
            continue
        # A matching verdict cannot authorize different sources or questions.
        from .judge_line_ordinals import original_prompt_identity
        if original_prompt_identity(primary) != original_prompt_identity(folder):
            raise ValueError('Saved judgment retry changed prompt.txt: '+name)
        from .judge_schema_transport import same_retry_schema
        try:
            same_retry_schema(primary, folder)
        except (ValueError, OSError, KeyError) as exc:
            raise ValueError('Saved judgment retry changed schema.json: '+name) from exc
        if response.parent != folder.resolve():
            raise ValueError('Explicit judgment retry has an indirect response binding: '+name)
        matches.append(response)
    if len(matches) != 1:
        raise ValueError('Saved judgment must match exactly one successful retry: '+name)
    response = matches[0]
    dump(root/'validation_history'/(name+'.invocation_selection.json'), {
        'version':'whitebox-saved-judgment-invocation.v1', 'name':name,
        'judgment':str(judgment_path.relative_to(root)), 'judgment_sha256':sha(judgment_path),
        'response':str(response.relative_to(root)), 'response_sha256':sha(response),
        'invocation_sha256':sha(response.parent/'invocation.json'),
        'original_invocation_sha256':sha(invocation),
        'prompt_sha256':sha(primary/'prompt.txt'),
        'submitted_prompt_sha256':sha(response.parent/'prompt.txt'), 'schema_sha256':sha(primary/'schema.json'),
        'submitted_schema_sha256':sha(response.parent/'schema.json'),
        'model_calls_added':0, 'selection':'Exact saved judgment after lossless keyed-check decoding, same prompt and exactly equivalent SHA-bound schema, successful SHA-bound reply'})
    return response
