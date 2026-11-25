"""Source-bound observer repair using explicit public fields, with unchanged actions."""
from pathlib import Path
import json
import shutil
import time

from . import batch, core12
from .protocol import dump, sha

VERSION = 'unity-public-field-observer-recovery.v1'
RECEIPT = 'public_field_observer_recovery.json'
CASE = 'GLM__G009_blackout_stealth'
SOL_CASE = 'Sol__G045_daily_street_lightlane'
CARAVAN_CASE = 'Sol__G033_card_caravan'
ESCORT_CASE = 'GLM__G029_caravan_escort'
LIGHTLANE_CASE = 'GLM__G045_daily_street_lightlane'
STORM_CASE = 'GLM__G046_storm_isle_survival'
FIRE_CASE = 'GLM__G047_oldtown_fire_rescue'
POLAR_CASE = 'Sol__G048_polar_return_trek'
PUBLIC_STATE_CASES = frozenset({ESCORT_CASE, LIGHTLANE_CASE, STORM_CASE, FIRE_CASE, POLAR_CASE})
SUPPORTED = frozenset({CASE, SOL_CASE, CARAVAN_CASE}) | PUBLIC_STATE_CASES


def contract(source):
    case = batch.read(Path(source)/'input_manifest.json')['entry']['id']
    if case == POLAR_CASE:
        return polar_return_contract(source)
    if case in PUBLIC_STATE_CASES:
        return authored_public_state_contract(source, case)
    if case == CARAVAN_CASE:
        return caravan_contract(source)
    if case == SOL_CASE:
        return lampwick_contract(source)
    project = Path(source)/'input/project'
    paths = [project/'Assets/Scripts/Mechanic'/name for name in
             ('G009RuntimeAdapter.cs', 'G009World.cs', 'G009Simulation.cs', 'G009SimState.cs')]
    adapter, world, simulation, state = [p.read_text() for p in paths]
    required = [('public G009World World;', adapter),
                ('public G009Simulation Sim =', world),
                ('public readonly G009SimState State =', simulation),
                ('public readonly List<G009Guard> Guards =', state),
                ('{g.Mode:F0}', adapter)]
    if not all(text in source_text for text, source_text in required):
        raise ValueError('G009 public observer source changed; inspect actual public contract')
    fields = ['PlayerHp', 'Stance', 'IsTakedownAnimating', 'TakedownTimer',
              'Time', 'Phase', 'Alert', 'Recognition', 'DecoyCount', 'DecoyCooldownRemaining',
              'HasArchive', 'CheckpointIndex', 'EndReason', 'L2Timer', 'L2EscapeTimer',
              'Takedowns', 'LightPhaseT', 'Guards', 'Covers', 'RecentNoises']
    result = {'schema':'unity-functional-observer-contract.v2.public-fields',
              'provider_type':'G009Mechanic.G009RuntimeAdapter',
              'required_fields':fields, 'require_events':True,
              'public_field_paths':[{'name':name, 'path':'World.Sim.State.'+name} for name in fields]}
    if snapshot_extension(source) or nested_event_extension(source):
        if '[NonSerialized] public G009SimState _lastSnapshot;' not in world:
            raise ValueError('Saved checkpoint snapshot is not the authored public field')
        result['required_fields'].append('SavedCheckpointSnapshot')
        result['public_field_paths'].append(
            {'name':'SavedCheckpointSnapshot','path':'World._lastSnapshot'})
    if nested_event_extension(source):
        if ('public event Action<string, object> OnEvent = delegate { };' not in simulation
                or 'Publish("failed", "hp_zero")' not in simulation):
            raise ValueError('Authored public simulation event contract changed')
        result.update(schema='unity-functional-observer-contract.v3.public-events',
            public_event_paths=[{'path':'World.Sim','event_name':'OnEvent'}])
    return result, {str(p.relative_to(project)):sha(p) for p in paths}



