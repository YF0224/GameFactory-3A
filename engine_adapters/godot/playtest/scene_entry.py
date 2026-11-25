"""Resolve delivered Godot scene references without altering project settings."""
from __future__ import annotations
import os,re
from pathlib import Path

def resolve_scene(project):
    project=Path(project).resolve()
    config=project/"project.godot"
    text=config.read_text(errors="replace") if config.is_file() else ""
    match=re.search(r'^\s*run/main_scene\s*=\s*["\']([^"\']+)["\']',text,re.M)
    configured=match[1] if match else ""
    scenes=[]
    for folder,dirs,files in os.walk(project,followlinks=False):
        dirs[:]=[d for d in dirs if d not in {".godot",".git",".import","node_modules"} and not (Path(folder)/d).is_symlink()]
        scenes.extend(p for n in files if (p:=Path(folder)/n).suffix in {".tscn",".scn"} and not p.is_symlink() and p.resolve().is_relative_to(project))
    scenes=sorted(scenes)
    result={"version":"whitebox-godot-scene.v2","configured":configured,"expected_path":None,"exists":False,"resolved":None,"classification":"NO_CONFIGURED_SCENE","other_scenes":[p.relative_to(project).as_posix() for p in scenes],"selection_evidence":[],"project_root":str(project)}
    candidates=[]
    if configured.startswith("uid://"):
        for p in scenes:
            if p.suffix==".tscn":
                header=p.open(errors="replace").read(4096).split("\n",1)[0]
                if re.search(r'\buid="'+re.escape(configured)+'"',header):candidates.append(p)
        result["classification"]="UID_IMPORT_REQUIRED"
        result["selection_evidence"]=["configured UID matches delivered scene header"] if candidates else []
    elif configured:
        rel=configured.removeprefix("res://")
        result["expected_path"]=rel
        p=project/rel
        if not Path(rel).is_absolute() and p.resolve().is_relative_to(project) and p in scenes:
            candidates=[p];result["selection_evidence"]=["configured delivered scene"]
        else:result["classification"]="PRODUCT_MISSING_MAIN_SCENE"
    if not candidates:
        # Explicit delivered README launch references can resolve a stale config.
        documented=[]
        for readme in project.glob("*README*"):
            if readme.is_file() and not readme.is_symlink():
                content=readme.read_text(errors="replace")
                for p in scenes:
                    if "res://"+p.relative_to(project).as_posix() in content:documented.append(p)
        candidates=sorted(set(documented))
        if candidates:result["selection_evidence"]=["delivered README explicitly names scene"]
        elif not configured:
            candidates=[p for p in scenes if p.relative_to(project).as_posix() in {"main.tscn","scenes/main.tscn"}]
            if candidates:result["selection_evidence"]=["unique conventional main scene; no configured entry"]
    if len(candidates)==1:
        p=candidates[0];rel=p.relative_to(project).as_posix()
        result.update(expected_path=rel,exists=True,resolved="res://"+rel,classification="LAUNCHABLE")
    elif len(candidates)>1:result["classification"]="AMBIGUOUS_MAIN_SCENE"
    result["candidates"]=[p.relative_to(project).as_posix() for p in candidates]
    return result
