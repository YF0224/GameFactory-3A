"""Read-only resolution of the delivered web launch command and document."""
from __future__ import annotations
import hashlib,json,os,re,sys
from pathlib import Path
from urllib.parse import quote

SKIP={"node_modules",".git",".godot",".cache",".vite"}

def author_entry(project):
    """Honor explicit delivered generation metadata; never repair game files.

    Historical absolute paths can be rebased only at the exact declared project
    component (including the original game/stage marker in recorder copies).
    Missing, ambiguous, escaping and symlink entries are engineering errors.
    """
    import hashlib
    report=project/'generation_report.json'
    if not report.is_file():return None
    if report.is_symlink():raise ValueError('Author entry report is linked')
    value=json.loads(report.read_text())
    if value.get('schema_version')!='gamefactory3a.generation_report.v1' or value.get('engine')!='three_js':return None
    entry=value.get('entrypoint')
    if not entry:return None
    if not isinstance(entry,str) or Path(entry).suffix.lower()!='.html':return None
    original=Path(entry)
    if '..' in original.parts:raise ValueError('Author entry escapes original delivery')
    if original.is_absolute():
        if original.is_relative_to(project):relative=original.relative_to(project)
        else:
            markers={project.name} if project.name not in {'project','runtime','input'} else set()
            if value.get('game_id') and value.get('stage'):
                markers.add(value['game_id']+'_'+value['stage'])
            positions=[i for i,part in enumerate(original.parts[:-1]) if part in markers]
            if len(positions)!=1:raise ValueError('Author entry cannot be unambiguously rebased')
            relative=Path(*original.parts[positions[0]+1:])
    else:relative=original
    path=project/relative
    if any((project/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)):
        raise ValueError('Author entry contains a linked path')
    if not path.resolve().is_relative_to(project) or not path.is_file():raise ValueError('Author entry missing or escapes delivery')
    return path,dict(report=str(report),report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
        original_entry=entry,relative_entry=str(relative),entry_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        original_author_files_unchanged=True)


def build_only_vite(package):
    """Conservative build-only recognition; shell wrappers/other builders are not Vite.

    Only the unambiguous default-root/default-output command is supported here.
    Existing dev/start/preview routes always retain precedence.
    """
    scripts = package.get('scripts') or {}
    dependencies = {**(package.get('dependencies') or {}),
                    **(package.get('devDependencies') or {})}
    return (isinstance(scripts, dict)
            and not any(scripts.get(k) for k in ('dev', 'start', 'preview'))
            and isinstance(scripts.get('build'), str)
            and re.fullmatch(r'\s*vite[ \t]+build\s*', scripts['build']) is not None
            and isinstance(dependencies.get('vite'), str) and bool(dependencies['vite'].strip()))


def configured_vite(project, package):
    """Use the authored Vite tool/config when the manifest omits npm scripts.

    Never invent an npm script or rewrite module imports. Restrict this route to
    an unambiguous root document/config; explicit delivered launch scripts win.
    """
    scripts = package.get('scripts') or {}
    deps = {**(package.get('dependencies') or {}), **(package.get('devDependencies') or {})}
    if any(scripts.get(k) for k in ('dev', 'start', 'build', 'preview')) or not deps.get('vite'):
        return None
    configs = [p for p in project.glob('vite.config.*') if p.suffix in ('.js', '.mjs', '.ts', '.mts', '.cjs', '.cts')]
    if not configs:
        return None
    if len(configs) != 1 or configs[0].is_symlink() or not configs[0].is_file():
        raise ValueError('scriptless Vite requires one ordinary authored config')
    config = configs[0]
    text = config.read_text()
    roots = re.findall(r'\broot\s*:\s*([^,}\n]+)', text)
    permitted = {"'.'", '"."', "'./'", '"./"', 'path.dirname(new URL(import.meta.url).pathname)'}
    if len(roots) > 1 or any(v.strip() not in permitted for v in roots):
        raise ValueError('scriptless Vite custom root requires explicit launch configuration')
    entry = project / 'index.html'
    if not entry.is_file() or entry.is_symlink():
        raise ValueError('scriptless Vite requires an ordinary root index.html')
    return {'config': str(config), 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
            'package_sha256': hashlib.sha256((project / 'package.json').read_bytes()).hexdigest(),
            'entry_sha256': hashlib.sha256(entry.read_bytes()).hexdigest(),
            'declared_vite': deps['vite'], 'author_files_modified': False}


def build_environment(project):
    """Validate the explicitly selected web environment *before* the build runs.

    NodeToolchain inherits this environment for npm run build. Never discover a
    different game's cache, mutate os.environ, or rewrite the author's Vite config.
    The caller may explicitly select its own installed working copy as WEB_ENV.
    """
    project = Path(project).resolve()
    configs = list(project.glob('vite.config.*'))
    needs_shared = any('A3GAME_WEB_ENV' in p.read_text(errors='replace') for p in configs)
    shared = os.environ.get('A3GAME_WEB_ENV', '').strip()
    if needs_shared and not shared:
        raise ValueError('Vite build requires explicit A3GAME_WEB_ENV before build (authored config)')
    if not shared:
        return {}
    from .dependencies import verify_critical_packages
    root = Path(shared).expanduser().resolve()
    if verify_critical_packages(root, ['vite', 'three']) or not (root/'node_modules/.bin/vite').is_file():
        raise ValueError('A3GAME_WEB_ENV lacks a complete Vite/Three build environment')
    return {'A3GAME_WEB_ENV': str(root)}


