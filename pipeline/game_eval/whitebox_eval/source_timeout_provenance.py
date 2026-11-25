"""Exact legacy subprocess timeout proof when invocation and deadline clocks differ.

The pinned producer creates its outer deadline before packaging/CLI qualification,
then starts invocation.seconds immediately before launching the subprocess. Its
TimeoutExpired branch proves the outer deadline expired; comparing the shorter
subprocess elapsed time to the full allocation mistakes two clock origins.
"""
import ast
import math
import re
from pathlib import Path
from . import batch
from .protocol import dump,sha

RECEIPT='source_timeout_clock_provenance.json'
VERSION='whitebox-source-timeout-clock-provenance.v1'
LEGACY_PRODUCER_SHA='4b43fd8ee862c728dfd495e7558da232b07b7fdd75373d4b83e33e074d510db2'


def _proof(source,failure,producer):
    source=Path(source).resolve();failure=Path(failure).resolve();producer=Path(producer).resolve()
    if sha(producer)!=LEGACY_PRODUCER_SHA:raise ValueError('Unqualified legacy timeout producer')
    folder=source/'model_calls/source_code_scores';inv=batch.read(folder/'invocation.json');budget=batch.read(folder/'budget.json')
    error=batch.read(failure);trace=error.get('traceback','')
    match=re.search(r"subprocess\.TimeoutExpired: Command '(.+)' timed out after ([0-9.]+) seconds",trace)
    if not match or error.get('error')!='Codex timeout; see '+str(folder) or error.get('classification')!='HARNESS_ERROR':
        raise ValueError('No exact preserved subprocess timeout traceback')
    command=ast.literal_eval(match[1]);wait=float(match[2]);runtime=batch.read(folder/'cli_runtime.json')
    effective=budget.get('effective_timeout_seconds');allocated=budget.get('allocated_seconds');elapsed=inv.get('seconds')
    from .static_existence import MODEL
    if (set(inv)!={'model_requested','status','seconds'} or inv['status']!='TIMEOUT' or inv['model_requested']!=MODEL
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in (effective,allocated,elapsed,wait))
            or effective<300 or not 0<wait<=allocated<=effective or not wait<=inv['seconds']<effective
            or budget.get('attempt')!=1 or budget.get('phase')!='source_code_scores'
            or (folder/'response.json').exists() or (folder/'accepted_response.json').exists()
            or not isinstance(command,list) or not command or command[0]!=runtime.get('path') or len(runtime.get('sha256',''))!=64
            or 'proc.communicate(submitted_prompt, timeout=remaining)' not in trace
            or '--model' not in command or command[command.index('--model')+1]!=MODEL
            or '--sandbox' not in command or command[command.index('--sandbox')+1]!='read-only'
            or '-C' not in command or command[command.index('-C')+1]!=str(source/'input')
            or '--output-schema' not in command or command[command.index('--output-schema')+1]!=str(folder/'schema.json')
            or '-o' not in command or command[command.index('-o')+1]!=str(folder/'response.json') or command[-1]!='-'):
        raise ValueError('Legacy full outer-deadline timeout proof differs')
    return {'version':VERSION,'source_attempt':str(source),'failure_path':str(failure),'failure_sha256':sha(failure),
        'producer_path':str(producer),'producer_sha256':sha(producer),
        'source_bindings':{str(p.relative_to(source)):sha(p) for p in folder.iterdir() if p.is_file()},
        'physical_traceback_line':trace[:match.start()].count('\n')+1,
        'subprocess_timeout_seconds':wait,'subprocess_elapsed_seconds':inv['seconds'],
        'effective_timeout_seconds':effective,'allocated_before_packaging_seconds':allocated,
        'outer_deadline_exhausted':True,'budget_extended':False,
        'proof':'Pinned original producer TimeoutExpired from communicate(timeout=outer_deadline-now). Subprocess elapsed clock starts after preparation; status/traceback prove the unchanged outer deadline exhausted. No tolerance or score/reference threshold changed.'}


def prepare(source,failure,producer):
    source=Path(source).resolve()
    if (source/RECEIPT).exists():raise ValueError('Existing timeout clock proof retained')
    value=_proof(source,failure,producer);dump(source/RECEIPT,value);return verify(source)


def verify(source):
    source=Path(source).resolve();path=source/RECEIPT
    if not path.is_file():return False
    value=batch.read(path)
    expected=_proof(source,value['failure_path'],value['producer_path'])
    if value!=expected:raise ValueError('Legacy source timeout provenance changed')
    return True
