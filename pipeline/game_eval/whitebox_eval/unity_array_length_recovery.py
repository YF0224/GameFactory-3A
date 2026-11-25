"""Exact-source compatibility for an authored array Count property compile error."""
from pathlib import Path
import difflib
import re

from .protocol import sha

SOURCE = 'Assets/Validation/FlightPlaytest.cs'
API = 'Assets/A3GameRuntime/Runtime/A3GameMediaDirector.cs'
RECEIVER = 'Assets/Presentation/SkyFeedback.cs'
BOOTSTRAP = 'Assets/Assembly/SkyBootstrap.cs'
OLD = 'feedback.director.GetEventLog().Count'
NEW = 'feedback.director.GetEventLog().Length'
ERROR = "Assets/Validation/FlightPlaytest.cs(49,655): error CS1061: 'A3GameMediaDirector.MediaEvent[]' does not contain a definition for 'Count' and no accessible extension method 'Count' accepting a first argument of type 'A3GameMediaDirector.MediaEvent[]' could be found (are you missing a using directive or an assembly reference?)"


def sources(entry, root):
    from .unity_asmdef_reference_recovery import asset
    review=entry['array_length_compatibility'];bindings=review.get('sources')
    if not isinstance(bindings,dict) or set(bindings)!={SOURCE,API,RECEIVER,BOOTSTRAP}:
        raise ValueError('Exact array API/caller/receiver/bootstrap bindings required')
    texts={}
    for relative,digest in bindings.items():
        path=asset(root,relative,'.cs')
        if sha(path)!=digest:raise ValueError('Reviewed array compatibility source changed')
        texts[relative]=path.read_text()
    caller=texts[SOURCE];lines=caller.splitlines()
    if (len(lines)<49 or not lines[48][654:].startswith('Count')
            or caller.count(OLD)!=1 or NEW in caller
            or caller.count(' void Finish(){')!=1
            or OLD not in lines[48] or not lines[48].startswith(' void Finish(){')
            or 'SkyFeedback feedback;' not in caller
            or not re.search(r'public\s+MediaEvent\[\]\s+GetEventLog\(\)\s*=>\s*_events\.ToArray\(\)\s*;',texts[API])
            or not re.search(r'public\s+A3GameMediaDirector\s+director\s*;',texts[RECEIVER])
            or 'class SkyFeedback:MonoBehaviour' not in texts[RECEIVER]
            or 'if(!string.IsNullOrEmpty(FlightPlaytest.Arg("--wb-output")))new GameObject("Validation Pilot - SYNTHETIC INPUT").AddComponent<FlightPlaytest>().Setup(r,u,f);' not in texts[BOOTSTRAP]):
        raise ValueError('Exact array count API, receiver, callsite or automation gate differs')
    return texts


def review(entry):
    from .batch import read
    item=entry['array_length_compatibility']
    if item.get('operation')!='reviewed_array_count_to_length':raise ValueError('Unknown array compatibility operation')
    sources(entry,entry['project'])
    for key in ('prior_receipt','compiler_log'):
        if sha(Path(item[key]))!=item[key+'_sha256']:raise ValueError('Array compiler failure evidence changed')
    execution=read(Path(item['prior_receipt'])).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code')==0:
        raise ValueError('Array repair requires a completed actual failed native process')
    errors={line.strip() for line in Path(item['compiler_log']).read_text(errors='replace').splitlines() if 'error CS' in line}
    if errors!={ERROR}:raise ValueError('Array compatibility requires exactly the reviewed physical compiler error')
    return True


def prepare(entry,sandbox):
    review(entry)
    texts=sources(entry,sandbox)
    original=texts[SOURCE];changed=original.replace(OLD,NEW,1)
    # Only a member identifier changes; the array, arguments and all other source bytes are preserved.
    if changed.replace(NEW,OLD,1)!=original:raise ValueError('Array compatibility inverse proof failed')
    return original,changed


def apply(entry,sandbox,prepared):
    from .unity_asmdef_reference_recovery import asset
    before,after=prepared
    path=asset(sandbox,SOURCE,'.cs')
    if path.read_text()!=before:raise ValueError('Array compatibility source changed after preparation')
    raw=path.read_bytes();before_sha=sha(path);path.write_bytes(raw.replace(OLD.encode(),NEW.encode(),1))
    return {'operation':'reviewed_array_count_to_length','source':SOURCE,'before_sha256':before_sha,
        'after_sha256':sha(path),'before_utf8':before,'after_utf8':after,
        'patch':''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+SOURCE,tofile='b/'+SOURCE)),
        'exact_inverse':after.replace(NEW,OLD,1)==before,'compiler_error':ERROR,
        'runtime_gameplay_changes':[],'author_validation_invoked':False,
        'scope':'Compile-only array length property compatibility in uninvoked authored validation output; formal runtime never supplies --wb-output.'}
