"""Report demonstrable capture gaps. Never repair the fact log."""
from collections import Counter, defaultdict
import hashlib
from ..core.artifact_store import ArtifactStore


def summarize_capture(trajectory, *, raw_journal_archived=False):
    """Production-monitoring summary of one finalized capture.

    Pairing completeness, raw-archive availability, request-boundary
    availability, verification presence and validator warning codes — a
    structured answer to "what exactly did this run capture", so a coarse
    capture_status no longer hides the details. Read-only; never repairs
    facts."""
    calls, results = defaultdict(int), defaultdict(int)
    for event in trajectory.get("events", []):
        for call in event.get("tool_calls") or []:
            calls[call.get("tool_call_id")] += 1
        if event.get("kind") == "tool_result":
            results[event.get("tool_call_id")] += 1
    unpaired = sorted(str(call_id) for call_id in calls if call_id not in results)
    orphans = sorted(str(call_id) for call_id in results if call_id not in calls)
    requests = trajectory.get("requests") or []
    if not requests:
        request_boundary = "unavailable"
    elif all(request.get("boundary") == "observed" for request in requests):
        request_boundary = "observed"
    elif any(request.get("boundary") for request in requests):
        request_boundary = "reconstructed"
    else:
        request_boundary = "unknown"
    from .validator import validate_trajectory
    report = validate_trajectory(trajectory)
    warnings = Counter(finding["code"] for finding in report["warnings"])
    tool_pairing_complete = not unpaired and not orphans
    # Fact capture, tool pairing, request-boundary availability and training
    # readiness are DIFFERENT facts: a complete fact capture with unavailable
    # request boundaries is not a failed run, and must not read as one.
    request_boundary_available = bool(requests)
    training_ready = (
        bool(requests)
        and all(request.get("boundary") == "observed"
                and request.get("context") == "complete" for request in requests)
        and (trajectory.get("training") or {}).get("status") == "ready")
    fact_capture_complete = (
        tool_pairing_complete and raw_journal_archived
        and bool(trajectory.get("events")))
    return {
        "tool_calls": sum(calls.values()),
        "tool_results": sum(results.values()),
        "unpaired_calls": len(unpaired),
        "orphan_results": len(orphans),
        "workspace_versions":
            len((trajectory.get("workspace") or {}).get("file_versions") or []),
        "raw_journal_archived": bool(raw_journal_archived),
        "request_boundary": request_boundary,
        "verification_count": len(trajectory.get("verification_refs") or []),
        "reasoning_events":
            sum(1 for e in trajectory.get("events", []) if e.get("raw_reasoning")),
        "warnings": dict(warnings),
        "fact_capture_complete": fact_capture_complete,
        "tool_pairing_complete": tool_pairing_complete,
        "request_boundary_available": request_boundary_available,
        "training_ready": training_ready,
    }


def audit_capture(trajectory, *, artifact_store=None, extra=()):
    findings=list(extra)
    def add(code,**kw): findings.append({'code':code,**kw})
    calls=defaultdict(list)
    results=defaultdict(list)
    inputs={x for r in trajectory.get('requests',[]) for x in r.get('input_event_ids',[])}
    definitions={x.get('name') for x in trajectory.get('tools',[])}
    store=artifact_store or ArtifactStore()
    checked=set()
    def attachment(block):
        uri=block.get('uri')
        if not uri or uri in checked: return
        checked.add(uri)
        try:
            data=store.get(uri)
            if not block.get('sha256') or hashlib.sha256(data).hexdigest()!=block['sha256']:
                add('attachment_unrecoverable',uri=uri,reason='missing_or_mismatched_hash')
        except (OSError,ValueError): add('attachment_unrecoverable',uri=uri,reason='unreadable')
    for e in trajectory.get('events',[]):
        if e.get('audit_code'): add(e['audit_code'],event_id=e['event_id'])
        if e.get('normalized') is False: add('unnormalized_raw_event',event_id=e['event_id'])
        for call in e.get('tool_calls',[]):
            calls[call.get('tool_call_id')].append((e,call))
            if call.get('name') not in definitions: add('tool_definition_missing',tool_call_id=call.get('tool_call_id'),name=call.get('name'))
        if e['kind']=='tool_result': results[e.get('tool_call_id')].append(e)
        for b in e.get('content',[]):
            if b.get('visibility')=='agent_received' and e['event_id'] not in inputs:
                add('unproven_agent_received',event_id=e['event_id'])
            attachment(b)
    for cid,entries in calls.items():
        if len(entries)>1:
            add('duplicate_call_id' if all(c==entries[0][1] for _,c in entries) else 'conflicting_call_id',tool_call_id=cid)
        if cid not in results: add('call_without_result',tool_call_id=cid)
    for cid in results:
        if cid not in calls: add('result_without_call',tool_call_id=cid)
    if not trajectory.get('requests'): add('request_context_missing')
    for ref in trajectory.get('verification_refs',[]):
        if not ref.get('state_ref'): add('verification_state_missing',event_id=ref.get('verification_event_id'))
    for b in trajectory.get('attachments',[]): attachment(b)
    for version in trajectory.get('workspace',{}).get('file_versions',[]):
        if version.get('operation')!='delete' and not version.get('uri'):
            add('attachment_unrecoverable',version_id=version.get('version_id'),reason='no_content_backup')
        attachment(version)
    return {'complete':not findings,'findings':findings,'counts':{'calls':sum(map(len,calls.values())),
            'results':sum(map(len,results.values())),'events':len(trajectory.get('events',[]))}}
