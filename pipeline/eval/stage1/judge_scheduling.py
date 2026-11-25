"""Bound judge dispatch so a failed shard cannot launch the remaining model queue."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


def bounded_map(function, tasks, *, max_workers=2, on_failure=None):
    """Return original task order; drain admitted work and stop admitting after failure.

    Worker exceptions stay intact. A failing batch never yields a partial aggregate.
    Already-running tasks finish and retain their own persisted accepted responses.
    """
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError('Judge concurrency must be a positive integer')
    tasks=list(tasks);outputs=[None]*len(tasks);next_index=0;failures=[]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending={}
        def submit():
            nonlocal next_index
            index=next_index;next_index+=1
            pending[pool.submit(function,tasks[index])]=index
        while next_index < min(max_workers,len(tasks)):submit()
        while pending:
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in sorted(done,key=lambda f:pending[f]):
                index=pending.pop(future)
                try:outputs[index]=future.result()
                except BaseException as error:failures.append((index,error,error.__traceback__))
            if failures:
                # No new submissions. Persisted successful responses are reusable.
                continue
            while len(pending)<max_workers and next_index<len(tasks):submit()
    if failures:
        index,error,traceback=min(failures,key=lambda value:value[0])
        if on_failure is not None:
            on_failure({'submitted_indices':list(range(next_index)),
                        'completed_indices':[i for i in range(next_index) if i not in {f[0] for f in failures}],
                        'failed_indices':sorted(f[0] for f in failures),
                        'not_submitted_indices':list(range(next_index,len(tasks))),
                        'selected_failure_index':index,
                        'failures':[{'index':i,'type':type(e).__name__,'error':str(e)} for i,e,_ in sorted(failures)],
                        'scoring_semantics_changed':False,
                        'partial_aggregate_produced':False})
        raise error.with_traceback(traceback)
    return outputs
