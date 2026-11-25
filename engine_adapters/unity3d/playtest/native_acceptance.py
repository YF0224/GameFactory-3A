"""Verify a current recorder against preserved short and long native fixtures."""
from pathlib import Path
import argparse
import json
import time
from . import background_record as rec

VERSION='unity-explicit-background-acceptance.v1'


def verify(path, adapter_root, editor):
    path,adapter_root,editor=Path(path),Path(adapter_root),Path(editor)
    value=json.loads(path.read_text())
    if value.get('schema')!=VERSION or value.get('accepted') is not True:
        raise ValueError('Current explicit recorder acceptance did not pass')
    if value['editor']!=str(editor.resolve()) or rec.sha(editor)!=value['editor_sha256']:
        raise ValueError('Accepted Editor changed')
    rec.verify_pin(adapter_root,value['pin'])
    for relative,digest in value['module_hashes'].items():
        if rec.sha(adapter_root/relative)!=digest:raise ValueError('Accepted recorder module changed: '+relative)
    for stage in value['stages']:
        for name in ('verification','runner_exit'):
            receipt=Path(stage[name]['path'])
            if rec.sha(receipt)!=stage[name]['sha256']:raise ValueError('Native acceptance receipt changed')
        verification=json.loads(Path(stage['verification']['path']).read_text())
        cleanup=json.loads(Path(stage['runner_exit']['path']).read_text())
        if (stage['exit_code']!=0 or not verification.get('ok') or not all(verification['checks'].values())
                or not cleanup.get('cleanup_verified') or cleanup.get('policy_violations')):
            raise ValueError('Native fixture/cleanup did not pass')
    if [stage['duration'] for stage in value['stages']]!=[20,180]:
        raise ValueError('Short and long native fixtures required')
    runtime_helper = adapter_root/'engine_adapters/unity3d/import_generated/GameFactory3ARuntimeInitializerRecorder.cs'
    runtime_stages = value.get('runtime_stages', [])
    if runtime_helper.is_file():
        from . import runtime_initializer
        required = ['engine_adapters/unity3d/playtest/'+name for name in
                    ('runtime_initializer.py','client.py','native_acceptance.py')]
        required += ['engine_adapters/unity3d/import_generated/GameFactory3ARuntimeInitializerRecorder.cs',
                     'engine_adapters/unity3d/_internal/transport/unity_editor.py']
        if any(name not in value['module_hashes'] for name in required):
            raise ValueError('Runtime initializer capture modules are not acceptance-bound')
        if [stage['duration'] for stage in runtime_stages] != [20,180]:
            raise ValueError('Runtime initializer short and long native fixtures required')
        for stage in runtime_stages:
            for name in ('verification','runner_exit','native_entry','entry_binding','actions'):
                receipt = Path(stage[name]['path'])
                if rec.sha(receipt) != stage[name]['sha256']:
                    raise ValueError('Runtime native acceptance receipt changed: '+name)
            verification = json.loads(Path(stage['verification']['path']).read_text())
            cleanup = json.loads(Path(stage['runner_exit']['path']).read_text())
            if (stage['exit_code'] != 0 or not verification.get('ok')
                    or not all(verification['checks'].values())
                    or verification['checks'].get('natural_runtime_entry') is not True
                    or not cleanup.get('cleanup_verified') or cleanup.get('policy_violations')):
                raise ValueError('Runtime initializer fixture/cleanup did not pass')
            binding = runtime_initializer.verify_recording(Path(stage['entry_binding']['path']).parent)
            native = json.loads(Path(stage['native_entry']['path']).read_text())
            if not runtime_initializer.verify_native(binding,native):
                raise ValueError('Runtime native lifecycle/source receipt invalid')
    elif runtime_stages:
        raise ValueError('Runtime acceptance has no matching recorder capability')
    return value


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--adapter-root',type=Path,required=True)
    p.add_argument('--control-root',type=Path,required=True)
    p.add_argument('--parent-pin',type=Path,required=True)
    p.add_argument('--fixture-root',type=Path,required=True)
    p.add_argument('--editor',type=Path,required=True)
    p.add_argument('--runtime-attempt',type=Path,help='Frozen actual authored scene-less entry with verified native admission')
    p.add_argument('--runtime-actions-20',type=Path)
    p.add_argument('--runtime-actions-180',type=Path)
    a=p.parse_args()
    runtime_helper = a.adapter_root/'engine_adapters/unity3d/import_generated/GameFactory3ARuntimeInitializerRecorder.cs'
    has_runtime = runtime_helper.is_file()
    runtime_options = (a.runtime_attempt,a.runtime_actions_20,a.runtime_actions_180)
    if has_runtime != all(runtime_options) or (not has_runtime and any(runtime_options)):
        raise ValueError('Runtime recorder capability requires independently admitted entry and both native action fixtures')
    out=a.output.resolve();out.mkdir(exist_ok=False,parents=True)
    parent=json.loads(a.parent_pin.read_text())
    if parent.get('accepted') is not True:raise ValueError('Preserved parent pin was not accepted')
    modules=['engine_adapters/unity3d/playtest/'+n for n in
             ['background_record.py','project_snapshot.py','endpoint_settle.py','native_acceptance.py','input_axis_serialization.py','resources/GameFactoryInput.cs','functional_observer.py']]
    modules += ['engine_adapters/unity3d/editor_paths.py',
                'engine_adapters/unity3d/playtest/resources/GameFactoryInput.provenance.json']
    if has_runtime:
        modules += ['engine_adapters/unity3d/playtest/runtime_initializer.py',
                    'engine_adapters/unity3d/playtest/client.py',
                    'engine_adapters/unity3d/import_generated/GameFactory3ARuntimeInitializerRecorder.cs',
                    'engine_adapters/unity3d/_internal/transport/unity_editor.py']
    pin=dict(parent,accepted=False,validation_scope='Explicit current short/long native fixtures')
    pin['files']={relative:rec.sha(a.adapter_root/relative) for relative in parent['files']}
    value={'schema':VERSION,'accepted':False,'started':time.time(),'editor':str(a.editor.resolve()),
        'editor_sha256':rec.sha(a.editor),'parent_pin':str(a.parent_pin.resolve()),'parent_pin_sha256':rec.sha(a.parent_pin),
        'pin':pin,'module_hashes':{n:rec.sha(a.adapter_root/n) for n in modules},'stages':[]}
    rec.dump(out/'candidate_pin.json',pin);rec.dump(out/'acceptance.json',value)
    rec.KNOWN_EDITOR=a.editor.resolve()
    for duration in (20,180):
        preserved=a.fixture_root/f'fixture_{duration}s'
        actions=json.loads((preserved/'actions_input.json').read_text())['actions']
        action_file=out/f'actions_{duration}s.json';rec.dump(action_file,{'actions':actions})
        args=['selftest','--adapter-root',str(a.adapter_root.resolve()),'--adapter-pin',str(out/'candidate_pin.json'),
              '--control-root',str(a.control_root.resolve()),'--unity',str(a.editor.resolve()),
              '--fixture-project',str((preserved/'project').resolve()),'--actions',str(action_file),
              '--duration',str(duration),'--output',str(out/f'fixture_{duration}s')]
        if (preserved/'functional_observer_contract.json').exists():
            args+=['--observer-contract',str((preserved/'functional_observer_contract.json').resolve())]
        if (preserved/'take/capture_schedule.json').exists():
            args+=['--capture-schedule',str((preserved/'take/capture_schedule.json').resolve())]
        from pipeline.game_eval.whitebox_eval import unity_disk_guard as disk
        disk.check(out,'native_acceptance',preserved/'project')
        disk.check(out,'capture',preserved/'project',duration=duration,frames=duration*10,width=960,height=540)
        code=rec.main(args,validation_pin=pin)
        stage={'duration':duration,'exit_code':code}
        for name in ('verification','runner_exit'):
            f=out/f'fixture_{duration}s'/(name+'.json');stage[name]={'path':str(f),'sha256':rec.sha(f)}
        value['stages'].append(stage);value['updated']=time.time();rec.dump(out/'acceptance.json',value)
        if code:raise RuntimeError('Native fixture failed: '+str(duration))
    if has_runtime:
        from . import runtime_initializer
        entry_path = out/'runtime_initializer_entry.json'
        binding = runtime_initializer.write(a.runtime_attempt,entry_path)
        source = Path(json.loads((a.runtime_attempt/'input_manifest.json').read_text())['entry']['project']).resolve()
        runtime_initializer.load(entry_path,source)
        value['runtime_stages'] = []
        value['runtime_scope'] = 'Native capability acceptance only; actual authored startup, input/frame/cleanup; not a production gameplay score'
        for duration,action_path in ((20,a.runtime_actions_20),(180,a.runtime_actions_180)):
            actions = rec.load_actions(action_path,duration)
            if rec.recording_duration(actions,duration) != duration:
                raise ValueError('Runtime fixture actions must cover the exact acceptance duration')
            action_file=out/f'runtime_actions_{duration}s.json';rec.dump(action_file,{'actions':actions})
            destination=out/f'runtime_fixture_{duration}s'
            args=['record','--adapter-root',str(a.adapter_root.resolve()),'--adapter-pin',str(out/'candidate_pin.json'),
                  '--control-root',str(a.control_root.resolve()),'--unity',str(a.editor.resolve()),
                  '--project',str(source),'--scene',binding['source'],'--runtime-entry',str(entry_path),
                  '--actions',str(action_file),'--duration',str(duration),'--output',str(destination)]
            from pipeline.game_eval.whitebox_eval import unity_disk_guard as disk
            disk.check(out,'native_acceptance',source)
            disk.check(out,'capture',source,duration=duration,frames=duration*10,width=960,height=540)
            code=rec.main(args,validation_pin=pin)
            stage={'duration':duration,'exit_code':code}
            files={'verification':destination/'verification.json','runner_exit':destination/'runner_exit.json',
                   'native_entry':destination/'take/runtime_initializer_native.json',
                   'entry_binding':destination/'take/runtime_initializer_entry.json','actions':action_file}
            for name,f in files.items():
                if f.is_file():stage[name]={'path':str(f),'sha256':rec.sha(f)}
                else:stage[name]={'path':str(f),'missing':True}
            value['runtime_stages'].append(stage);value['updated']=time.time();rec.dump(out/'acceptance.json',value)
            if code:raise RuntimeError('Runtime native fixture failed: '+str(duration))
    value['accepted']=True;rec.dump(out/'acceptance.json',value)
    verify(out/'acceptance.json',a.adapter_root,a.editor)
    print(json.dumps({'accepted':True,'path':str(out/'acceptance.json')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