def polar_return_contract(source):
    """Read authored state through the existing verified auto-property reader.

    Mechanic's getter/private setter are verified in native IL before reading its
    compiler backing field. No getter, gameplay method or command is invoked.
    """
    project = Path(source)/'input/project'
    expected = {'Assets/Scripts/Runtime/PolarReturnGame.cs': '716993ec619ea21d25676501630f0bed1e6169d8a48fe88d95c92e26db0b1d18', 'Assets/Scripts/Mechanics/PolarReturnMechanic.cs': 'aac544ad30bb67808f09876cf65bb3ace581ba40224b045dbe991aa3f13e61fb'}
    for name, digest in expected.items():
        path = project/name
        if path.is_symlink() or sha(path) != digest:
            raise ValueError('Polar Return authored observer source changed: '+name)
    fields = ['phase', 'route', 'distanceM', 'temperature', 'stamina', 'dataIntegrity', 'fuel', 'selectedRecords', 'shelterCheckpoint', 'flagCount', 'checkpointM', 'wetSeconds', 'elapsedSeconds', 'minimumTemperature', 'windFactor', 'fireSeconds', 'lowTempSeconds', 'dataColdSeconds', 'sprintLockSeconds', 'frostbite', 'windbreakerOwned', 'windbreakerEquipped', 'fireActive', 'inShelter', 'canSprint', 'shortcutTaken', 'stormSeen', 'sprinting', 'lastEvent', 'flags']
    return ({'schema':'unity-functional-observer-contract.v5.verified-auto-properties',
        'provider_type':'PolarReturnGame','required_fields':fields,'require_events':True,
        'public_field_paths':[{'name':name,'path':'Mechanic.State.'+name,
                               'auto_property_segments':[0]} for name in fields],
        'public_event_paths':[{'path':'Mechanic','event_name':'EventRaised',
                               'auto_property_segments':[0]}]}, dict(expected))


def nested_event_extension(source):
    path = Path(source)/'functional_observer_contract.json'
    if not path.is_file() or not (Path(source)/RECEIPT).is_file():
        return False
    value = batch.read(path)
    return (value.get('schema') == 'unity-functional-observer-contract.v2.public-fields'
        and value.get('provider_type') == 'G009Mechanic.G009RuntimeAdapter'
        and 'SavedCheckpointSnapshot' in value.get('required_fields', []))


def snapshot_extension(source):
    """A prior accepted public observer may omit the authored saved checkpoint."""
    path = Path(source)/'functional_observer_contract.json'
    if not path.exists() or not (Path(source)/RECEIPT).exists():
        return False
    value = batch.read(path)
    return (value.get('provider_type') == 'G009Mechanic.G009RuntimeAdapter'
            and value.get('schema') == 'unity-functional-observer-contract.v2.public-fields'
            and 'Guards' in value.get('required_fields', [])
            and 'SavedCheckpointSnapshot' not in value.get('required_fields', []))


