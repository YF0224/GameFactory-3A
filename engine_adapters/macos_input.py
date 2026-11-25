"""Shared real macOS keyboard-edge transport for existing engine clients.

Quartz posts hardware key edges to the already-foregrounded engine PID. It
never calls game APIs. In particular, nonprinting keys must not be sent as
complete taps on both down and up (which toggles menus twice).
"""
from __future__ import annotations

import time

KEYCODES = {
    'a':0,'s':1,'d':2,'f':3,'h':4,'g':5,'z':6,'x':7,'c':8,'v':9,'b':11,
    'q':12,'w':13,'e':14,'r':15,'y':16,'t':17,'1':18,'2':19,'3':20,'4':21,
    '6':22,'5':23,'9':25,'7':26,'8':28,'0':29,'o':31,'u':32,'i':34,'p':35,
    'j':38,'k':40,'l':37,'n':45,'m':46,'space':49,'enter':36,'return':36,
    'escape':53,'leftshift':56,'left_arrow':123,'right_arrow':124,
    'down_arrow':125,'up_arrow':126,'tab':48,
}


def _mouse_button(button: str):
    """Return the Quartz mouse-button constant for a portable button name."""
    import Quartz

    value = str(button).strip().lower()
    if value in {'left', 'lmb'}:
        return Quartz.kCGMouseButtonLeft
    if value in {'right', 'rmb'}:
        return Quartz.kCGMouseButtonRight
    raise ValueError(f'unsupported mouse button: {button}')


def _window_bounds(process_id: int):
    """Find the frontmost on-screen window bounds owned by ``process_id``."""
    import Quartz

    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    ) or []
    candidates = []
    for window in windows:
        if int(window.get(Quartz.kCGWindowOwnerPID, -1)) != int(process_id):
            continue
        bounds = window.get(Quartz.kCGWindowBounds) or {}
        try:
            x = float(bounds['X'])
            y = float(bounds['Y'])
            width = float(bounds['Width'])
            height = float(bounds['Height'])
        except (KeyError, TypeError, ValueError):
            continue
        if width > 1 and height > 1:
            candidates.append((x, y, width, height))
    if not candidates:
        return None
    # Prefer the largest visible window, which avoids targeting a small log
    # window when the editor/game owns more than one window.
    return max(candidates, key=lambda item: item[2] * item[3])


def post_mouse_edge(
    process_id: int,
    x: float,
    y: float,
    button: str = 'left',
    phase: str = 'click',
    *, screen_rect=None, foreground: bool = False,
):
    """Post a normalized-coordinate mouse event to an existing process PID.

    ``x`` and ``y`` are relative to the target window's visible bounds. The
    helper resolves those bounds at send time so plans remain portable across
    window positions and sizes.
    """
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return False, 'mouse coordinates must be numeric'
    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        return False, f'mouse coordinates out of range: {x}/{y}'
    if phase not in {'move', 'drag', 'down', 'up', 'click'}:
        return False, f'unsupported macOS mouse phase: {phase}'
    try:
        import Quartz
        if hasattr(Quartz, 'CGPreflightPostEventAccess') and not Quartz.CGPreflightPostEventAccess():
            return False, 'macOS input posting access unavailable'
        bounds = screen_rect if screen_rect is not None else _window_bounds(process_id)
        if bounds is None:
            return False, f'no visible window bounds found for process {process_id}'
        window_x, window_y, width, height = bounds
        point = Quartz.CGPoint(
            window_x + x * (width - 1),
            window_y + y * (height - 1),
        )
        mouse_button = _mouse_button(button)
        if phase == 'move':
            event_types = [(Quartz.kCGEventMouseMoved, mouse_button)]
        elif phase == 'drag':
            event_types = [(Quartz.kCGEventLeftMouseDragged if mouse_button == Quartz.kCGMouseButtonLeft else Quartz.kCGEventRightMouseDragged, mouse_button)]
        elif phase == 'down':
            event_types = [(Quartz.kCGEventLeftMouseDown if mouse_button == Quartz.kCGMouseButtonLeft else Quartz.kCGEventRightMouseDown, mouse_button)]
        elif phase == 'up':
            event_types = [(Quartz.kCGEventLeftMouseUp if mouse_button == Quartz.kCGMouseButtonLeft else Quartz.kCGEventRightMouseUp, mouse_button)]
        else:
            down_type = Quartz.kCGEventLeftMouseDown if mouse_button == Quartz.kCGMouseButtonLeft else Quartz.kCGEventRightMouseDown
            up_type = Quartz.kCGEventLeftMouseUp if mouse_button == Quartz.kCGMouseButtonLeft else Quartz.kCGEventRightMouseUp
            event_types = [(down_type, mouse_button), (up_type, mouse_button)]
        for event_type, event_button in event_types:
            event = Quartz.CGEventCreateMouseEvent(None, event_type, point, event_button)
            if event is None:
                return False, 'CGEventCreateMouseEvent returned null'
            if phase in {'down', 'up', 'click'}:
                Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)
            if foreground:
                # Legacy Unity reads the desktop pointer position. PID-only
                # mouse events deliver buttons but leave that pointer unchanged.
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            else:
                Quartz.CGEventPostToPid(int(process_id), event)
            if phase == 'click' and event_type == event_types[0][0]:
                time.sleep(.08)
        return True, ''
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'


def post_key_edge(process_id: int, key: str, phase: str):
    """Return delivery-attempt result, never a game-response verdict."""
    if key not in KEYCODES or phase not in {'down','up','tap'}:
        return False, f'unsupported macOS physical input: {key}/{phase}'
    try:
        import Quartz
        if hasattr(Quartz,'CGPreflightPostEventAccess') and not Quartz.CGPreflightPostEventAccess():
            return False, 'macOS input posting access unavailable'
        for down in ([True,False] if phase=='tap' else [phase=='down']):
            event=Quartz.CGEventCreateKeyboardEvent(None,KEYCODES[key],down)
            if event is None:return False,'CGEventCreateKeyboardEvent returned null'
            Quartz.CGEventPostToPid(int(process_id),event)
            if phase=='tap' and down:time.sleep(.08)
        return True,''
    except Exception as exc:
        return False,f'{type(exc).__name__}: {exc}'
