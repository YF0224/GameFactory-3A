"""Immutable Gameness v4 rubric manifest bound to all original scope sources."""
from pathlib import Path
from . import gameness_v4 as policy
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-original-checks.v4'
RELATIVE_PATH = 'rubrics/gameness_v4.json'
STANDARD = dict(
    version=VERSION, scoring_protocol=policy.VERSION, model=policy.MODEL,
    levels=[dict(credit=.1, requirement='Valid author implementation actually wired to gameplay'),
            dict(credit=.5, requirement='Actually triggered; correct object/core information, basic function normal, no known basic bug; result insufficient'),
            dict(credit=1., requirement='Delivered native result frame and minimum necessary context prove recognizable intended communication, correct object/information, no basic bug')],
    credit='Highest supported level, not additive; absent implementation may receive 0; harness errors are unscored',
    groups={g:dict(weight_numerator=1,weight_denominator=3,within_group='equal mean of ALL original checks') for g in policy.GROUPS},
    original_checks='Retain every original ID, requirement, group and meaning; no pooling, selection or new count quota',
    diagnostics_only=list(policy.DIAGNOSTIC),
    result_gate='Broad semantic correctness and usability; one clear native frame can suffice; minimum context only for actual ambiguity',
    basic_bugs=['wrong object','wrong/reversed core information','key text/control obscured beyond understanding or usability'],
    uncovered='Unknown coverage, not an observed product bug; source-only credit is not basic/runtime success',
    refusal='Operation must have been processed and correctly refused; unchanged screen alone is insufficient',
    preserved_columns='Gameness only; Mechanic and six other columns untouched; no eight-column total',
    prior_results='Old binary verdicts cannot be converted; only complete independent equivalent three-tier judgments may be revalidated with explicit migration lineage')


def build(inventory):
    from .gameness_v3_runtime import _original_source_protocol
    cases={};bindings={}
    for row in inventory['entries']:
        if not row['in_scope']:continue
        case=row['entry']['case_id'];protocol,bound=_original_source_protocol(row)
        checks=policy.criteria(protocol)
        if case in cases and cases[case]['criteria']!=checks:
            raise ValueError('Cross-model original Gameness rubric mismatch: '+case)
        cases.setdefault(case,dict(criteria=checks,check_count=len(checks),
            group_denominators={g:sum(s['group']==g for s in checks) for g in policy.GROUPS}))
        bindings.update(bound)
        frozen=Path(row['entry']['frozen_rubric']);bindings[str(frozen)]=sha(frozen)
    return dict(standard=STANDARD,scope_binding=inventory['full_scope_binding'],cases=cases,source_bindings=bindings)


def freeze(workspace,inventory):
    path=Path(workspace)/RELATIVE_PATH;value=build(inventory)
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Frozen Gameness v4 rubric differs')
    else:runner.exclusive_json(path,value)
    return dict(path=str(path),sha256=sha(path),version=VERSION)


def verify(workspace,inventory):
    revision=runner.read(Path(workspace)/'gameness_assessment_revision.json')
    binding=revision['original_rubric_manifest'];path=Path(binding['path'])
    if revision.get('gameness_rubric_policy')!='gameness-original-eightcol-v1':
        raise ValueError('Gameness v4 must preserve every original criterion')
    if path!=Path(workspace)/RELATIVE_PATH or sha(path)!=binding['sha256'] or runner.read(path)!=build(inventory):
        raise ValueError('Gameness v4 rubric/source binding changed')
    return runner.read(path)


def validate_protocol(workspace,case,protocol):
    revision=runner.read(Path(workspace)/'gameness_assessment_revision.json')
    bound=revision['original_rubric_manifest'];path=Path(bound['path'])
    if sha(path)!=bound['sha256']:raise ValueError('Gameness v4 rubric changed')
    rubric=runner.read(path)
    if policy.criteria(protocol)!=rubric['cases'][case]['criteria']:
        raise ValueError('Gameness v4 runtime changed original checks/requirements/groups')
