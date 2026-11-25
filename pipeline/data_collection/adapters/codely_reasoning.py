"""Lossless presentation of Codely's observed reasoning, not model input.

Two sources, two reconstructions:
- wire strings (stream deltas) stay verbatim: the stream carries its own
  whitespace, so inserting anything would fabricate text.
- UI ``thoughts`` segments (journal/autosave) are word-boundary joined:
  the CLI stores each description as a display segment with its boundary
  whitespace dropped (verified on real sessions: word-separating spaces are
  missing at every boundary while spaces inside a segment are intact), so
  the faithful reconstruction inserts one space at word boundaries — but
  never before closing punctuation, after opening punctuation, or between
  two CJK characters, where no space can have existed.

Raw segment arrays are NOT embedded: the raw source (journal/autosave) is
archived with sha256 and every event carries source_refs, so the originals
stay recoverable from the source instead of being duplicated per event.
Unknown segment shapes are still detected and mark the text reconstruction
as incomplete.
"""
from __future__ import annotations

_CLOSERS = ",.;:!?)]}\"'…、,。!?:;·》〉」』`_"
_OPENERS = "([{\"'《〈「『_"


def _is_cjk(ch):
    return ('\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f'
            or '\uff00' <= ch <= '\uffef')


def _needs_space(prev_tail, nxt):
    if not nxt:
        return False
    prev = prev_tail[-1] if prev_tail else ""
    before = prev_tail[-2] if len(prev_tail) >= 2 else ""
    if not prev:
        return False
    if prev.isspace() or nxt[0].isspace():
        return False
    if nxt[0] in _CLOSERS or prev in _OPENERS:
        return False
    if _is_cjk(prev) and _is_cjk(nxt[0]):
        return False
    # A backtick ending a segment after whitespace opens a code span whose
    # text continues in the next segment; after a word character it closes
    # one, and the following word keeps its separating space.
    if prev == "`" and (not before or before.isspace()):
        return False
    return True


def reasoning_record(thoughts):
    if isinstance(thoughts, str):
        return {"visibility": "collector_only", "content": thoughts,
                "policy": "retained_restricted_not_training_input"}
    fragments = []
    complete = isinstance(thoughts, list)
    for segment in thoughts if isinstance(thoughts, list) else []:
        if isinstance(segment, str):
            fragments.append(segment)
        elif isinstance(segment, dict) and isinstance(segment.get("description"), str):
            fragments.append(segment["description"])
        else:
            complete = False
    content = ""
    for fragment in fragments:
        if content and _needs_space(content, fragment):
            content += " "
        content += fragment
    return {"visibility": "collector_only", "content": content,
            "text_reconstruction": "description_segments_space_joined",
            "text_reconstruction_complete": complete,
            "policy": "retained_restricted_not_training_input"}