def lampwick_contract(source):
    """Read only authored public save data; do not invent a missing event channel."""
    import re
    project = Path(source)/'input/project'
    paths = [project/'Assets/Scripts'/name for name in ('LampwickGame.cs','LaneState.cs')]
    game,state = [p.read_text() for p in paths]
    if ('public class LampwickGame : MonoBehaviour' not in game
            or 'public LaneSave s=new LaneSave();' not in game
            or '[Serializable] public class LaneSave {' not in state
            or '[Serializable] public class LaneJob {' not in state):
        raise ValueError('Lampwick public observer source changed')
    fields = ['version','cash','debt','rent','rice','meals','hobby','clock','liveSeconds',
        'hunger','energy','stress','hygiene','stamina','notice','player','bike','yaw','bikeYaw',
        'incidentAt','eventAt','trust','jobs','countDay','forcedDay','started','paid','deferred',
        'labor','settled','breakfast','borrowed','bikeExtended','bikeLate','bikeDue','roomSorted',
        'meetStage','meetDay','meetActive','meetMissed','meetRebooked','rewards','memories',
        'discoveries','shortcuts','journal','sold','room','jobTypes','delivery','manuscript',
        'shelf','cleanup','held','heldType','lost','outcome','activeEvent','shelfDone','trashDone']
    save = state.split('[Serializable] public class LaneSave {',1)[1].split('public int Day',1)[0]
    # Each listed name must be declared in a public field statement, never a
    # private mode, getter invocation, injected field, or fabricated state.
    declarations = re.findall(r'public\s+[\w<>\[\]]+\s+([^;]+);',save)
    declared = set()
    for declaration in declarations:
        # Initializers contain vectors/constructors; match only names followed
        # by assignment, comma or end, avoiding words inside literal values.
        declared.update(re.findall(r'(?:^|,)\s*([A-Za-z_]\w*)\s*(?==|,|$)',declaration))
    if not set(fields) <= declared:
        raise ValueError('Lampwick public save fields changed: '+str(sorted(set(fields)-declared)))
    result = {'schema':'unity-functional-observer-contract.v2.public-fields',
        'provider_type':'LampwickGame','required_fields':fields,'require_events':False,
        'public_field_paths':[{'name':name,'path':'s.'+name} for name in fields]}
    return result,{str(p.relative_to(project)):sha(p) for p in paths}

def caravan_contract(source):
    """Observe authored live mechanic fields through CaravanApp.g, no getters."""
    import re
    project = Path(source)/'input/project'
    paths = [project/'Assets/Presentation/CaravanApp.cs',project/'Assets/Mechanic/CaravanMechanic.cs']
    app,mechanic = [p.read_text() for p in paths]
    if ('public class CaravanApp:MonoBehaviour' not in app
            or 'public CaravanMechanic g;' not in app
            or 'public class CaravanMechanic {' not in mechanic):
        raise ValueError('Caravan public observer source changed')
    fields = 'phase returnPhase message seed battle turn hp enemyHp enemyMax energy block enemyBlock strength enemyStrength vulnerable poison intentIndex seq firstAttack rng deck draw discard hand offers relic'.split()
    # Restrict to declarations preceding the first property; static Cards and
    # public delegate OnEvent are excluded from observation.
    declarations = re.findall(r'public\s+(?:string|int|uint|List<int>)\s+([^;]+);',
        mechanic.split('public class CaravanMechanic {',1)[1].split('public string EnemyName',1)[0])
    declared=set()
    for value in declarations:
        declared.update(re.findall(r'(?:^|,)\s*([A-Za-z_]\w*)\s*(?==|,|$)',value))
    if not set(fields)<=declared:
        raise ValueError('Caravan public state declarations changed')
    return ({'schema':'unity-functional-observer-contract.v2.public-fields',
        'provider_type':'SandCaravan.CaravanApp','required_fields':fields,'require_events':False,
        'public_field_paths':[{'name':name,'path':'g.'+name} for name in fields]},
        {str(p.relative_to(project)):sha(p) for p in paths})



