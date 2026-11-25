"""Persist an actual Astra source review before any paired native recording."""

from ..model_config import PLANNER_MODEL
from pathlib import Path

from . import llm
from .paths import read_profiles
from .paths import read_json, write_json, sha256

PROTOCOL = 'stage1-dual-client.75s.v3'
DURATION_S = 75
SCHEMA = llm.obj({
    'duration_s': {'type':'integer','enum':[75]},
    'entry_supported': llm.B,
    'entry_review': llm.S,
    'replication_review': llm.S,
    'product_limitations': llm.arr(llm.S),
    'source_references': llm.arr(llm.obj({'path':llm.S,'line':{'type':'integer','minimum':1},'finding':llm.S}), minItems=3),
    'actions': llm.arr(llm.obj({'role':llm.enum('host','client'), 'key':llm.enum('W','A','S','D'),
                              'duration_s':{'type':'number','minimum':.6,'maximum':1.0},
                              'wait_s':{'type':'number','minimum':.6,'maximum':1.2},
                              'purpose':llm.S}), minItems=4,maxItems=6),
})


def make_plan(project, take_dir, *, profile, model, requirement, feedback=None):
    project, take_dir = Path(project).resolve(), Path(take_dir).resolve()
    if model != PLANNER_MODEL:
        raise llm.HarnessError(f'paired playable requires the requested {PLANNER_MODEL} source review; no substitution')
    requirement = Path(requirement).resolve()
    requirement_sha = sha256(requirement)
    reviewed = read_profiles(Path(__file__).with_name('dual_client_profiles.json'), reader=read_json)[profile]
    hashes = {name:sha256(project/name) for name in reviewed['reviewed_sha256']}
    if hashes != reviewed['reviewed_sha256']:
        raise llm.HarnessError('source review profile hashes changed')
    def validate(result):
        llm.validate_schema(result, SCHEMA)
        for ref in result['source_references']:
            if ref['path'] not in hashes or ref['line'] > len((project/ref['path']).read_text().splitlines()):
                raise ValueError('source reference must name an actual reviewed source line')
        for role in ('host','client'):
            keys = {a['key'] for a in result['actions'] if a['role'] == role}
            if not ({'D','A'} <= keys or {'W','S'} <= keys):
                raise ValueError('each role needs opposite movement directions to distinguish input from drift')
    path = take_dir/'plan.json'
    if path.exists():
        plan = read_json(path)
        if plan.get('protocol') != PROTOCOL or plan.get('source_sha256') != hashes or plan.get('planner') != model or plan.get('feedback') != feedback or plan.get('requirement_sha256') != requirement_sha:
            raise llm.HarnessError('existing pair plan binding differs; preserve it')
        response = llm.accepted_response(take_dir/'model_calls','source_review')
        if response != plan['review']:
            raise llm.HarnessError('plan does not match accepted Astra response')
        validate(response)
        return plan
    # Include full pinned source and the exact formal entry routine, not guessed controls.
    module = Path(__file__).with_name('dual_client.py').read_text()
    entry = module.split('def _enter(',1)[1].split('\ndef record_pair',1)[0]
    source = '\n\n'.join(f'FILE {name}\n'+'\n'.join(f'{i}: {line}' for i,line in enumerate((project/name).read_text().splitlines(),1)) for name in hashes)
    prompt = f'''Review the actual original Godot G043 source for a real two-process playable take.
Profile: {profile}. Both viewports record for exactly 75 seconds from scene boot.
Confirm the supplied formal native UI host/join/ready entry against source, identify the shared session,
peer identity and replication fields, and document product limitations. No game editing, bots, OS input,
RPC/game function calls, or state changes. Input is native Input.parse_input_event only.
Return 4-6 isolated movement inputs, BOTH directions for EACH role, .6-1s holds and .6-1.2s waits.
An additional 1.8s idle precedes each movement. The other role stays idle. Prefer D,A if source supports it.
This is source review, not runtime proof; do not claim observed success. Missing manual ready path must
be reported as a product limitation; still plan safe native movement probes. Do not invent a workaround.
For take two use the prior evidence feedback to improve native input coverage without changing the rules.
Feedback: {feedback!r}
Exact formal entry routine (review only):\ndef _enter({entry}
Original case requirement (same selection as prepare: SAMPLES/game_id/general_requirement.txt):\n{requirement.read_text()}\nFull original source follows:\n{source}
'''
    calls = take_dir/'model_calls'
    response = llm.accepted_response(calls,'source_review')
    if response is None:
        if calls.exists() and any(calls.iterdir()):
            raise llm.HarnessError('prior unaccepted source review preserved; explicit recovery required')
        response = llm.call_model(calls,name='source_review',prompt=prompt,schema=SCHEMA,cwd=project,
                                  model=model,timeout=480,validator=validate,read_dirs=[project])
    validate(response)
    plan = {'protocol':PROTOCOL,'planner':model,'duration_s':DURATION_S,'required_real_clients':2,
            'profile':profile,'requirement_sha256':requirement_sha,'source_sha256':hashes,'feedback':feedback,'review':response,
            'accepted_response_receipt':'model_calls/source_review/accepted_response.json',
            'accepted_response_sha256':sha256(calls/'source_review/accepted_response.json'),
            'entry_transport':'authored UI through Input.parse_input_event; source-reviewed formal _enter',
            'observer_sha256':sha256(Path(__file__).with_name('dual_client_observer.gd'))}
    write_json(path,plan)
    return plan
