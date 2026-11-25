"""Explicit original eight-column Gameness targets with staged native delivery.

Preserve every original criterion and group. The only added runtime field is a
transport/readability assertion; missing images remain a harness error. Static
reviews and the original result-oriented credit calculator stay unchanged.
"""
from __future__ import annotations
import copy
from . import gameness_v3_static as static_review, gameness_v3 as policy
from .codex import validate_schema

VERSION = 'gameness-original-eightcol-v1'
DELIVERY_NOTICE = """CURRENT RUNTIME DELIVERY: the source-only contract was frozen earlier, before this runtime judgment. Its runtime_evidence_supplied=false describes that EARLIER source-only stage, not this request. All predeclared real native frames are attached to THIS request as lossless native-size sheets, with a complete IMAGE MAP and author sources. Inspect the attached images. Return runtime_delivery_status=COMPLETE only when the supplied native images are actually visible and readable. If missing/unreadable, return MISSING_OR_UNREADABLE; this is HARNESS_ERROR, never an unobserved product result or zero. A visible frame that simply does not show a particular event is ordinary limited coverage, not a delivery failure. Preserve every original CHECKS identity and intent; do not pool several checks into a new one. A gameplay result/HUD label does not automatically establish its distinct event feedback; judge the intended communication for each original check under the frozen contract."""


def runtime_binding(frozen):
    return dict(stage='earlier_source_only_freeze', provenance={
        k:v for k,v in frozen.items() if k not in {'runtime_evidence_supplied','old_verdict_supplied'}})


def runtime_schema(specs, rules, manifest):
    value=copy.deepcopy(static_review.runtime_schema(specs,rules,manifest))
    value['properties']['runtime_delivery_status']={
        'type':'string','enum':['COMPLETE','MISSING_OR_UNREADABLE']}
    value['required'].append('runtime_delivery_status')
    return value


def evaluate(root, protocol, manifest, rules, contract, raw, specs, review, *, scoring_policy=policy):
    validate_schema(raw,runtime_schema(specs,rules,manifest))
    if raw['runtime_delivery_status']!='COMPLETE':
        raise ValueError('HARNESS_ERROR: original Gameness native images missing or unreadable')
    value=copy.deepcopy(raw)
    del value['runtime_delivery_status']
    return static_review.runtime_evaluate(root,protocol,manifest,rules,contract,value,specs,review,scoring_policy=scoring_policy)
