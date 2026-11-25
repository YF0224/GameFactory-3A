"""Gameness v4: every original check, original group weights, 10/50/100.

This is the versioned name of the original-check outcome-frame trial. Credit,
references and evidence gates share the accepted calculator; no score target
or comparison score is available to the judge.
"""
from . import gameness_v3 as shared

VERSION = 'whitebox-gameness10-50-100.v4'
REVISION = shared.REVISION
COLUMN = shared.COLUMN
GROUPS = shared.GROUPS
MODEL = shared.MODEL
SOURCE_SUFFIXES = shared.SOURCE_SUFFIXES
DIAGNOSTIC = shared.DIAGNOSTIC
references = shared.references
CONTRACT_PROMPT = shared.CONTRACT_PROMPT.replace('Gameness v3', 'Gameness v4')
# Keep the v4 runtime request self-identifying while preserving the frozen
# original-check policy and all shared scoring/schema behavior.
INSTRUCTION = shared.INSTRUCTION.replace('Gameness v3', 'Gameness v4')


def criteria(protocol):
    if 'gameness_rubric' in protocol:
        raise ValueError('Gameness v4 preserves all original checks; reduced rubrics are ineligible')
    return shared.criteria(protocol)


def contract_schema(protocol):
    criteria(protocol)
    return shared.contract_schema(protocol, scoring_version=VERSION)


def validate_contract(protocol, value):
    criteria(protocol)
    return shared.validate_contract(protocol, value, scoring_version=VERSION)


judgment_schema = shared.judgment_schema
inspect_references = shared.inspect_references
def evaluate(root, protocol, manifest, rules, contract, raw, specs):
    criteria(protocol)
    return shared.evaluate(root, protocol, manifest, rules, contract, raw, specs,
                           scoring_version=VERSION)



def aggregate(protocol, checks):
    criteria(protocol)
    return shared.aggregate(protocol, checks, scoring_version=VERSION)
