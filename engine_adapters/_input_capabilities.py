"""Physical input vocabulary shared by target planners, gates and translators.

These capabilities apply only to the Godot and Three.js bounded protocol.
"""
import re

VERSION = 'whitebox-input-capabilities.v2.godot-threejs'
TARGET_ENGINES = frozenset({'godot', 'three_js'})
MAX_PROBES = 24
MAX_STEPS = 96
MAX_STEP_MS = 30000
MAX_WATCHERS = 32

CANONICAL_KEYS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') | {
    'Enter', 'Escape', 'Space', 'Tab', 'Shift', 'Ctrl', 'Alt',
    'Left', 'Right', 'Up', 'Down', 'Backspace', 'Delete', 'Insert',
    'Home', 'End', 'PageUp', 'PageDown',
} | {f'F{i}' for i in range(1, 13)}
KEY_ALIASES = {key.lower(): key for key in CANONICAL_KEYS}
KEY_ALIASES.update({'return': 'Enter', 'esc': 'Escape', 'spacebar': 'Space',
    'control': 'Ctrl', 'controlleft': 'Ctrl', 'controlright': 'Ctrl',
    'shiftleft': 'Shift', 'shiftright': 'Shift', 'altleft': 'Alt', 'altright': 'Alt',
    'leftshift': 'Shift', 'leftctrl': 'Ctrl', 'leftalt': 'Alt',
    'pgup': 'PageUp', 'pgdn': 'PageDown', 'del': 'Delete', 'ins': 'Insert'})
for direction in ('Left', 'Right', 'Up', 'Down'):
    KEY_ALIASES['arrow' + direction.lower()] = direction
    KEY_ALIASES[direction.lower() + '_arrow'] = direction
for key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ': KEY_ALIASES['key' + key.lower()] = key
for key in '0123456789': KEY_ALIASES['digit' + key] = key
GODOT_MOUSE_KEYS = {'lmb': 'LMB', 'rmb': 'RMB', 'mmb': 'MMB'}

def canonical_key(key, *, mouse=False):
    if not isinstance(key, str) or not key or key != key.strip():
        raise ValueError('empty or malformed physical key')
    canonical = KEY_ALIASES.get(key.lower())
    if canonical is None and mouse: canonical = GODOT_MOUSE_KEYS.get(key.lower())
    if canonical is None: raise ValueError(f'unsupported physical key: {key!r}')
    return canonical

def canonical_chord(value, *, mouse=False):
    if not isinstance(value, str): raise ValueError('physical chord must be a string')
    keys = [canonical_key(key, mouse=mouse) for key in value.split('+')]
    if not 1 <= len(keys) <= 3 or len(set(keys)) != len(keys):
        raise ValueError('physical chord needs 1..3 distinct keys')
    return keys

def key_pattern(*, mouse=False):
    # Explicit character classes work in both Python JSON Schema and JS regex.
    tokens = set(KEY_ALIASES) | (set(GODOT_MOUSE_KEYS) if mouse else set())
    expressions = [''.join('['+c.lower()+c.upper()+']' if c.isalpha() else re.escape(c)
                           for c in token) for token in sorted(tokens)]
    token = '(?:' + '|'.join(expressions) + ')'
    return '^' + token + '(?:\\+' + token + '){0,2}$'

BROWSER_CODES = {key: key for key in CANONICAL_KEYS}
BROWSER_CODES.update({key: 'Key'+key for key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'})
BROWSER_CODES.update({key: 'Digit'+key for key in '0123456789'})
BROWSER_CODES.update({key: 'Arrow'+key for key in ('Left','Right','Up','Down')})
BROWSER_CODES.update(Shift='ShiftLeft', Ctrl='ControlLeft', Alt='AltLeft')

def browser_code(key):
    return BROWSER_CODES[canonical_key(key)]

def capability_record(engine):
    if engine not in TARGET_ENGINES: raise ValueError('target input capability only')
    from ._mouse_plan import MOUSE_KINDS
    return {'version': VERSION, 'engine': engine, 'max_probes': MAX_PROBES,
            'max_steps_per_probe': MAX_STEPS, 'max_step_ms': MAX_STEP_MS,
            'watchers': 'typed_numeric_bool_vector' if engine == 'godot' else 'unavailable',
            'keys': sorted(CANONICAL_KEYS | (set(GODOT_MOUSE_KEYS.values()) if engine == 'godot' else set())),
            'aliases': KEY_ALIASES, 'mouse_kinds': sorted(MOUSE_KINDS),
            'mouse_duration_ms': [100, 6000], 'coordinates': 'viewport_fraction_0_1'}
