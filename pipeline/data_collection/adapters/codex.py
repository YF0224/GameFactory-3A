"""Codex exec JSONL adapter. Unknown items remain explicitly unnormalized."""
from .base import AgentAdapter
from ..core.collector import content_block


class CodexAdapter(AgentAdapter):
    provider = 'codex'
    # codex exec's --json stream never echoes the launch prompt (verified
    # against the installed CLI): the runner records the task input itself
    echoes_prompt = False
    def __init__(self, executable='codex', extra_args=()):
        self.executable, self.extra_args = executable, list(extra_args)
    def start(self, prompt, *, cwd, env=None):
        return self._spawn([self.executable,'exec','--json','--cd',str(cwd),*self.extra_args,prompt],cwd,env)
    def normalizer(self): return CodexNormalizer()


class CodexNormalizer:
    provider = 'codex'
    def __init__(self):
        self.thread_id=None
        self.turn_index=0
        self.turn_id=None
        self.items={}

    def normalize(self, e):
        typ=e.get('type')
        if typ=='thread.started':
            self.thread_id=e.get('thread_id')
        if typ=='turn.started':
            self.turn_index+=1
            self.turn_id=e.get('turn_id') # absent on known CLI events; index is derived, not a request ID
        common={'producer':self.provider,'provider_event':typ,'thread_id':self.thread_id,
                'turn_id':self.turn_id,'turn_index':self.turn_index}
        if e.get('timestamp'): common.update(ts=e['timestamp'],ts_source='provider')
        if typ in {'thread.started','turn.started','turn.completed','turn.failed','error'}:
            return [dict(source='system',kind='runtime',content=[content_block('json',data=e,visibility='collector_only')],**common)]
        if typ in {'tool_call','function_call'}:
            return [self.call(e.get('call_id') or e.get('id'),e.get('name'),e.get('arguments'),common)]
        if typ in {'tool_result','function_call_output'}:
            return [self.result(e.get('call_id'),e.get('output'),e.get('status','unknown'),common)]
        item=e.get('item')
        if typ not in {'item.started','item.updated','item.completed'} or not isinstance(item,dict):
            return [self.unknown(e,common)]
        common={**common,'item_id':item.get('id')}
        it=item.get('type')
        if it in {'agent_message','reasoning'}:
            if typ!='item.completed' or it=='reasoning':
                return [dict(source='system',kind='runtime',content=[content_block('json',data=item,visibility='collector_only')],**common)]
            return [dict(source='assistant',kind='message',content=[content_block('text',data=item.get('text',''),visibility='collector_only')],**common)]
        if it in {'command_execution','mcp_tool_call'}:
            iid=item.get('id')
            key=(self.thread_id,self.turn_index,iid)
            cid=item.get('call_id') or self.items.get(key)
            if typ=='item.started':
                cid=item.get('call_id') or (str(iid) if iid else None)
                self.items[key]=cid
                name='command_execution' if it=='command_execution' else f'{item.get("server", "")}.{item.get("tool", "")}'
                args={'command':item.get('command')} if it=='command_execution' else item.get('arguments')
                return [self.call(cid,name,args,{**common,'provider_call_id':item.get('call_id'),
                    'identity_origin':'provider' if item.get('call_id') else 'item_derived',
                    'observation_view':'provider_item'})]
            if typ=='item.completed':
                if it=='command_execution':
                    output={k:item[k] for k in ('aggregated_output','exit_code','status') if k in item}
                    status='unknown' if item.get('exit_code') is None else ('success' if item['exit_code']==0 else 'error')
                else:
                    output={k:item[k] for k in ('result','error','status') if k in item}
                    status='error' if item.get('error') or item.get('status')=='failed' else ('success' if item.get('status')=='completed' else 'unknown')
                return [self.result(cid,output,status,{**common,'observation_view':'provider_result'})]
            return [dict(source='system',kind='runtime',content=[content_block('json',data=item,visibility='collector_only')],**common)]
        return [self.unknown(e,common)]

    @staticmethod
    def call(cid,name,args,common):
        if not cid or not name:
            return CodexNormalizer.unknown({'name':name,'arguments':args,'call_id':cid},common)
        return dict(source='assistant',kind='tool_call',tool_calls=[{'tool_call_id':str(cid),'name':name,'arguments':args}],content=[],**common)

    @staticmethod
    def result(cid,output,status,common):
        if not cid:
            return CodexNormalizer.unknown({'output':output,'missing_call_id':True},common)
        return dict(source='tool',kind='tool_result',tool_call_id=str(cid),status=status,
            content=[content_block('json',data=output,visibility='collector_only')],**common)

    @staticmethod
    def unknown(e,common):
        return dict(source='system',kind='runtime',status='unknown',audit_code='unknown_provider_event',
            normalized=False,content=[content_block('json',data=e,visibility='collector_only')],**common)
