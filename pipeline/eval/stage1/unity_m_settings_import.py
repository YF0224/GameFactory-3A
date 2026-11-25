"""Exact reviewed native PlayerSettings serialization for the first Unity M case.

The source and imported bytes are both retained and delivered. This narrowly
binds the actual 2022.3.62t13 import; no rendering equivalence is asserted.
"""
from pathlib import Path
from .protocol import sha
from . import batch

PAIR=('554ba32f8a816bd6ce774c042cece55e68a2f723fb1654a977fc58266f3c5921',
      'f220f809c990ec2e9e21fe42681c9901e7f60c9a94760b988504019e0f633c2a')


def proof(recorded, isolated):
    recorded=Path(recorded);isolated=Path(isolated)
    before=isolated/'ProjectSettings/ProjectSettings.asset'
    project=recorded/'background_record/project';after=project/'ProjectSettings/ProjectSettings.asset'
    if (sha(before),sha(after))!=PAIR:
        raise ValueError('Unreviewed native PlayerSettings serialization; exact source/import pair required')
    binding=batch.read(recorded/'recorder_acceptance_binding.json')
    acceptance=Path(binding['acceptance'])
    if sha(acceptance)!=binding['acceptance_sha256'] or not batch.read(acceptance)['accepted']:
        raise ValueError('Current matching native acceptance required')
    version=project/'ProjectSettings/ProjectVersion.txt';log=project/'Library/GameFactory3A/Editor.log'
    if 'm_EditorVersion: 2022.3.62t13\n' not in version.read_text() or b'Initialize engine version: 2022.3.62t13' not in log.read_bytes():
        raise ValueError('Actual accepted native Editor import required')
    # Both complete serializations are bound; source gameplay settings unchanged.
    # Reviewed differences: native YAML tag, platform schema additions, iOS/tvOS
    # target 12->13, HMI/OpenHarmony mobile render entries, deprecated zero HMI log.
    return {'version':'unity-m-player-settings-import.v1','isolated_sha256':PAIR[0],
        'recorded_sha256':PAIR[1],'editor_version':'2022.3.62t13',
        'native_log_sha256':sha(log),'native_acceptance_sha256':sha(acceptance),
        'authored_gameplay_settings_changed':False,'rendering_equivalence_claimed':False}
