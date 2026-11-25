"""Source-bound lossless PCM transport recovery for native Astra audio evidence."""
from pathlib import Path
import base64
import hashlib
import json
import wave
from .common import read, dump, once, sha
from .vfx_groups import ref
from .project_eval_judge import recovery_authorization


def split_pcm(wav, directory, seconds=30):
    directory.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav), 'rb') as stream:
        params = stream.getparams()
        if params.comptype != 'NONE':
            raise ValueError('PCM transport recovery requires uncompressed native WAV')
        segments = []
        original_digest = hashlib.sha256()
        offset = 0
        while offset < params.nframes:
            count = min(seconds*params.framerate, params.nframes-offset)
            frames = stream.readframes(count)
            if len(frames) != count*params.nchannels*params.sampwidth:
                raise ValueError('Native WAV frame coverage incomplete')
            original_digest.update(frames)
            path = directory/('segment_%03d.wav' % len(segments))
            with wave.open(str(path), 'wb') as output:
                output.setparams(params._replace(nframes=count))
                output.writeframes(frames)
            segments.append({'audio': ref(path), 'start_frame': offset, 'frame_count': count,
                             'pcm_sha256': hashlib.sha256(frames).hexdigest()})
            offset += count
    value = {'audio': ref(wav), 'segments': segments, 'nframes': params.nframes,
             'sample_rate': params.framerate, 'channels': params.nchannels, 'sample_width': params.sampwidth,
             'pcm_sha256': original_digest.hexdigest(), 'sample_unchanged': True}
    verify_segments(value)
    return value


def verify_segments(value):
    if ref(value['audio']['path']) != value['audio']:
        raise ValueError('Original native audio changed')
    offset = 0
    digest = hashlib.sha256()
    with wave.open(value['audio']['path'], 'rb') as original:
        if (original.getnframes(), original.getframerate(), original.getnchannels(), original.getsampwidth()) != (
                value['nframes'], value['sample_rate'], value['channels'], value['sample_width']):
            raise ValueError('Audio parameters changed')
        for segment in value['segments']:
            if segment['start_frame'] != offset or ref(segment['audio']['path']) != segment['audio']:
                raise ValueError('PCM segments reordered, missing or changed')
            with wave.open(segment['audio']['path'], 'rb') as part:
                if (part.getframerate(), part.getnchannels(), part.getsampwidth(), part.getnframes()) != (
                        value['sample_rate'], value['channels'], value['sample_width'], segment['frame_count']):
                    raise ValueError('PCM segment parameters changed')
                frames = part.readframes(part.getnframes())
            if frames != original.readframes(segment['frame_count']) or hashlib.sha256(frames).hexdigest() != segment['pcm_sha256']:
                raise ValueError('Segment samples differ from original native recording')
            digest.update(frames)
            offset += segment['frame_count']
    if offset != value['nframes'] or digest.hexdigest() != value['pcm_sha256']:
        raise ValueError('Incomplete native audio sample coverage')
    return True


def prepare_segmented_audio(root):
    entry = recovery_authorization(root, 'audio_qwen')
    if not entry or entry.get('transport') != 'pcm_segments_v1':
        return
    if entry['recovery_implementation_sha256'] != sha(__file__):
        raise ValueError('Segmented transport implementation changed')
    stage = entry['recovery_stage']
    directory = root/'audio'/stage
    wav = root/'background_record/take/audio.wav'
    def operation():
        from models.reasoning.judges import AudioJudgeModel
        from ..judge_profiles import load_dashscope_key_file
        credentials = {}
        if not load_dashscope_key_file(Path(os.environ.get('DASHSCOPE_KEY_FILE', Path.home() / '.config/gamefactory/dashscope.txt')), credentials):
            raise ValueError('DashScope key unavailable; contents withheld')
        transport = split_pcm(wav, directory/'segments')
        dump(directory/'segments.json', transport)
        merged = {key: {'audible': 'unknown', 'time_windows_seconds': [], 'reason': ''} for key in ('gunshot', 'rain')}
        responses = []
        for index, segment in enumerate(transport['segments']):
            prompt = ('Listen to this actual native game audio segment, unchanged PCM samples. '
                'Recognizable gunshots suffice; no exact source WAV or brass-tail requirement. '
                'Rain requires audible rain/rainstorm ambience; thunder alone or music is insufficient. '
                'Do not infer from code or images. Uncertain is unknown. Times are relative to THIS segment. '
                'Return only JSON {"gunshot":{"audible":"yes|no|unknown","time_windows_seconds":[{"start":0.0,"end":1.0}],"reason":"..."},'
                '"rain":{"audible":"yes|no|unknown","time_windows_seconds":[{"start":0.0,"end":1.0}],"reason":"..."}}.')
            def invoke_segment():
                request = {'model': 'qwen3.8-omni-flash', 'prompt': prompt, 'audio': segment['audio'], 'segment': segment}
                location = directory/('observation_%03d' % index)
                dump(location/'request.json', request)
                response = AudioJudgeModel(model='qwen3.8-omni-flash', api_key=credentials['DASHSCOPE_API_KEY'],
                    max_tokens=2048, timeout_s=180).judge(prompt=prompt,
                    audio_b64=[('wav', base64.b64encode(Path(segment['audio']['path']).read_bytes()).decode())])
                dump(location/'raw_response.json', {'text': response.text, 'provenance': response.provenance})
                parsed = json.loads(response.text)
                duration = segment['frame_count']/transport['sample_rate']
                for key in ('gunshot', 'rain'):
                    row = parsed[key]
                    if row['audible'] not in ('yes', 'no', 'unknown'):
                        raise ValueError('Invalid acoustic observation')
                    for window in row['time_windows_seconds']:
                        if not 0 <= window['start'] <= window['end'] <= duration+0.05:
                            raise ValueError('Acoustic time outside delivered segment')
                return parsed
            parsed = once(root, stage+'_segment_%03d' % index, invoke_segment)
            location = directory/('observation_%03d' % index)
            responses.append({'request': ref(location/'request.json'), 'response': ref(location/'raw_response.json'), 'segment': segment})
            for key in merged:
                row = parsed[key]
                if row['audible'] == 'yes':
                    merged[key]['audible'] = 'yes'
                    start = segment['start_frame']/transport['sample_rate']
                    merged[key]['time_windows_seconds'] += [{'start': start+w['start'], 'end': start+w['end']} for w in row['time_windows_seconds']]
                merged[key]['reason'] += 'Segment %d: %s; ' % (index, row['reason'])
        verify_segments(transport)
        dump(directory/'raw_response.json', {'text': json.dumps(merged, ensure_ascii=False),
            'provenance': {'transport': 'pcm_segments_v1', 'responses': responses}})
        dump(directory/'actual_delivery.json', {'status': 'delivered', 'audio': ref(wav), 'sample_unchanged': True,
            'transport': 'pcm_segments_v1', 'segments': ref(directory/'segments.json'), 'calls': responses,
            'response': ref(directory/'raw_response.json'), 'parent_failure': entry['parent_failure']})
        return merged
    once(root, stage, operation)
    verify_segments(read(directory/'segments.json'))
