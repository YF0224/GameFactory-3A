"""Episode lifecycle + runtime capture + single canonical Writer.

Execution stays in the existing AgentToolBridge/Dispatcher/engine clients.
Raw files are archival streams, never a second canonical trajectory schema.
"""
from __future__ import annotations
from contextlib import nullcontext
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from ..adapters import SUPPORTED_AGENTS, AgentAdapter, AgentProcess, default_normalizer, get_adapter
from ..adapters.codely_journal import (attempt_run_recovery, harvest_exit_tools,
                                        session_id_from_raw_stream)
from ..adapters.codex_session import (attempt_codex_run_recovery,
                                      harvest_rollout_layer)
from ..adapters.claude_code import (attempt_claude_run_recovery,
                                     harvest_claude_session_layer)


from ..core.collector import Collector, add_identity_arguments, identity_metadata
from ..core.collector_sink import CollectorSink
from ..core.artifact_store import ArtifactStore
from pipeline.common.paths import REPO_ROOT
from ..core.event_writer import atomic_write_json, now_iso
from ..core.telemetry import TelemetryWriter
from ..tools.harness_adapter import redact
from ..tools.dispatch_context import CaptureError
from .live_assembler import LiveAssembler
from .environment import capture_environment
from .verification_observer import apply_declared_verification_rules, parse_verification_rules
from ..quality.capture_audit import audit_capture
from .observation_spool import SpoolReader, ENV_SPOOL, ENV_TRAJECTORY, ENV_BLOBS
from ..core.workspace_tracker import WorkspaceObserver


# Secret value patterns shared by both redaction paths. Applied to plain text
# (stderr / non-JSON lines) directly, and to the *inside of each string* for
# parsed JSON — never to a serialized JSON document, where ``[^\s,;]+`` can
# swallow quotes/braces and destroy the line.
_SECRET_VALUE_PATTERNS = (
    re.compile(r'(?i)(Bearer\s+)[\w.\-]+'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{8,}'),
    re.compile(r'(?i)((?:api[_-]?key|access_token|password|authorization)\s*[=:]\s*)[^\s,;]+'),
)


def _redact_text(text):
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) + '[REDACTED]') if (m.lastindex and m.group(1)) else '[REDACTED]', text)
    return text


def _redact_json_strings(value):
    """Apply the secret patterns inside every string of a parsed JSON value."""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_json_strings(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_json_strings(v) for v in value]
    return value