def resolve_launch(project):
    project=Path(project).resolve()
    declared=author_entry(project)
    # A nested explicitly delivered HTML bundle is its own static document.
    # Root index.html still uses the original package/Vite command as before.
    if declared is not None and declared[0].parent!=project:
        entry,proof=declared
        return dict(version='whitebox-three-launch.v2',mode='static',script=None,
            script_text=None,cwd=str(project),serve_root=str(entry.parent),entry=str(entry),
            url_path='/'+quote(entry.name) if entry.name!='index.html' else '/',
            build_script=None,launch_verified=False,author_entry=proof)
    manifest=project/"package.json"
    package=json.loads(manifest.read_text()) if manifest.is_file() else {}
    scripts=package.get("scripts") or {}
    if not isinstance(scripts,dict):
        raise ValueError("package scripts must be an object")
    script=next((s for s in ("dev","start") if isinstance(scripts.get(s),str) and scripts[s].strip()),None)
    mode="script" if script else "static"
    if not script and scripts.get("build") and scripts.get("preview"):
        script="preview";mode="build_preview"
    configured = configured_vite(project, package) if not script else None
    if configured:
        return dict(version='whitebox-three-launch.v2', mode='configured_vite', script=None,
            script_text=None, cwd=str(project), serve_root=str(project), entry=str(project/'index.html'),
            url_path='/', build_script=None, launch_verified=False, authored_vite=configured)
    vite_static = not script and build_only_vite(package)
    if vite_static:
        # The existing client executes the authored build under import_build_timeout.
        # This mode supplies its preview via http.server, not an invented npm script.
        for config in sorted(project.glob('vite.config.*')):
            text = config.read_text(errors='replace')
            if re.search(r'\broot\s*:', text):
                raise ValueError('build-only Vite with custom root requires explicit launch configuration')
            outputs = re.findall(r'\boutDir\s*:\s*([^,}\n]+)', text)
            if any(re.fullmatch(r"['\"]dist['\"]", value.strip()) is None for value in outputs):
                raise ValueError('build-only Vite requires the declared default dist output')
        if not (project/'index.html').is_file():
            raise ValueError('build-only Vite requires a root index.html')
        if (project/'dist').is_symlink():
            raise ValueError('build-only Vite dist must not be a symlink')
        build_environment(project)
        mode = 'build_preview'
    root=project/"dist" if mode=="build_preview" else project
    if not script and (project/"dist/index.html").is_file():
        root=project/"dist"
    # Only a literal Vite root is resolved offline. Dynamic config remains
    # visible as an ambiguity; the harness never edits the configuration.
    if script and mode!="build_preview" and re.search(r"(?:^|[ /])vite(?:\s|$)",scripts[script]):
        for config in sorted(project.glob("vite.config.*")):
            match=re.search(r"\broot\s*:\s*['\"]([^'\"]+)['\"]",config.read_text(errors="replace"))
            if match:
                proposed=(project/match[1]).resolve()
                if not proposed.is_relative_to(project) or not proposed.is_dir():
                    raise ValueError("Vite root escapes delivery or is missing")
                root=proposed;break
    entries=[]
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in SKIP and not (Path(folder)/d).is_symlink()]
        entries.extend(p for n in files if (p:=Path(folder)/n).suffix.lower()=='.html' and not p.is_symlink() and p.resolve().is_relative_to(root))
    preferred=root/"index.html"
    if preferred in entries:entry=preferred
    elif len(entries)==1:entry=entries[0]
    elif mode=="build_preview":entry=root/"index.html" # verified after build, by HTTP as well
    elif script and not entries:entry=None # delivered server can generate HTML
    else:raise ValueError("web HTML entry missing or ambiguous: "+str([str(p.relative_to(root)) for p in entries]))
    path="/" if entry is None or entry.name=="index.html" and entry.parent==root else "/"+quote(entry.relative_to(root).as_posix())
    return {"version":"whitebox-three-launch.v2","mode":mode,"script":script,"script_text":scripts.get(script),"cwd":str(project),"serve_root":str(root),"entry":str(entry) if entry else None,"url_path":path,"build_script":"build" if mode=="build_preview" else None,"launch_verified":False, **({"preview_provider":"python_http_server", "build_kind":"vite_build_only"} if vite_static else {})}

def launch_command(selection,package_manager,host,port):
    if selection['mode'] == 'configured_vite':
        project = Path(selection['cwd'])
        proof = selection['authored_vite']
        if (configured_vite(project, json.loads((project/'package.json').read_text())) != proof):
            raise ValueError('authored Vite launch source changed')
        binary = project/'node_modules/.bin/vite'
        expected = project/'node_modules/vite/bin/vite.js'
        if not binary.is_file() or binary.resolve() != expected.resolve():
            raise ValueError('authored Vite local executable is unavailable or points outside its package')
        return [str(binary), '--config', proof['config'], '--host', host, '--port', str(port), '--strictPort']
    if selection["mode"]=="static" or selection.get("preview_provider")=="python_http_server":
        return [sys.executable,"-m","http.server",str(port),"--bind",host,"--directory",selection["serve_root"]]
    command=[str(package_manager),"run",selection["script"]]
    # These switches belong to Vite; arbitrary start scripts receive env only.
    text=selection["script_text"]
    if re.search(r"(?:^|[ /])vite(?:\s|$)",text):
        command += ["--","--host",host,"--port",str(port),"--strictPort"]
    return command
