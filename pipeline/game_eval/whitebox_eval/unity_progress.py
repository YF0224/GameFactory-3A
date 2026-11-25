"""Refresh execution progress without changing original delivery inventory entries."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import fcntl
import math

from .protocol import dump, sha


def table_scores(batch):
    result = {}
    path = Path(batch)/'scores.md'
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        cells = [value.strip() for value in line.strip().strip('|').split('|')]
        if len(cells) < 11 or ' / ' not in cells[0]:
            continue
        model, case = cells[0].split(' / ', 1)
        if not case.startswith('G') or len(case) != 4:
            continue
        try:
            score = float(cells[9])
        except ValueError:
            continue
        if math.isfinite(score) and 0 <= score <= 100:
            result[(model,case)] = (score,cells[-1])
    return result


def refresh(batch, queue, *, mirror=None):
    from . import batch as files
    batch, queue = Path(batch), Path(queue)
    with (batch/'.unity_progress.lock').open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        inventory = files.read(batch/'inventory.json')
        state = files.read(queue/'queue_state.json')
        if mirror is None and (queue/'unity_progress_configuration.json').is_file():
            mirror = files.read(queue/'unity_progress_configuration.json').get('mirror')
        rows = [row for row in inventory['entries'] if row.get('actual_engine') == 'unity3d']
        scores = table_scores(batch)
        pending_path = batch/'pending_audits.json'
        audit_entries = files.read(pending_path).get('entries', {}) if pending_path.is_file() else {}
        progress = inventory.get('unity_execution_progress', {})
        updated = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
        counts, entries = {}, {}
        for row in rows:
            case = state.get('cases', {}).get(row['id'], {})
            score, label = scores.get((row['method'],row.get('case_id',row['id'].split('__',1)[1])[:4]), (None,None))
            item = dict(progress.get('entries', {}).get(row['id'], {}))
            item.update(score_in_table=score, score_status=label,
                queue_status=case.get('status','DEFERRED_MODEL' if row['method'] not in state.get('models',[]) else 'PENDING'),
                phase=case.get('phase'), attempt=case.get('attempt') or case.get('recorded_attempt'),
                judge_attempt=case.get('judge_attempt'), failure_class=case.get('failure_class'),
                reason=case.get('error') or case.get('reason'),
                launchability=item.get('launchability','NOT_REVALIDATED_BY_HANDOFF'))
            item['audit_status'] = ('PENDING' if label and 'SCORED_PENDING_AUDIT' in label
                else case.get('audit_status', item.get('audit_status')))
            audited = audit_entries.get(row['id'], {})
            if (label and 'SCORED_PENDING_AUDIT' not in label
                    and audited.get('status') == 'AUDITED' and audited.get('audit_status') == 'PASSED'):
                audit_path = batch/audited['attempt']/'formal_publication_audit.json'
                item['audit_status'] = ('PASSED' if audit_path.is_file()
                    and sha(audit_path) == audited.get('audit_sha256')
                    and files.read(audit_path).get('valid') is True else 'AUDIT_SOURCE_MISMATCH')

            item['cleanup'] = case.get('cleanup')
            if item['attempt'] and (Path(item['attempt'])/'background_record/verification.json').is_file():
                capture = Path(item['attempt'])/'background_record'
                verification = files.read(capture/'verification.json')
                item['launchability'] = 'NATIVE_CAPTURE_RECEIPT_SAVED'
                item['capture_frames'] = verification.get('frames')
                item['capture_cleanup'] = {key:verification.get('checks', {}).get(key)
                    for key in ('input_cleanup','view_cleanup','process_cleanup')}
                exit_path = capture/'runner_exit.json'
                item['capture_cleanup_verified'] = files.read(exit_path).get('cleanup_verified') if exit_path.is_file() else None
                item['capture_verification'] = {'path':str(capture/'verification.json'),
                    'sha256':sha(capture/'verification.json')}
            else:
                for key in ('capture_frames','capture_cleanup','capture_cleanup_verified','capture_verification'):
                    item.pop(key, None)
            entries[row['id']] = item
            group = counts.setdefault(row['method'], {'total':0,'scored':0,'unscored':0})
            group['total'] += 1
            group['scored' if score is not None else 'unscored'] += 1
        progress.update(updated_at=updated, queue=str(queue.resolve()), pid_snapshot=state.get('pid'),
            queue_status=state.get('status'), queue_state_sha256=sha(queue/'queue_state.json'),
            counts=counts, entries=entries,
            note='Execution snapshot only; original delivery entries preserved. Table counts do not establish launchability.')
        inventory['unity_execution_progress'] = progress
        dump(batch/'inventory.json',inventory)
        if mirror:
            path = Path(mirror)
            doc = files.read(path) if path.is_file() else {'version':'whitebox-unity-night-handoff.v1'}
            old = {row['id']:row for row in doc.get('entries',[])}
            doc.update(updated_at=updated,batch=str(batch.resolve()),current_queue=str(queue.resolve()),
                current_queue_pid_snapshot=state.get('pid'),current_queue_status=state.get('status'),
                current_queue_counts=dict(Counter(row['status'] for row in state.get('cases',{}).values())),
                counts=counts,total=len(rows),scored=sum(v['scored'] for v in counts.values()),
                unscored=sum(v['unscored'] for v in counts.values()))
            doc['entries'] = [{**old.get(row['id'], {}), **{key:row.get(key) for key in
                ('id','method','case_id','project','required_real_clients')}, **entries[row['id']]} for row in rows]
            doc.setdefault('source_sha256',{}).update({str(batch/'inventory.json'):sha(batch/'inventory.json'),
                str(queue/'queue_state.json'):sha(queue/'queue_state.json'),str(batch/'scores.md'):sha(batch/'scores.md')})
            dump(path,doc)
        return {'updated_at':updated, 'counts':counts, 'queue_status':state.get('status')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--mirror',type=Path)
    args = parser.parse_args(argv)
    print(refresh(args.batch,args.queue,mirror=args.mirror))


if __name__ == '__main__':
    main()