class LiveTrajectoryCollector:
    """Archive complete records before normalization; flush partial tail on drain."""
    def __init__(self, collector, raw_path, provider, *, normalizer=None, assembler=None, workspace=None):
        self.collector=collector
        self.provider=provider
        self.raw_path=Path(raw_path)
        self.raw_path.parent.mkdir(parents=True,exist_ok=True)
        self._raw=self.raw_path.open('xb')
        self._stderr=self.raw_path.with_suffix('.stderr.log').open('xb')
        self.buffers={'stdout':b'','stderr':b''}
        self.normalizer=normalizer or default_normalizer(provider)
        self.assembler=assembler or LiveAssembler(collector)
        self.invalid_events=0
        self.raw_failures=[]
        self.failed=False
        self.workspace=str(Path(workspace).resolve()) if workspace else None
        self.raw_redacted=False
        self._closed=False

    def _sanitize(self, data):
        """Redact secrets without ever breaking the provider's line structure.

        Valid JSON lines are redacted structurally — keys via ``redact()``,
        string *values* via the secret patterns applied inside each string —
        and serialized once; text regexes never run over serialized JSON.
        Non-JSON lines (stderr, plain text, mid-write truncation) get the
        patterns applied as plain text.
        """
        text=data.decode('utf-8',errors='surrogateescape')
        try:
            document=json.loads(text)
        except ValueError:
            text=_redact_text(text)
        else:
            text=json.dumps(_redact_json_strings(redact(document)),ensure_ascii=False)+ ('\n' if data.endswith(b'\n') else '')
        if self.workspace: text=text.replace(self.workspace,'$WORKSPACE')
        text=text.replace(str(Path.home()),'$HOME')
        result=text.encode('utf-8',errors='surrogateescape')
        self.raw_redacted |= result!=data
        return result

    def _record(self,channel,line,*,partial=False):
        data=self._sanitize(line)
        stream=self._raw if channel=='stdout' else self._stderr
        try:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        except OSError as exc:
            self.raw_failures.append({'code':'raw_archive_failure','channel':channel,'error':str(exc)})
            raise CaptureError(str(exc)) from exc
        if channel!='stdout': return
        if partial:
            self.assembler.audit('partial_provider_line',provider=self.provider)
            return
        try:
            event=json.loads(data)
            if not isinstance(event,dict): raise ValueError('provider JSON is not an object')
        except (ValueError,UnicodeError) as exc:
            self.invalid_events+=1
            self.assembler.audit('invalid_json',missing_reason='invalid_json',error=str(exc),provider=self.provider)
            return
        if event.get('type') in {'turn.failed','error'} or (event.get('type')=='result' and (
                event.get('status')=='error' or (self.provider=='claude' and not event.get('parent_tool_use_id') and (
                    event.get('is_error') is True or str(event.get('subtype','')).startswith('error'))))):
            self.failed=True
        try:
            normalized=self.normalizer.normalize(event)
        except (ValueError,TypeError,KeyError) as exc:
            self.assembler.audit('unnormalized_raw_event',provider=self.provider,error=str(exc))
            return
        for observation in normalized:
            self.assembler.provider_event(observation)

    def feed(self,channel,data):
        if channel not in self.buffers:
            self.assembler.audit('provider_reader_failure',error=data.decode(errors='replace'));return
        buffer=self.buffers[channel]+data
        while b'\n' in buffer:
            line,buffer=buffer.split(b'\n',1)
            self._record(channel,line+b'\n')
        self.buffers[channel]=buffer

    def consume_line(self,line):
        # Compatibility API: caller supplies a complete runtime record.
        self.feed('stdout',(line if line.endswith('\n') else line+'\n').encode())

    def normalize(self,event):
        for observation in self.normalizer.normalize(event): self.assembler.provider_event(observation)

    def close(self):
        if self._closed: return
        self._closed=True
        try:
            for channel,tail in self.buffers.items():
                if tail: self._record(channel,tail,partial=True)
            self.buffers={'stdout':b'','stderr':b''}
            finish=getattr(self.normalizer,'finish',None)
            if finish:
                for observation in finish(): self.assembler.provider_event(observation)
        finally:
            self._raw.close(); self._stderr.close()