def authored_public_state_contract(source, case):
    """Use reviewed public fields already read by authored UI/simulation, no getters."""
    project = Path(source)/'input/project'
    if case == ESCORT_CASE:
        path = project/'Assets/Mechanic/CaravanEscortGame.cs'
        text = path.read_text()
        fields = 'phase durability resource segmentIndex routeProgress selectedDevice warnCountdown warnDirection recycleCountdown isPaused settingsCameraShake settingsDamageNumbers deployables enemies checkpointDurability'.split()
        declarations = ['public sealed class CaravanEscortGame : MonoBehaviour',
            'public Phase phase = Phase.Boot;', 'public int durability, resource, segmentIndex;',
            'public float routeProgress;', 'public DeviceKind selectedDevice = DeviceKind.ArrowTower;',
            'public float warnCountdown;', 'public WarnDirection warnDirection;',
            'public float recycleCountdown;', 'public bool isPaused;',
            'public bool settingsCameraShake = true, settingsDamageNumbers = true;',
            'public readonly List<DeployableState> deployables = new List<DeployableState>();',
            'public readonly List<EnemyState> enemies = new List<EnemyState>();',
            'public readonly List<int> checkpointDurability = new List<int>();']
        provider = 'CaravanEscort.Mechanic.CaravanEscortGame'
    elif case == LIGHTLANE_CASE:
        path = project/'Assets/Scripts/Runtime/GameCore.cs'
        text = path.read_text()
        fields = 'day dayMinute subMinuteAccum cash rentPaid rentDebt prepayDebt hunger energy stress hygiene stamina attention rentSettled rentExtendedOnce endingBranch lastFatigueDay duskCgPlayed inventory npcTrust questState flags discoveredPoints discoveredShortcuts workCounts'.split()
        declarations = ['public class GameState : MonoBehaviour', 'public int day = 1;',
            'public int dayMinute = GameConfig.DayStartMinute;', 'public float subMinuteAccum = 0f;',
            'public int cash, rentPaid, rentDebt, prepayDebt;',
            'public float hunger, energy, stress, hygiene, stamina, attention;',
            'public bool rentSettled=false, rentExtendedOnce=false;', 'public string endingBranch="";',
            'public int lastFatigueDay=-1;', 'public bool duskCgPlayed=false;',
            'public Dictionary<string,int> inventory = new();', 'public Dictionary<NpcId,int> npcTrust = new();',
            'public QuestState[] questState = new QuestState[7];',
            'public HashSet<string> flags = new(), discoveredPoints = new(), discoveredShortcuts = new();',
            'public Dictionary<string,int> workCounts = new();']
        provider = 'LightLane.GameState'
    elif case == FIRE_CASE:
        return fire_rescue_contract(source)
    elif case == STORM_CASE:
        path = project/'Assets/Mechanics/GameManager.cs'
        text = path.read_text()
        fields = ['phase','craftPanelOpen','skipCinematics','smokeFreezePlayer']
        declarations = ['public class GameManager : MonoBehaviour', 'public GamePhase phase = GamePhase.Title;',
            'public bool craftPanelOpen = false;', 'public bool skipCinematics = false;',
            'public bool smokeFreezePlayer = false;', 'public HealthSystem health;',
            'public Inventory inventory;', 'public DayNightStormSystem dayNight;', 'public PlayerController player;']
        provider = 'GameFactory3A.Mechanics.GameManager'
    else:
        raise ValueError('Unsupported authored public state observer')
    if not all(declaration in text for declaration in declarations):
        raise ValueError('Reviewed authored public state declarations changed: '+case)
    paths = [{'name':name,'path':name} for name in fields]
    refs = {str(path.relative_to(project)):sha(path)}
    if case == STORM_CASE:
        additions = [
            ('HealthSystem.cs', ['public int hp = G.Frozen.HP_MAX;', 'public int deaths = 0;', 'public bool isDead = false;'],
             [('hp','health.hp'),('deaths','health.deaths'),('isDead','health.isDead')]),
            ('Inventory.cs', ['public InvSlot[] hotbar = new InvSlot[Slots];','public int selected = 0;'],
             [('hotbar','inventory.hotbar'),('selected','inventory.selected')]),
            ('DayNightStormSystem.cs', ['public float elapsed = 0f;', 'public bool Running = false;'],
             [('elapsed','dayNight.elapsed'),('Running','dayNight.Running')]),
            ('PlayerController.cs', ['public bool InputEnabled = true;'], [('InputEnabled','player.InputEnabled')])]
        for name, required, members in additions:
            path = project/'Assets/Mechanics'/name
            if not all(item in path.read_text() for item in required):
                raise ValueError('Reviewed authored public nested state declarations changed: '+name)
            refs[str(path.relative_to(project))] = sha(path)
            paths.extend({'name':name,'path':member} for name,member in members)
        fields = [row['name'] for row in paths]
    return ({'schema':'unity-functional-observer-contract.v2.public-fields',
        'provider_type':provider,'required_fields':fields,'require_events':False,
        'public_field_paths':paths}, refs)


