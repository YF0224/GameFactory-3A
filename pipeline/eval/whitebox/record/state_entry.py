"""State entry for state-conditioned evaluation (stage3, opt-in per take).

For checks the planner could not reach by normal play (declared unreachable / set aside), a separate take
may start from a deeper game state. The planner writes the state entry as calls to the game's OWN existing
methods / fields, each citing the source line where the game itself makes the same call; the recorder runs
them through reflection right before the first player input (Unity: GAMEFACTORY_UNITY_STATE_ENTRY). Nothing
is added to the game. Whether the state was reached is checked against the game's own events
(``expect_events``); results are scored apart from normal-play results.

Plan field (added to the plan schema only for state-conditioned takes):
  state_entry = {target_state, calls: [{object, member, kind: method|field, args: [str], caller: "file:line",
                 why_not_the_tested_mechanic}], expect_events: [substring], applies_to: [criterion id]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.llm import S, arr, enum, obj

VERSION = 'stage3-state-entry.v1'
ENV = {'unity3d': 'GAMEFACTORY_UNITY_STATE_ENTRY', 'ue5': 'A3GAME_UE_STATE_ENTRY'}
UE_MARKER = 'A3 state entry: done'
UE_START = 'A3 state entry call'
UE_BEGIN = 'A3 state entry: begin'
SOURCE_SUFFIX = {'unity3d': ('.cs',), 'ue5': ('.cpp', '.h'), 'godot': ('.gd',), 'three_js': ('.js', '.ts')}

PROMPT = '''
STATE-CONDITIONED TAKE: the TARGETS below could not be reached by normal play. Besides the probes, write
"state_entry": the shortest way to put the running game into the state where the TARGETS can be tested,
using ONLY members that already exist in the delivered source:
- Unreal Engine: fields must be UPROPERTY(...) in a UCLASS. Methods: UFUNCTION(...), or a plain (non-virtual)
  C++ method of the game's own class declared in its header whose return type is void/bool/int32/float/double
  and whose parameters are only int32/float/bool/double/uint8/const FString& (e.g. StartSection(int32),
  Interact(const FString&)).
- If no allowed member can reach the state, return calls: [] and say why in target_state (no take is run).
- calls: each {object: class name, member: method or field name, kind: "method" | "field", args: values as
  strings}. Prefer methods. Each call MUST cite "caller": "<source file>:<line>" where the game itself makes
  this same call during normal play (e.g. the "next section" handler calling StartSection(Section+1)). A
  field write is allowed only when no method does it.
- PREFER THE GAME'S OWN SAVE / LOAD. If the game has a save / snapshot object and a load method (save
  terminal, checkpoint, pause-menu load, save slot), write ONE save state into that object and then call the
  game's own load method, so the game itself restores abilities, items, progress and position. Unity: a field of
  the game's [Serializable] save class may be set from one JSON string in its JsonUtility form (exactly its
  serialized fields). Unreal: a UPROPERTY save struct / object may be set from its UE text form (ImportText).
  Write it exactly as the game's own save code would (same fields, list order as the game sorts them, e.g.
  ordinal string order "crystal_1","crystal_10","crystal_2"), so the game's own load accepts it unchanged.
  The save state must be one a player could legitimately reach (e.g. all modules earned, standing at the
  checkpoint before the tested spot) - never a state that already contains the tested result.
  Only when no save / load exists, use the game's own progression methods (e.g. start / next section).
- never call or set the member that implements a TARGET's tested behaviour (state why in
  why_not_the_tested_mechanic); the probes must still produce the tested behaviour with player input.
- expect_events: short, stable substrings of game log / event lines the game itself prints once the state is
  reached (e.g. the event NAME of its load / section-start log), from its own logging code; not values that
  depend on field order, timers or exact equality checks. Empty if the game prints nothing.
- applies_to: TARGETS this state is valid for. Leave out TARGETS that depend on progress the entry does not
  recreate (scores / history from earlier sections).
'''


def schema(ids: list[str], direct: bool = False) -> dict:
    if direct:
        call = obj({'object': S, 'member': S, 'kind': enum('method', 'field'), 'args': arr(S, maxItems=6),
                    'caller': S, 'role': enum('input_handler', 'feature_entry', 'setup'),
                    'at_ms': {'type': 'integer', 'minimum': 0, 'maximum': 60000}, 'why': S})
        return obj({'target_state': S, 'calls': arr(call, minItems=0, maxItems=12),
                    'expect_events': arr(S, maxItems=12), 'applies_to': arr(enum(*ids), minItems=1),
                    'postconditions': arr(obj({'criterion_id': enum(*ids), 'log_substring': S, 'frame': S}),
                                          maxItems=len(ids) * 2)})
    call = obj({'object': S, 'member': S, 'kind': enum('method', 'field'), 'args': arr(S, maxItems=6),
                'caller': S, 'why_not_the_tested_mechanic': S})
    return obj({'target_state': S, 'calls': arr(call, minItems=0, maxItems=6),
                'expect_events': arr(S, maxItems=6), 'applies_to': arr(enum(*ids), minItems=1)})


DIRECT_PROMPT = '''
DIRECT TRIGGER TAKE: normal play never reached these TARGETS. Make the game itself run each TARGET's feature by
calling the game's OWN existing functions, in "state_entry" (calls run in order; at_ms = ms after the take starts,
use waits between steps, e.g. a load then 1500 ms later the action). Choose entry points in this order:
1. role "input_handler": the function the player's control calls for this action (e.g. Interact(), the pawn's
   jump / use / confirm handler) - preferred, it keeps the game's whole logic chain;
2. role "feature_entry": the feature's own entry function, only when no handler fits;
3. role "setup": preconditions only (the game's save / load / progression functions, or a field write when no
   function exists) - never write or fake the tested result itself.
Every call must cite "caller": "<source file>:<line>" where the game itself makes that call. Probes may add normal
inputs and waits so the result is visible. For each TARGET add "postconditions": the game log substring (from the
source) and / or what a frame must show once the feature has worked. applies_to = TARGETS this take tests.
Unreal Engine: UPROPERTY fields; UFUNCTION methods or plain non-virtual methods with scalar return / parameters.
If a CALLABLE FUNCTIONS list is given below, use ONLY methods from it (others exist in the source but cannot be
called in the built game, e.g. defined inline or not exported). If a TARGET's feature cannot be started this way,
leave it out of applies_to.
The general rule "never call game functions" is for normal-play takes and does NOT apply here. Engine errors from
earlier direct takes such as "symbol not found" were evaluation-tool faults (since fixed), not proof that a
function cannot be called: such functions may be used again.
'''


def _sources(project: Path, engine: str) -> dict[str, list[str]]:
    found = {}
    for p in project.rglob('*'):
        if p.suffix in SOURCE_SUFFIX.get(engine, ()) and p.is_file() and 'Library' not in p.parts \
                and 'GameFactory3A' not in p.name:
            found[str(p.relative_to(project))] = p.read_text(errors='replace').splitlines()
    return found


def normalize_caller(caller: str) -> str:
    """'<abs>/input/project/Source/X.cpp:12' or 'project/Source/X.cpp:12' -> 'Source/X.cpp:12' (lossless)."""
    c = (caller or '').strip()
    for marker in ('/input/project/', 'input/project/'):
        if marker in c:
            c = c.split(marker, 1)[1]
    if c.startswith('project/'):
        c = c[len('project/'):]
    return c


def validate(entry: dict, project: Path, engine: str, direct: bool = False) -> None:
    """Every call names an existing class + member, and its caller citation is a real source line that
    already makes that call. Raises ValueError with what to fix (planner correction)."""
    if engine not in ENV:
        raise ValueError(f'state entry is not available for {engine} yet')
    src = _sources(project, engine)
    text = '\n'.join('\n'.join(v) for v in src.values())
    problems = []
    for c in entry['calls']:
        if not re.search(rf'\b(class|struct)\s+(?:\w+_API\s+)?{re.escape(c["object"])}\b', text):
            problems.append(f'{c["object"]}: no such class in the delivered source')
        if not re.search(rf'\b{re.escape(c["member"])}\b', text):
            problems.append(f'{c["object"]}.{c["member"]}: member not in the delivered source')
        c['caller'] = normalize_caller(c.get('caller', ''))
        m = re.match(r'(.+?):(\d+)$', c.get('caller', '').strip())
        lines = None
        if m:
            key = next((k for k in src if k == m[1] or k.endswith('/' + m[1].lstrip('/'))), None)
            lines = src.get(key) if key else None
        if lines is None:
            problems.append(f'{c["member"]}: caller "{c.get("caller")}" is not <source file>:<line>')
            continue
        n = int(m[2])
        if engine == 'ue5' and not _ue_reflected(src, c['object'], c['member'], c.get('kind', 'method')):
            native = native_signature(src, c['object'], c['member']) if c.get('kind', 'method') == 'method' else None
            if native is None:
                problems.append(f'{c["object"]}.{c["member"]}: not reachable in Unreal - a field must be UPROPERTY; a '
                                f'method must be UFUNCTION, or a plain C++ method declared in the class with return type '
                                f'void/bool/int32/float/double and at most 3 int32/float/bool/double/uint8/const FString& parameters')
            elif len(native['params']) != len(c.get('args') or []):
                problems.append(f'{c["object"]}.{c["member"]}: takes {len(native["params"])} argument(s), '
                                f'{len(c.get("args") or [])} given')
            else:
                # the call must exist in the BUILT game: a method defined inline in its header usually has no symbol;
                # instance methods need a UCLASS (the live object is found through UE reflection)
                built = Path(project).resolve().parent.parent / 'runtime' / 'project'
                if not native['static'] and not _is_uclass(src, c['object']):
                    problems.append(f'{c["object"]}.{c["member"]}: {c["object"]} is not a UCLASS, so no live object can '
                                    f'be found for an instance call - choose a method of a UCLASS')
                elif (built / 'Binaries').is_dir() or any((built / 'Plugins').glob('*/Binaries')):
                    try:
                        resolve_native(built, c['object'], c['member'], native)
                    except ValueError:
                        problems.append(f'{c["object"]}.{c["member"]}: no callable symbol in the built game (it is '
                                        f'probably defined inline in the header) - choose another function')
        near = lines[max(0, n - 3):n + 2]
        if not any(re.search(rf'\b{re.escape(c["member"])}\b', l) for l in near):
            problems.append(f'{c["member"]}: {c["caller"]} does not call/set {c["member"]}')
    if direct:
        for c in entry['calls']:
            if c.get('kind') == 'field' and c.get('role') != 'setup':
                problems.append(f'{c["object"]}.{c["member"]}: a field write is only allowed as a setup precondition, '
                                f'never to produce the tested result')
    if problems:
        raise ValueError('state_entry: ' + '; '.join(problems))


_NATIVE_TYPES = {'void': 'v', 'bool': 'b', 'int32': 'i', 'int': 'i', 'float': 'f', 'double': 'd', 'uint8': 'h',
                 'FString&': 's'}
_MANGLE = {'v': 'v', 'b': 'b', 'i': 'i', 'f': 'f', 'd': 'd', 'h': 'h', 's': 'RK7FString'}


def native_signature(src: dict, cls: str, member: str) -> dict | None:
    """A plain (non-reflected) C++ method of the game's own class that the UE recorder may call directly:
    declared in the class in a header, not virtual / template, return type and every parameter a simple scalar
    (registers only - no struct returns). Returns {'static', 'const', 'ret', 'params'} or None."""
    for name, lines in src.items():
        if not name.endswith('.h'):
            continue
        text = '\n'.join(lines)
        m = re.search(rf'class\s+(?:\w+_API\s+)?{re.escape(cls)}\b[^{{;]*{{', text)
        if not m:
            continue
        body = text[m.end():]
        for d in re.finditer(rf'(?:^|[;{{}}\s])((?:static\s+|inline\s+|FORCEINLINE\s+)*)(\w+)\s+{re.escape(member)}\s*\(([^)]*)\)\s*(const)?', body):
            quals, ret, params, const = d.group(1), d.group(2), d.group(3).strip(), bool(d.group(4))
            pre = body[max(0, d.start() - 60):d.start()]
            if 'virtual' in quals or 'virtual' in pre.split(';')[-1] or 'template' in pre.split(';')[-1]:
                continue
            if ret not in _NATIVE_TYPES:
                continue
            types = []
            for prm in ([] if params in ('', 'void') else params.split(',')):
                prm = prm.split('=')[0].strip()
                if re.match(r'^const\s+FString\s*&', prm):          # passed by const reference (a pointer in the ABI)
                    types.append('FString&')
                    continue
                t = re.sub(r'\b(const)\b', '', prm).split()
                if not t or t[0] not in _NATIVE_TYPES or t[0] in ('void', 'FString&') or '&' in prm or '*' in prm:
                    break
                types.append(t[0])
            else:
                return {'static': 'static' in quals, 'const': const, 'ret': ret, 'params': types}
    return None


def itanium_symbol(cls: str, member: str, sig: dict) -> str:
    """Itanium C++ mangled name (as dlsym expects it, no leading underscore) of Class::Member(params)."""
    params = ''.join(_MANGLE[_NATIVE_TYPES[t]] for t in sig['params']) or 'v'
    return f"_ZN{'K' if sig['const'] else ''}{len(cls)}{cls}{len(member)}{member}E{params}"


def resolve_native(project: Path, cls: str, member: str, sig: dict) -> dict:
    """Find Class::Member in the game's own module binaries (never engine modules) with nm."""
    import subprocess
    want = itanium_symbol(cls, member, sig)
    libs = sorted((Path(project) / 'Binaries' / 'Mac').glob('*.dylib'))
    # game code often lives in the game's own plugins (never the evaluation recorder's plugin, never the engine)
    libs += sorted(p for p in (Path(project) / 'Plugins').glob('*/Binaries/Mac/*.dylib') if 'A3GamePlayable' not in p.parts)
    for lib in libs:
        try:
            out = subprocess.run(['nm', '-gU', str(lib)], capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        names = [line.split()[-1][1:] for line in out.splitlines() if line.strip()]
        prefix = want[:want.index(member) + len(member) + 1]           # _ZN[K]<len>Class<len>MemberE
        if want not in names:
            # repeated parameter types are abbreviated (S2_ ...) in real symbols: accept the single method of
            # that class + name; overloads stay ambiguous -> error
            cands = [n for n in names if n.startswith(prefix)]
            if len(cands) == 1:
                want = cands[0]
        if want in names:
            return {'symbol': want, 'image': str(lib.resolve()),
                    'sig': ('S' if sig['static'] else 'M') + ':' + ''.join(_NATIVE_TYPES[t] for t in sig['params'])}
    raise ValueError(f'{cls}::{member}: symbol {want} not found in the game module binaries')


def _is_uclass(src: dict, cls: str) -> bool:
    text = '\n'.join('\n'.join(v) for k, v in src.items() if k.endswith('.h'))
    return bool(re.search(rf'UCLASS\s*\([^)]*\)\s*class\s+(?:\w+_API\s+)?{re.escape(cls)}\b', text))


def callable_catalog(project_in: Path, engine: str, limit: int = 220) -> list:
    """UE: game-class methods the recorder can really call in the BUILT game - UFUNCTIONs, and plain methods that
    are exported from the game's own modules with scalar / const FString& parameters. Shown to the Direct Trigger
    planner so it does not pick functions that exist in the source but cannot be called (inline / not exported)."""
    if engine != 'ue5':
        return []
    import subprocess
    built = Path(project_in).resolve().parent.parent / 'runtime' / 'project'
    libs = sorted((built / 'Binaries' / 'Mac').glob('*.dylib'))
    libs += sorted(p for p in (built / 'Plugins').glob('*/Binaries/Mac/*.dylib') if 'A3GamePlayable' not in p.parts)
    exported = set()
    for lib in libs:
        try:
            out = subprocess.run(['nm', '-gU', str(lib)], capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        exported |= {line.split()[-1][1:] for line in out.splitlines() if line.strip()}
    if not exported:                  # game not built yet: no list (would wrongly hide the native methods)
        return []
    src = _sources(project_in, engine)
    text = '\n'.join('\n'.join(v) for k, v in src.items() if k.endswith('.h'))
    classes = re.findall(r'UCLASS\s*\([^)]*\)\s*class\s+(?:\w+_API\s+)?(\w+)', text)
    rows = []
    for cls in dict.fromkeys(classes):
        m = re.search(rf'class\s+(?:\w+_API\s+)?{re.escape(cls)}\b[^{{;]*{{', text)
        body = text[m.end():m.end() + 60000] if m else ''
        names = dict.fromkeys(re.findall(r'\b(\w+)\s*\([^;{)]*\)\s*(?:const)?\s*[;{]', body))
        for mem in names:
            if mem in (cls, 'GENERATED_BODY', 'UFUNCTION', 'UPROPERTY', 'UCLASS', 'FString', 'FName', 'FText', 'FVector',
                       'FRotator', 'FTransform', 'FLinearColor', 'TArray', 'TMap', 'TSet', 'TSubclassOf', 'TObjectPtr',
                       'TWeakObjectPtr', 'TSharedPtr', 'Super', 'return', 'if', 'for', 'while', 'switch', 'sizeof') \
                    or mem.startswith(('~', 'TEXT')):
                continue
            if _ue_reflected(src, cls, mem, 'method'):
                rows.append(f'{cls}::{mem} (UFUNCTION)')
                continue
            sig = native_signature(src, cls, mem)
            if sig is None:
                continue
            want = itanium_symbol(cls, mem, sig)
            prefix = want[:want.index(mem) + len(mem) + 1]
            if want in exported or sum(1 for e in exported if e.startswith(prefix)) == 1:
                rows.append(f"{cls}::{mem}({', '.join(t.replace('FString&', 'const FString&') for t in sig['params'])})")
    # the game's own classes first; shared framework classes (A3Game*) after them
    rows.sort(key=lambda r: ('A3Game' in r.split('::')[0], 0))
    return rows[:limit]


def _ue_reflected(src: dict, cls: str, member: str, kind: str) -> bool:
    macro = 'UPROPERTY' if kind == 'field' else 'UFUNCTION'
    for name, lines in src.items():
        if not name.endswith('.h'):
            continue
        text = '\n'.join(lines)
        m = re.search(rf'class\s+(?:\w+_API\s+)?{re.escape(cls)}\b[^{{;]*{{', text)
        if not m:
            continue
        body = text[m.end():]
        for d in re.finditer(rf'\b{re.escape(member)}\b', body):
            before = body[max(0, d.start() - 400):d.start()]
            last_stmt = re.split(r'[;}]', before)[-1]      # declaration's own preamble only
            if macro in last_stmt:
                return True
    return False


def prepare(plan: dict, engine: str, folder: Path, project: Path | None = None) -> dict | None:
    """Write the recorder's state-entry file; return the env to set while recording (or None).
    UE: a non-reflected method is resolved here to its symbol in the game's own module (native route)."""
    entry = plan.get('state_entry')
    if not entry or not entry.get('calls'):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    calls, unresolved = [], []
    src = _sources(project, engine) if (engine == 'ue5' and project is not None) else {}
    for c in entry['calls']:
        row = {k: c[k] for k in ('object', 'member', 'kind', 'args')}
        row['at_ms'] = int(c.get('at_ms') or 0)
        if engine == 'ue5' and project is not None and c.get('kind', 'method') == 'method' \
                and not _ue_reflected(src, c['object'], c['member'], 'method'):
            sig = native_signature(src, c['object'], c['member'])
            if sig is not None:
                try:
                    row.update(resolve_native(project, c['object'], c['member'], sig))
                except ValueError as exc:      # recorded as a failed call; the other calls of the take still run
                    unresolved.append({'object': c['object'], 'member': c['member'], 'kind': 'method',
                                       'route': 'native_symbol', 'targets': 0, 'ok': False, 'error': str(exc)})
                    continue
        calls.append(row)
    if unresolved:
        (folder / 'state_entry_unresolved.json').write_text(json.dumps(unresolved, ensure_ascii=False))
    path = folder / 'state_entry.json'
    path.write_text(json.dumps({'calls': calls}, ensure_ascii=False))
    return {ENV[engine]: str(path.resolve())}


def verify(record_dir: Path, plan: dict) -> dict:
    """state_reached: every call ran on >=1 target and every expect_events substring appears in the game's
    own events after the entry. 'unverified' when the game logs nothing to check against."""
    entry = plan.get('state_entry') or {}
    found = sorted(Path(record_dir).rglob('state_entry_result.json'))
    if not entry or not found:
        return {'version': VERSION, 'state_reached': False, 'reason': 'state entry did not run'}
    result = json.loads(found[-1].read_text())
    for f in Path(record_dir).rglob('state_entry_unresolved.json'):   # calls that could not be resolved on the host
        result['calls'] = result.get('calls', []) + json.loads(f.read_text())
    calls_ok = all(c.get('ok') and c.get('targets', 0) > 0 for c in result['calls'])
    at = result.get('at_ms', 0)
    lines = []
    for f in Path(record_dir).rglob('unreal.log'):         # UE: game log lines after the entry marker
        text = f.read_text(errors='replace')
        if UE_BEGIN in text:           # recorder logs 'begin' before calling; the game logs during the call
            lines += text.split(UE_BEGIN, 1)[1].splitlines()
        elif UE_START in text:         # older recorder: lines of the same engine frame as the first call, onward
            before, after = text.split(UE_START, 1)
            head = before.splitlines()
            frame = re.match(r'\[[^\]]*\]\[\s*(\d+)\]', head[-1]) if head else None
            k = len(head)
            while frame and k > 0 and re.match(r'\[[^\]]*\]\[\s*' + frame.group(1) + r'\]', head[k - 1]):
                k -= 1
            lines += head[k:] + after.splitlines()
    for f in Path(record_dir).rglob('game_events.jsonl'):
        for raw in f.read_text(errors='replace').splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if (e.get('t_ms') or e.get('time_ms') or 0) >= at:
                lines.append(json.dumps(e, ensure_ascii=False))
    expect = entry.get('expect_events') or []
    seen = {x: any(x in l for l in lines) for x in expect}
    reached = calls_ok and all(seen.values()) if expect else ('unverified' if calls_ok else False)
    return {'version': VERSION, 'state_reached': reached, 'calls': result['calls'], 'expect_seen': seen,
            'events_after_entry': len(lines), 'applies_to': entry.get('applies_to', [])}