class AgentRunner:
    def __init__(self,adapter:AgentAdapter,*,timeout_seconds=3600,drain_seconds=1.0,watch_workspace=True,
                 observation_checkpoint_seconds=None,observer_max_files=10000,
                 include_project_symlink=False,startup_counts_toward_timeout=False):
        self.adapter=adapter
        self.timeout_seconds=timeout_seconds
        self.drain_seconds=drain_seconds
        self.watch_workspace=watch_workspace
        self.observation_checkpoint_seconds=observation_checkpoint_seconds
        self.observer_max_files=observer_max_files
        self.include_project_symlink=include_project_symlink
        self.startup_counts_toward_timeout=startup_counts_toward_timeout
        self._stop=threading.Event()
        self.last_report=None

    def request_stop(self): self._stop.set()

    def run(self,prompt,*,workspace,run_dir,metadata=None,env=None,prepare_workspace=None,
            trajectory_path=None,register=False,setup=None,artifact_store=None,
            engine=None,skip_environment=True,journal_root=None,
            autosave_dir=None,autosave_pattern='chat-auto-save-*.json',
            verification_rules=None):
        launch_deadline=time.monotonic()+self.timeout_seconds
        workspace,run_dir=Path(workspace).resolve(),Path(run_dir).resolve()
        run_dir.mkdir(parents=True,exist_ok=True)
        if (run_dir/'run_meta.json').exists(): raise FileExistsError('run directory already used')
        if prepare_workspace:
            src=Path(prepare_workspace).resolve()
            if workspace==src or workspace.is_relative_to(src):
                raise ValueError('isolated destination must not be inside the source workspace')
            if workspace.exists() and any(workspace.iterdir()):
                raise ValueError('prepared workspace must be empty')
            shutil.copytree(src,workspace,dirs_exist_ok=True,symlinks=True)
        workspace.mkdir(parents=True,exist_ok=True)
        md=dict(metadata or {})
        md.setdefault('game_id','live_agent');md.setdefault('run_id',run_dir.name)
        md.update(agent_provider=self.adapter.provider,started_at=now_iso())
        store=artifact_store or ArtifactStore()
        trajectory_path = trajectory_path or (run_dir/'trajectory.json')
        environment_ref = ({} if skip_environment else capture_environment(
            agent=self.adapter.provider, engine=engine,
            workspace=str(workspace), artifact_store=store))
        collector=Collector.start(md,environment_ref=environment_ref,
            path=trajectory_path,artifact_store=store,register=register,exclusive=True)
        path=collector.writer.path.resolve()
        # The launch prompt is the session's task statement (schema §6 task_ref)
        # and the companion inherits it from this live view.
        collector.trajectory['task_ref']={'source':'live_launch_prompt','prompt':prompt}
        if not getattr(self.adapter,'echoes_prompt',True):
            # codex exec's stream never echoes the launch prompt (verified
            # against the installed CLI): record the delivered task input
            # ourselves, or the live view loses its first turn. Stream-event
            # visibility policy applies (collector_only — the rollout-derived
            # companion carries the agent_received copy).
            collector.record_message('user',text=prompt,visibility='collector_only')
        else:
            collector.writer.checkpoint()
        sink=CollectorSink(collector)
        assembler=LiveAssembler(sink)
        spool_dir=run_dir/'raw'/'observations'; spool_dir.mkdir(parents=True,exist_ok=True)
        spool=SpoolReader(spool_dir,assembler,run_dir/'spool_positions.json')
        child_env={**os.environ,**(env or {}),ENV_SPOOL:str(spool_dir),ENV_TRAJECTORY:str(path),ENV_BLOBS:str(store.root.resolve())}
        repo=str(REPO_ROOT)
        child_env['PYTHONPATH']=os.pathsep.join(filter(None,(repo,child_env.get('PYTHONPATH'))))
        state={**md,'trajectory_path':str(path),'workspace':str(workspace),
               'autosave_dir':str(autosave_dir) if autosave_dir else None,
               'autosave_pattern':autosave_pattern,
               'register':register,
               'capabilities':self.adapter.capabilities(),'raw_policy':'redacted_runtime_archive'}
        stream=None;handle=None;observer=None
        result={'status':'runner_error','ok':False}
        extras=[]
        observer_failed=False
        project_observer=None
        next_observation=0.0
        def observe(force=False, final=False):
            nonlocal next_observation,observer_failed
            spool.poll()
            if observer and not observer_failed and (force or time.monotonic()>=next_observation):
                try:
                    batch=(collector.writer.coalesce_checkpoints(self.observation_checkpoint_seconds)
                           if self.observation_checkpoint_seconds is not None else nullcontext())
                    with batch:
                        observer.poll(final=final)
                        if project_observer: project_observer.poll(final=final)
                except CaptureError: raise
                except Exception as exc:
                    assembler.audit('filesystem_observer_failed',error=str(exc));observer_failed=True
                    if self.observation_checkpoint_seconds is not None: raise
                next_observation=time.monotonic()+0.25
        def pump():
            for channel,data in self.adapter.poll_events(handle,timeout=0.02): stream.feed(channel,data)
            observe()
        try:
            atomic_write_json(run_dir/'run_meta.json',state)
            try: normalizer=self.adapter.normalizer()
            except NotImplementedError: normalizer=None # backwards-compatible fixture adapters
            stream=LiveTrajectoryCollector(collector,run_dir/'raw'/f'{self.adapter.provider}.jsonl',self.adapter.provider,
                normalizer=normalizer,assembler=assembler,workspace=workspace)
            if self.watch_workspace:
                observer=WorkspaceObserver(sink,workspace,excluded=(run_dir,store.root,path.parent),
                                           max_files=self.observer_max_files)
                if self.include_project_symlink and (workspace/'project').is_symlink():
                    project_observer=WorkspaceObserver(sink,(workspace/'project').resolve(),
                        max_files=self.observer_max_files,logical_prefix='project/')
                observe(force=True)
            if setup: setup(sink) # injection only; Runner never registers or calls engine tools
            if self.startup_counts_toward_timeout and time.monotonic()>=launch_deadline:
                raise TimeoutError('Workspace baseline exceeded invocation budget before model launch')
            handle=self.adapter.start(prompt,cwd=workspace,env=child_env)
            state['pid']=handle.process.pid
            atomic_write_json(run_dir/'run_meta.json',state)
            deadline=launch_deadline if self.startup_counts_toward_timeout else time.monotonic()+self.timeout_seconds
            self.adapter.start_readers(handle)
            while True:
                pump()
                if self._stop.is_set():
                    result={'status':'interrupted','ok':None};break
                if not self.adapter.is_running(handle):
                    code=handle.process.returncode
                    result={'status':'completed' if code==0 else 'crashed','ok':code==0,'exit_code':code};break
                if time.monotonic()>=deadline:
                    result={'status':'timeout','ok':False};break
        except KeyboardInterrupt:
            result={'status':'interrupted','ok':None,'stop_reason':'keyboard_interrupt'}
        except Exception as exc:
            result={'status':'runner_error','ok':False,'error':str(exc)}
            extras.append({'code':'collector_or_runtime_failure','error':str(exc)})
        finally:
            try:
                if handle:
                    self.adapter.terminate(handle,grace_seconds=min(.25,self.drain_seconds))
                    end=time.monotonic()+self.drain_seconds
                    while time.monotonic()<end:
                        pump()
                        pending=set(assembler.sequences)-assembler.closed
                        if handle.eof=={'stdout','stderr'} and handle.queue.empty() and not pending and not spool.partial:
                            break
                    result['exit_code']=handle.process.poll()
                    if handle.eof!={'stdout','stderr'} or not handle.queue.empty():
                        extras.append({'code':'producer_drain_incomplete','producer':'provider'})
                    for reader in handle.readers: reader.join(timeout=.02)
                observe(force=True, final=True)
            except (Exception, KeyboardInterrupt) as exc:
                extras.append({'code':'producer_drain_incomplete','error':str(exc)})
            if self.adapter.provider=='codely':
                # The live stream carries no tool definitions: the session's
                # exit autosave is the only honest source for the tool layer
                # the stream's calls actually used. The requests-view companion
                # harvests it independently; this keeps the MAIN view
                # self-contained too.
                session_id=getattr(getattr(stream,'normalizer',None),'session_id',None) \
                    or session_id_from_raw_stream(run_dir/'raw',self.adapter.provider)
                harvested=harvest_exit_tools(collector,session_id,workspace,
                    autosave_dir=autosave_dir,autosave_pattern=autosave_pattern,
                    wait_seconds=3.0)
                if harvested.get('definitions'):
                    state['tools_harvested']=harvested['definitions']
            if self.adapter.provider=='codex':
                # The exec stream carries neither tool definitions nor the
                # model name: the session rollout is the only honest source
                # for both (tools derived from the observed calls, model from
                # turn_context). This keeps the MAIN view self-contained too;
                # the requests-view companion harvests it independently.
                harvested=harvest_rollout_layer(collector,run_dir/'raw',
                    sessions_root=journal_root)
                if harvested.get('definitions'):
                    state['tools_harvested']=harvested['definitions']
            if self.adapter.provider=='claude':
                # Same for Claude Code: the session file's observed tool_use
                # blocks are the only tool-registry source, and the model
                # comes from the session records.
                harvested=harvest_claude_session_layer(collector,run_dir/'raw',
                    projects_root=journal_root)
                if harvested.get('definitions'):
                    state['tools_harvested']=harvested['definitions']
            if verification_rules:
                recorded = apply_declared_verification_rules(collector, verification_rules)
                if recorded:
                    state['verification_observed'] = {
                        'kinds': sorted(set(recorded)), 'count': len(recorded)}
            try:
                if stream: stream.close()
            except Exception as exc:
                extras.append({'code':'raw_archive_failure','error':str(exc)})
            extras.extend(stream.raw_failures if stream else [])
            # The stream's init event carries the model that produced the run;
            # record it at the metadata level the training side expects.
            if stream is not None and not collector.trajectory['metadata'].get('model'):
                model = getattr(stream.normalizer, 'model', None)
                if model:
                    collector.trajectory['metadata']['model'] = model
                    collector.writer.checkpoint()
            if spool.partial: extras.append({'code':'producer_drain_incomplete','partial_files':sorted(spool.partial)})
            pending=set(assembler.sequences)-assembler.closed
            if pending: extras.append({'code':'producer_drain_incomplete','producers':sorted(pending)})
            if stream and stream.failed and result['status']=='completed':
                result.update(status='provider_failed',ok=False)
            report=audit_capture(collector.trajectory,artifact_store=store,extra=extras)
            state.update(result,finished_at=now_iso(),capture_complete=report['complete'],
                raw_redacted=bool(stream and stream.raw_redacted),invalid_events=stream.invalid_events if stream else 0)
            try:
                collector.finish(result,completeness='complete' if report['complete'] and result['status']=='completed' else 'partial')
                atomic_write_json(run_dir/'capture_audit.json',report)
                # The stream alone never carries request boundaries, and the
                # codely stream carries neither tool definitions nor the system
                # prompt: every codely finalize — clean exit included — rebuilds
                # the requests-view companion from the CLI session journal,
                # enriched by the session's exit/periodic autosave. Never raises.
                if self.adapter.provider=='codely':
                    state['journal_recovery']=attempt_run_recovery(state,run_dir/'raw',
                        self.adapter.provider,path,journal_root=journal_root)
                if self.adapter.provider=='codex':
                    # The exec stream never carries request boundaries either:
                    # every codex finalize — clean exit included — rebuilds the
                    # requests-view companion from the session rollout, whose
                    # token_usage_records are the verified response boundaries.
                    # Never raises.
                    state['rollout_recovery']=attempt_codex_run_recovery(state,
                        run_dir/'raw',path,sessions_root=journal_root)
                if self.adapter.provider=='claude':
                    # Same for Claude Code: every finalize rebuilds the
                    # requests-view companion from the session file, whose
                    # assistant records are the verified response boundaries.
                    # Never raises.
                    state['session_recovery']=attempt_claude_run_recovery(state,
                        run_dir/'raw',path,projects_root=journal_root)
                atomic_write_json(run_dir/'run_meta.json',state)
                # Usage/cost telemetry: the CLI's terminal result event carries
                # the run's aggregate usage block with provider keys (verified
                # against the installed CLI: result.stats total/input/output
                # tokens + duration_ms). The invocation merges into run_meta
                # under 'telemetry' via the single metering-source writer,
                # after the runner's own final write; provider keys stay
                # verbatim and missing numbers stay absent, never zero-filled.
                if stream is not None:
                    payload=None
                    for event in reversed(collector.trajectory['events']):
                        if event.get('provider_event')=='result':
                            data=(event.get('content') or [{}])[0].get('data')
                            payload=data if isinstance(data,dict) else None
                            break
                    if isinstance((payload or {}).get('stats'),dict):
                        try:
                            TelemetryWriter(run_dir/'run_meta.json').record_invocation(
                                kind='session',
                                status=str(payload.get('status') or 'unknown'),
                                session_id=getattr(stream.normalizer,'session_id',None),
                                model=collector.trajectory['metadata'].get('model'),
                                provider=self.adapter.provider,
                                completed_at=payload.get('timestamp'),
                                ts_source='provider' if payload.get('timestamp') else 'collector',
                                usage=payload['stats'])
                        except (OSError,ValueError) as exc:
                            # telemetry is auxiliary: the stats stay verbatim in
                            # the runtime events and the raw archive either way
                            print(f'usage telemetry merge failed; stats kept in the raw archive: {exc}',
                                  file=sys.stderr)
                # Codex usage telemetry: the rollout harvest already parsed the
                # per-response token_usage_records (one physical model call
                # each, provider keys verbatim, verified on real sessions);
                # record them as the invocations they are.
                if self.adapter.provider=='codex':
                    for record in (state.get('rollout_recovery') or {}).get('usage_records') or []:
                        if not isinstance(record.get('usage'),dict):
                            continue
                        try:
                            TelemetryWriter(run_dir/'run_meta.json').record_invocation(
                                kind='model', status='completed',
                                provider='codex', model=record.get('model'),
                                session_id=record.get('turn_id'),
                                completed_at=record.get('ts'),
                                ts_source='provider' if record.get('ts') else 'collector',
                                usage=record['usage'])
                        except (OSError,ValueError):
                            pass  # telemetry is auxiliary; the usage stays in the companion + rollout
                # Claude usage telemetry: the session harvest already parsed
                # the per-response usage blocks (one per assistant record,
                # provider keys verbatim, verified on real sessions).
                if self.adapter.provider=='claude':
                    for record in (state.get('session_recovery') or {}).get('usage_records') or []:
                        if not isinstance(record.get('usage'),dict):
                            continue
                        try:
                            TelemetryWriter(run_dir/'run_meta.json').record_invocation(
                                kind='model', status='completed',
                                provider='claude', model=record.get('model'),
                                session_id=record.get('response_id'),
                                completed_at=record.get('ts'),
                                ts_source='provider' if record.get('ts') else 'collector',
                                usage=record['usage'])
                        except (OSError,ValueError):
                            pass  # telemetry is auxiliary; the usage stays in the companion + session file
            except Exception as exc:
                state['finalization_error']=str(exc)
                print(f'Live capture finalization failed; keep partial trajectory at {path}: {exc}',file=sys.stderr)
            finally:
                collector.writer.close()
            self.last_report=state
        return path