def fire_rescue_contract(source):
    """Expose existing public gameplay data; never invoke methods or invent an event."""
    project = Path(source)/'input/project'
    specs = {
        'GameDirector.cs': ['public class GameDirector : MonoBehaviour',
            'public FireGridSystem fireGrid;', 'public WaterResourceSystem water;',
            'public RouteBlockSystem routeBlock;', 'public NpcRescueSystem npcs;',
            'public PlayerController player;', 'public MechanicConfig config;',
            'public GameState state = GameState.Boot;', 'public float timeRemaining;',
            'public string currentCgKey;', 'public bool cgPlayedC01, cgPlayedC02, cgPlayedC03;',
            'public string loseReason;', 'public float timeUsed;', 'public bool smokeTestMode;'],
        'FireGridSystem.cs': ['public class FireGridSystem : MonoBehaviour',
            'public CellState[,] cells;',
            'public readonly List<FireSpreadEvent> spreadLog = new List<FireSpreadEvent>();',
            'public readonly List<ExtinguishEvent> extinguishLog = new List<ExtinguishEvent>();',
            'public struct FireSpreadEvent', 'public float t;', 'public List<GridCoord> newFireCells;',
            'public List<GridCoord> newSmokeCells;', 'public struct ExtinguishEvent',
            'public GridCoord cell;', 'public int waterCost;'],
        'PlayerController.cs': ['public class PlayerController : MonoBehaviour',
            'public int hp;', 'public GridCoord cell;'],
        'WaterResourceSystem.cs': ['public class WaterResourceSystem : MonoBehaviour',
            'public int water;', 'public bool isSpraying;',
            'public readonly List<(GridCoord cell, int cost)> costLedger = new List<(GridCoord, int)>();'],
        'NpcRescueSystem.cs': ['public class NpcRescueSystem : MonoBehaviour',
            'public List<NpcInfo> npcs = new List<NpcInfo>();', 'public string carriedNpcId;',
            'public int rescuedCount;', 'public int casualtyCount;'],
        'RouteBlockSystem.cs': ['public class RouteBlockSystem : MonoBehaviour',
            'public bool isBlocked;', 'public GridCoord? nearestClearableDebris;'],
        'MechanicConfig.cs': ['public class MechanicConfig : ScriptableObject',
            'public int gridWidth = 20;', 'public int gridDepth = 16;',
            'public float fireSpreadPeriodSec = 4.0f;'],
    }
    refs={}
    for name,declarations in specs.items():
        path=project/'Assets/Mechanics'/name
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()/'Assets'):
            raise ValueError('Reviewed fire rescue source escaped: '+name)
        text=path.read_text()
        if not all(declaration in text for declaration in declarations):
            raise ValueError('Reviewed fire rescue public declarations changed: '+name)
        refs[str(path.relative_to(project))]=sha(path)
    fields='state timeRemaining currentCgKey cgPlayedC01 cgPlayedC02 cgPlayedC03 loseReason timeUsed smokeTestMode'.split()
    paths=[{'name':name,'path':name} for name in fields]
    nested=[('cells','fireGrid.cells'),('spreadLog','fireGrid.spreadLog'),
        ('extinguishLog','fireGrid.extinguishLog'),('playerHp','player.hp'),('playerCell','player.cell'),
        ('water','water.water'),('isSpraying','water.isSpraying'),('costLedger','water.costLedger'),
        ('npcs','npcs.npcs'),('carriedNpcId','npcs.carriedNpcId'),('rescuedCount','npcs.rescuedCount'),
        ('casualtyCount','npcs.casualtyCount'),('isBlocked','routeBlock.isBlocked'),
        ('nearestClearableDebris','routeBlock.nearestClearableDebris'),
        ('gridWidth','config.gridWidth'),('gridDepth','config.gridDepth'),
        ('fireSpreadPeriodSec','config.fireSpreadPeriodSec')]
    paths.extend({'name':name,'path':path} for name,path in nested)
    return ({'schema':'unity-functional-observer-contract.v2.public-fields',
        'provider_type':'G047.FireRescue.Mechanics.GameDirector',
        'required_fields':[row['name'] for row in paths], 'require_events':False,
        'public_field_paths':paths},refs)


