"""Prove a lock-only rebasing to an unchanged absolute local plugin dependency.

No package/version/dependency record can change. The old lock location is
retained as evidence; the runtime link must resolve the already authored absolute
file dependency and the formal pinned Three.js plugin. Capture validation still
checks every authored file and adapter pin independently.
"""
import json
from pathlib import Path
from .protocol import sha

VERSION = 'npm-absolute-local-plugin-lock-rebase.v1'


def proof(root):
    root = Path(root)
    before = root/'input/project'
    after = root/'runtime/project'
    original = before/'package-lock.json'
    updated = after/'package-lock.json'
    try:
        if sha(before/'package.json') != sha(after/'package.json'):
            return None
        package = json.loads((before/'package.json').read_text())
        old = json.loads(original.read_text())
        new = json.loads(updated.read_text())
        if old.get('lockfileVersion') != 3 or new.get('lockfileVersion') != 3:
            return None
        if {k:v for k,v in old.items() if k != 'packages'} != {k:v for k,v in new.items() if k != 'packages'}:
            return None
        prior, current = old['packages'], new['packages']
        name = '@a3game/playable'
        link = 'node_modules/'+name
        declaration = package.get('dependencies', {}).get(name, '')
        if not declaration.startswith('file:/'):
            return None
        target = Path(declaration[5:]).resolve(strict=True)
        formal = Path(__file__).resolve().parents[3]/'engine_adapters/three_js/plugin/A3GamePlayable'
        if target != formal.resolve(strict=True):
            return None
        old_link, new_link = prior[link], current[link]
        if set(old_link) != {'resolved', 'link'} or set(new_link) != {'resolved', 'link'}:
            return None
        if old_link['link'] is not True or new_link['link'] is not True:
            return None
        old_key, new_key = old_link['resolved'], new_link['resolved']
        if (not isinstance(old_key, str) or not isinstance(new_key, str)
                or not old_key.startswith('../') or not new_key.startswith('../') or old_key == new_key):
            return None
        if (after/new_key).resolve(strict=True) != target:
            return None
        installed = after/link
        if not installed.is_symlink() or installed.resolve(strict=True) != target:
            return None
        if prior[old_key] != current[new_key]:
            return None
        unchanged_old = {k:v for k,v in prior.items() if k not in {old_key,link}}
        unchanged_new = {k:v for k,v in current.items() if k not in {new_key,link}}
        if unchanged_old != unchanged_new or old_key in current or new_key in prior:
            return None
        plugin_manifest = target/'package.json'
        plugin = json.loads(plugin_manifest.read_text())
        record = prior[old_key]
        fields = ('name','version','license','dependencies','devDependencies','peerDependencies','optionalDependencies')
        if any(record.get(k) != plugin.get(k) for k in fields):
            return None
        if record.get('name') != name:
            return None
        return dict(version=VERSION, before_sha256=sha(original), after_sha256=sha(updated),
            package_json_sha256=sha(before/'package.json'), old_lock_key=old_key,
            new_lock_key=new_key, authored_absolute_dependency=declaration,
            resolved_plugin=str(target), plugin_manifest_sha256=sha(plugin_manifest),
            unchanged_plugin_record=record, all_other_lock_records_unchanged=True,
            rule='lock path rebase only; unchanged absolute authored dependency and exact formal plugin link')
    except (OSError, ValueError, KeyError, TypeError):
        return None
