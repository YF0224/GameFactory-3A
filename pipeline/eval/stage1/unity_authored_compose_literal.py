"""Recover an exact delivered compose literal without executing its author script."""
import ast
import json
import math
from pathlib import Path

from .protocol import dump, sha

VERSION = 'literal-authored-compose-job.v1'


def _literal(node):
    # Reject duplicate keys and Python values that JSON would silently normalize.
    for part in ast.walk(node):
        if isinstance(part, ast.Dict):
            keys = [ast.literal_eval(key) for key in part.keys if key is not None]
            if len(keys) != len(part.keys) or any(type(key) is not str for key in keys) or len(set(keys)) != len(keys):
                raise ValueError('Compose literal must have unique string keys')
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as error:
        raise ValueError('Compose job must be an original literal') from error
    def check(item):
        if type(item) in (str, int, bool) or item is None:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item: check(child)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str: raise ValueError('Compose job keys must be strings')
                check(child)
            return
        raise ValueError('Compose literal must preserve JSON types')
    check(value)
    if not isinstance(value, dict):
        raise ValueError('Compose job must be an object')
    return value


def extract(project, recipe):
    project, recipe = Path(project).resolve(), Path(recipe)
    if (recipe.is_symlink() or not recipe.resolve().is_relative_to(project.parent)
            or recipe.suffix != '.py' or recipe.stat().st_size > 1_000_000):
        raise ValueError('Compose recipe must be a bounded original delivery Python file')
    text = recipe.read_text()
    tree = ast.parse(text)
    # The reviewed recipe must bind one complete literal to spec, followed by a
    # public UnityClient compose_scene(spec, ...) call in the same compose branch.
    candidates = []
    for branch in ast.walk(tree):
        if not isinstance(branch, ast.If): continue
        test = branch.test
        if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                and test.left.id == 'op' and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
                and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == 'compose'): continue
        assignments = [item for item in branch.body if isinstance(item, ast.Assign)
                       and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name)
                       and item.targets[0].id == 'spec']
        if len(assignments) != 1: raise ValueError('Compose branch needs one literal assignment')
        assignment = assignments[0]
        if not isinstance(assignment.value, ast.Dict): raise ValueError('Compose job must be an original literal')
        spec = _literal(assignment.value)
        following = branch.body[branch.body.index(assignment)+1:]
        if len(following) != 1 or not isinstance(following[0], ast.Expr):
            raise ValueError('Compose branch may not modify the literal before submission')
        statement = following[0]
        calls = [item for item in ast.walk(statement) if isinstance(item, ast.Call)
                 and isinstance(item.func, ast.Attribute) and item.func.attr == 'compose_scene']
        if len(calls) != 1: raise ValueError('Compose literal must have one public compose call')
        call = calls[0]
        if (not isinstance(call.func.value, ast.Attribute) or call.func.value.attr != 'world'
                or not isinstance(call.func.value.value, ast.Name) or call.func.value.value.id != 'u'
                or len(call.args) != 1 or not isinstance(call.args[0], ast.Name) or call.args[0].id != 'spec'
                or any(keyword.arg != 'timeout' or not isinstance(keyword.value, ast.Constant)
                       or type(keyword.value.value) not in (int, float) for keyword in call.keywords)):
            raise ValueError('Compose call must submit the unchanged literal to u.world')
        # The enclosing expression is exactly save(name, compose_call), with no
        # arbitrary wrapper that could transform spec or execute author code.
        wrapper = statement.value
        if (not isinstance(wrapper, ast.Call) or not isinstance(wrapper.func, ast.Name)
                or wrapper.func.id != 'save' or wrapper.keywords or len(wrapper.args) != 2
                or not isinstance(wrapper.args[0], ast.Constant)
                or wrapper.args[0].value != 'scene_compose' or wrapper.args[1] is not call):
            raise ValueError('Compose call must be directly recorded by save')
        candidates.append((spec, assignment, statement))
    if len(candidates) != 1: raise ValueError('One unambiguous authored compose branch required')
    spec, assignment, statement = candidates[0]
    scene = spec.get('output_scene')
    rel = Path(scene) if isinstance(scene, str) else Path('/')
    if (rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'Assets'
            or rel.suffix != '.unity' or not isinstance(spec.get('objects'), list) or not spec['objects']):
        raise ValueError('Authored literal must bind an Assets scene and original objects')
    return {'version': VERSION, 'project': str(project), 'recipe': str(recipe.resolve()),
            'recipe_sha256': sha(recipe), 'assignment_line': assignment.lineno,
            'assignment_end_line': assignment.end_lineno,
            'assignment_source': ast.get_source_segment(text, assignment),
            'compose_call_line': statement.lineno, 'compose_call_end_line': statement.end_lineno,
            'compose_call_source': ast.get_source_segment(text, statement), 'spec': spec}


def preserve(project, recipe, output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError('Preserve original derivations; output must be new')
    result = extract(project, recipe)
    output.mkdir(parents=True)
    dump(output/'job.json', result['spec'])
    result.update(job_source=str(output/'job.json'), job_sha256=sha(output/'job.json'),
                  author_script_executed=False, literal_values_changed=False)
    dump(output/'derivation.json', result)
    return {'job_mode': VERSION, 'job_source': result['job_source'],
            'job_sha256': result['job_sha256'], 'literal_derivation': str(output/'derivation.json'),
            'literal_derivation_sha256': sha(output/'derivation.json')}


def verify(entry, project):
    if entry.get('job_mode') != VERSION: raise ValueError('Unknown literal job mode')
    path = Path(entry['literal_derivation'])
    if path.is_symlink() or sha(path) != entry['literal_derivation_sha256']:
        raise ValueError('Literal derivation SHA changed')
    result = json.loads(path.read_text())
    actual = extract(project, result['recipe'])
    expected = dict(actual, job_source=entry['job_source'], job_sha256=entry['job_sha256'],
                    author_script_executed=False, literal_values_changed=False)
    job = Path(entry['job_source'])
    if (json.dumps(result, sort_keys=True) != json.dumps(expected, sort_keys=True) or job.is_symlink() or job.parent.resolve() != path.parent.resolve()
            or sha(job) != entry['job_sha256']
            or json.dumps(json.loads(job.read_text()), sort_keys=True) != json.dumps(actual['spec'], sort_keys=True)
            or actual['spec']['output_scene'] != entry['scene']):
        raise ValueError('Literal job does not preserve the exact authored recipe')
    return actual['spec']