def qualify(source, failed_judge):
    from .unity_recovery import qualify_capture
    source, failed_judge = Path(source).resolve(), Path(failed_judge).resolve()
    case = batch.read(source/'input_manifest.json')['entry']['id']
    if (case not in SUPPORTED
            or (source/'scores.json').exists() or (failed_judge/'scores.json').exists()
            or Path(batch.read(failed_judge/'recorded_capture_provenance.json')['source_attempt']).resolve() != source):
        raise ValueError('Requires supported unscored source and source-bound failed judge')
    qualify_capture(source)
    judgments = sorted((failed_judge/'judgments').glob('evidence_*.json'))
    rows = [row for p in judgments for row in batch.read(p)['rows']]
    failed = [row for row in rows if row.get('execution', {}).get('status') == 'HARNESS_ERROR']
    states = source/'background_record/take/state_trace.jsonl'
    extension = case == CASE and snapshot_extension(source)
    nested = case == CASE and nested_event_extension(source)
    if not failed or (case == CASE and not extension and not nested and not any('guard' in json.dumps(r, ensure_ascii=False).lower() or '守卫' in json.dumps(r, ensure_ascii=False) for r in failed)):
        raise ValueError('No demonstrated guard observer failure in accepted verdicts')
    accepted_bindings = []
    if case in PUBLIC_STATE_CASES:
        from .judge_invocation import response_for_judgment, _same_judgment
        for judgment in judgments:
            value = batch.read(judgment)
            if any(row.get('execution', {}).get('status') == 'HARNESS_ERROR' for row in value['rows']):
                response = response_for_judgment(failed_judge, judgment.stem)
                if not _same_judgment(batch.read(response), value['raw']):
                    raise ValueError('Observer failure differs from accepted original response')
                # The strictly selected successful invocation may be an explicit
                # retry sibling; preserve its accepted pointer and the failed
                # original transport files without assuming the original succeeded.
                call = response.parent
                accepted_bindings.extend([response, call/'accepted_response.json',
                    call/'invocation.json',call/'prompt.txt',call/'schema.json'])
                primary = failed_judge/'model_calls'/judgment.stem
                if primary.resolve() != call.resolve():
                    accepted_bindings.extend(path for path in primary.iterdir() if path.is_file())
        if not accepted_bindings:
            raise ValueError('No accepted source-bound observer failure')
        contract(source)
    if states.exists():
        observed_public = False
        observed_snapshot = False
        for line in states.open():
            row = json.loads(line)
            for provider, value in row.get('state', {}).items():
                if provider.endswith('.public_fields') and isinstance(value, dict):
                    observed_public = True
                    observed_snapshot |= 'SavedCheckpointSnapshot' in value
        if nested:
            event_failures = [r for r in failed
                if r.get('id','').endswith('.C2.tiered.11')
                and 'failed' in json.dumps(r,ensure_ascii=False)]
            events = source/'background_record/take/event_trace.jsonl'
            if (not event_failures or not observed_public or not observed_snapshot
                    or (source/'background_record/take/event_source_bindings.jsonl').exists()
                    or any(json.loads(line).get('source','').endswith('.World.Sim')
                        for line in events.read_text().splitlines() if line.strip())):
                raise ValueError('No demonstrated missing nested simulation event observation')
            prior_bindings = audit_binding(source)
            if not prior_bindings:
                raise ValueError('Prior public-field native lineage missing')
            from .judge_invocation import response_for_judgment, _same_judgment
            responses = []
            for judgment in judgments:
                value = batch.read(judgment)
                if any(row.get('execution',{}).get('status') == 'HARNESS_ERROR' for row in value['rows']):
                    response = response_for_judgment(failed_judge, judgment.stem)
                    if not _same_judgment(batch.read(response), value['raw']):
                        raise ValueError('Harness failure differs from accepted original response')
                    call = failed_judge/'model_calls'/judgment.stem
                    responses.extend([response,call/'accepted_response.json',call/'invocation.json',
                        call/'prompt.txt',call/'schema.json'])
            contract(source)
            observation = [states,events,source/'functional_observer_contract.json',source/RECEIPT,
                *map(Path,prior_bindings),*responses]
        elif extension:
            checkpoint_failures = [r for r in failed
                if r.get('id','').endswith('.C2.tiered.07')
                and any(word in json.dumps(r,ensure_ascii=False).lower()
                        for word in ('snapshot','快照'))]
            if not checkpoint_failures or not observed_public or observed_snapshot:
                raise ValueError('No accepted missing saved-checkpoint observer failure')
            # Revalidate the prior native repair rather than replacing its claim.
            prior_bindings = audit_binding(source)
            if not prior_bindings:
                raise ValueError('Prior public-field native lineage missing')
            contract(source)  # Require the actual authored public declaration.
            observation = [states, source/'functional_observer_contract.json', source/RECEIPT,
                           *map(Path, prior_bindings)]
        else:
            if observed_public:
                raise ValueError('Explicit field observation already exists; investigate rather than repeat take')
            observation = [states]
    else:
        report = source/'background_record/take/_editor_report.json'
        bindings = source/'background_record/take/state_source_bindings.jsonl'
        value = batch.read(report)
        rows = [json.loads(line) for line in bindings.read_text().splitlines() if line.strip()]
        if (case not in ({SOL_CASE,CARAVAN_CASE} | PUBLIC_STATE_CASES) or value.get('state_snapshots') != 0
                or value.get('channels',{}).get('states_available') is not False
                or not rows or any(row.get('sources') != [] for row in rows)):
            raise ValueError('Missing state file is not explained by original native observer diagnostics')
        observation = [report,bindings]
    files = [source/'background_record/verification.json', source/'background_record/runner_exit.json',
             *observation, *accepted_bindings, failed_judge/'recorded_capture_provenance.json', *judgments]
    return {str(p):sha(p) for p in files}