def main(argv=None):
    p=argparse.ArgumentParser(description='Run an Agent; observe existing execution boundaries without providing tools')
    p.add_argument('prompt');p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--prepare-workspace',type=Path)
    p.add_argument('--provider',choices=SUPPORTED_AGENTS,default='codex')
    p.add_argument('--interactive',action='store_true',help='Native agent terminal: codely journal observation / codex rollout snapshots (not a lossless stream)')
    p.add_argument('--autosave-dir',type=Path)
    p.add_argument('--autosave-pattern',default='chat-auto-save-*.json')
    p.add_argument('--trajectory',type=Path)
    p.add_argument('--executable');p.add_argument('--agent-arg',action='append',default=[])
    p.add_argument('--game-id',default='live_agent');p.add_argument('--run-id')
    p.add_argument('--timeout',type=float,default=3600);p.add_argument('--drain-seconds',type=float,default=1)
    p.add_argument('--no-workspace-watch',action='store_true')
    p.add_argument('--engine',help='Target engine name for the environment snapshot, e.g. unity3d')
    p.add_argument('--no-environment',action='store_true',
                   help='Skip the collector-host environment snapshot')
    p.add_argument('--journal-root',type=Path,
                   help='Override the codely session-journal root (default ~/.codely-cli/tmp)')
    add_identity_arguments(p)
    p.add_argument('--verify',action='append',default=[],metavar='KIND=REGEX',
                   help='Harness-declared verification rule: command executions matching REGEX are recorded as KIND verification observations (e.g. syntax_check=^node --check)')
    a=p.parse_args(argv)
    identity=identity_metadata(vars(a))
    verification_rules=parse_verification_rules(a.verify)
    if a.interactive:
        if a.prepare_workspace: p.error('prepare the interactive workspace before launching')
        from .interactive_runner import run_interactive
        path=run_interactive(a.prompt,workspace=a.workspace,run_dir=a.run_dir,
            game_id=a.game_id,run_id=a.run_id or a.run_dir.name,provider=a.provider,
            executable=a.executable or a.provider,extra_args=a.agent_arg,
            autosave_dir=a.autosave_dir,autosave_pattern=a.autosave_pattern,
            trajectory=a.trajectory,timeout_seconds=a.timeout,
            engine=a.engine,skip_environment=a.no_environment,
            journal_root=a.journal_root,extra_metadata=identity,
            verification_rules=verification_rules)
        print(path)
        state=json.loads((a.run_dir/'run_meta.json').read_text())
        return 0 if state['status']=='completed' and not state.get('capture_missing_reason') else 1
    runner=AgentRunner(get_adapter(a.provider,executable=a.executable,extra_args=a.agent_arg),timeout_seconds=a.timeout,
                       drain_seconds=a.drain_seconds,watch_workspace=not a.no_workspace_watch)
    print(runner.run(a.prompt,workspace=a.workspace,run_dir=a.run_dir,prepare_workspace=a.prepare_workspace,
                    metadata={'game_id':a.game_id,'run_id':a.run_id or a.run_dir.name,**identity},register=True,
                    trajectory_path=a.trajectory,engine=a.engine,skip_environment=a.no_environment,
                    journal_root=a.journal_root,autosave_dir=a.autosave_dir,autosave_pattern=a.autosave_pattern,
                    verification_rules=verification_rules))
    return 0 if runner.last_report.get('status')=='completed' and not runner.last_report.get('finalization_error') else 1


if __name__=='__main__': raise SystemExit(main())