def audit_binding(root):
    root = Path(root).resolve()
    recorded = Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt']).resolve() \
        if (root/'recorded_capture_provenance.json').exists() else root
    receipt = recorded/RECEIPT
    if not receipt.exists():
        return {}
    value = batch.read(receipt)
    source, judge = Path(value['source_attempt']), Path(value['failed_judge'])
    if (value.get('version') != VERSION or source == recorded or source.parent != recorded.parent
            or value.get('plan_model_calls_added') != 0 or value.get('physical_actions_changed') is not False
            or value['qualification_sha256'] != qualify(source, judge)):
        raise ValueError('Public field repair lineage or failed-stage qualification changed')
    expected, refs = contract(source)
    if batch.read(recorded/'functional_observer_contract.json') != expected or value['public_source_sha256'] != refs:
        raise ValueError('Public field source contract changed')
    bindings = value['copied_bindings']
    if not {'sol_plan.json','input_manifest.json','input/pilot_rubric.json'} <= bindings.keys():
        raise ValueError('Missing immutable plan/input bindings')
    result = {str(receipt):sha(receipt), **value['qualification_sha256']}
    for name, digest in bindings.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid frozen relative path')
        for base in (source,recorded):
            if sha(base/relative) != digest:
                raise ValueError('Frozen input changed: '+str(base/relative))
            result[str(base/relative)] = digest
    for name in ('editor_acceptance','behavior_acceptance'):
        path = Path(value[name])
        if sha(path) != value[name+'_sha256']:
            raise ValueError('Native observer acceptance changed')
        result[str(path)] = sha(path)
    result[str(recorded/'functional_observer_contract.json')] = sha(recorded/'functional_observer_contract.json')
    return result


def prepare(source, failed_judge, acceptance, behavior):
    source = Path(source).resolve()
    qualification = qualify(source, failed_judge)
    case = batch.read(source/'input_manifest.json')['entry']['id']
    for receipt in source.parent.glob(case+'__public_field_observer_v1_*/'+RECEIPT):
        if batch.read(receipt)['source_attempt'] == str(source):
            raise ValueError('Source-bound repair already exists; resume preserved identity')
    expected, refs = contract(source)
    batch.verify_inputs(source)
    core12.verify_attempt(source,'unity3d')
    root = source.parent/(case+'__public_field_observer_v1_'+str(time.time_ns()))
    root.mkdir()
    names = ['input_manifest.json','input','model_calls','static_source_scores.json','static_code_scores.json',
             'static_existence.json','sol_plan.json','capture_route_contract.json','endpoint_conditions_receipt.json',
             'planning_retry_feedback.json','route_metadata_repair.json','planning_prompt_policy.json',
             'plan_normalization.json','planning_prompt_template.py','selection_provenance.json',
             'planning_prompt_transform.json','operation_report.md']
    bindings = {}
    for name in names:
        path = source/name
        if path.is_dir():
            # Partitioned static reuse writes its own strict origin receipt below.
            # Its model calls must be copied by that formal handoff only once.
            ignored = shutil.ignore_patterns('static_existence_output_*') if case == POLAR_CASE and name == 'model_calls' else None
            shutil.copytree(path,root/name,ignore=ignored)
            files = [p for p in path.rglob('*') if p.is_file()]
        elif path.is_file():
            shutil.copy2(path,root/name)
            files = [path]
        else:
            continue
        bindings.update({str(p.relative_to(source)):sha(p) for p in files})
    if case == POLAR_CASE:
        from .prepare_unity_recorded_judge import copy_static_judgment
        copy_static_judgment(source, root, batch.read(source/'input/pilot_rubric.json'))
    manifest = batch.read(source/'attempt_manifest.json')
    manifest.update(attempt_id=root.name,previous_attempt=str(source))
    dump(root/'attempt_manifest.json',manifest)
    dump(root/'functional_observer_contract.json',expected)
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'failed_judge':str(Path(failed_judge).resolve()),
         'qualification_sha256':qualification,'copied_bindings':bindings,'public_source_sha256':refs,
         'editor_acceptance':str(Path(acceptance).resolve()),'editor_acceptance_sha256':sha(acceptance),
         'behavior_acceptance':str(Path(behavior).resolve()),'behavior_acceptance_sha256':sha(behavior),
         'repair_kind':('nested-public-simulation-event-subscription' if nested_event_extension(source) else 'saved-checkpoint-public-contract-extension' if snapshot_extension(source) else 'authored-public-state-contract' if case in PUBLIC_STATE_CASES else 'initial-public-field-contract'),
         'reason':('Accepted C2.11 requires actual failed callback; subscribe authored World.Sim.OnEvent via explicit public fields. Preserve live fields, saved checkpoint, original exceptions and all old responses.' if nested_event_extension(source) else 'Accepted C2.07 verdict lacks saved snapshot; observe authored public World._lastSnapshot with existing native field reader, retaining prior live fields and all original errors.' if snapshot_extension(source) else 'Accepted HARNESS_ERROR demonstrates missing authored gameplay state; observe reviewed public fields with the existing native reader, preserving all actions and original failures.' if case in PUBLIC_STATE_CASES else 'Guard snapshot enum formatting throws; read existing public World.Sim.State fields independently. Original exception retained.' if case == CASE else 'Accepted execution verdicts demonstrate missing state observer; read existing authored public '+('CaravanApp.g' if case == CARAVAN_CASE else 'LampwickGame.s')+' fields. No event channel invented.'),
         'plan_model_calls_added':0,'physical_actions_changed':False,'created_unix':time.time()})
    audit_binding(root)
    batch.verify_inputs(root)
    core12.verify_attempt(root,'unity3d')
    return root
