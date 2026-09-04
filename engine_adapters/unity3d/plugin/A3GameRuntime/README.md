# A3Game Runtime Framework

The Unity runtime framework for 3AGameFactory — the Unity equivalent of UE5's
`A3GamePlayable` C++ framework. It provides controllable-entity contracts,
in-memory session state management, and UDP input reception for AI-driven
game generation.

## Architecture

```
A3GameRuntime/
├── package.json
├── Runtime/
│   ├── A3GameRuntime.asmdef          # Assembly definition (UnityEngine only)
│   ├── A3GameControlMode.cs          # Control mode enum
│   ├── A3GameLocomotionState.cs      # Locomotion state enum
│   ├── A3GameRuntimeInputState.cs    # Input state struct
│   ├── A3GameEntitySpawnRequest.cs   # Entity spawn request struct
│   ├── A3GameParticipantInfo.cs      # Participant info struct
│   ├── A3GameControllerState.cs      # Controller state struct
│   ├── A3GameControlBinding.cs       # Control binding struct
│   ├── A3GameEntitySnapshot.cs       # Entity snapshot struct
│   ├── IA3GameControllableEntity.cs  # Controllable entity interface
│   ├── IA3GameEntityFactory.cs       # Entity factory interface
│   ├── IA3GameRuntimeMessageHandler.cs # Message handler interface
│   ├── A3GameIdentityComponent.cs    # Identity MonoBehaviour
│   ├── A3GameRuntimeEntityComponent.cs # Entity MonoBehaviour
│   ├── A3GameRuntimeSubsystem.cs     # Runtime coordinator singleton
│   ├── A3GameWorldSessionSubsystem.cs # Session state owner singleton
│   ├── A3GameRuntimeInputReceiver.cs # UDP input receiver (port 30030)
│   └── A3GameMediaDirector.cs       # Native audio/video CG/VFX bridge
└── Tests/
    └── A3GameRuntime.Tests.asmdef    # Test assembly definition
```

## Media director naming

The cross-engine logical component is `media_director`. Unity keeps the native
C# convention `A3GameMediaDirector.cs` with the public type
`A3GameMediaDirector`; do not rename it to `media_director.cs`, because the
MonoBehaviour file and class name should remain aligned. See the **Unity Media
Director** section in `<REPO_PATH>/agent_skills/engine_context/unity3d_api.md`
for the naming, ownership, pause, and evidence contract.

## Key Design Decisions

- **Assembly references UnityEngine only** — no game-specific assemblies.
  Generated gameplay code depends on this assembly; this assembly never
  depends on generated code.
- **MonoBehaviour-based** — uses Unity's component model, not UE5's
  UObject/Actor system.
- **Gameplay-owned movement** — the runtime component records locomotion and
  broadcasts normalized input; a generated controller or optional example
  owns collision, gravity, jumping, combat, and interaction.
- **UDP port 30030** — receives JSON datagrams from the Python
  `RuntimeUDPBridge`.
- **In-memory session state** — mirrors the Python `RuntimeSessionService`
  with `Dictionary`-based participant, controller, entity, binding, and
  input tracking.

## Message Types

The `A3GameRuntimeInputReceiver` handles these UDP JSON message types:

| Type | Description |
|---|---|
| `sync_session` | Create/reconnect a participant and bind a controller to its entity |
| `input_state` | Apply input to a bound entity |
| `participant_offline` | Mark a participant and its controllers offline |
| `destroy_entity` | Remove an entity and clean up associated state |

Unknown message types are forwarded to registered `IA3GameRuntimeMessageHandler`
instances via `A3GameRuntimeSubsystem.DispatchExtensionMessage`.

## Usage

1. Add `A3GameRuntime` and `A3GameWorldSessionSubsystem` to a GameObject in
   your scene (or let them auto-create).
2. Register an `IA3GameEntityFactory` implementation with the runtime
   subsystem to customize entity creation.
3. The `A3GameRuntimeInputReceiver` automatically starts listening on UDP
   port 30030 when enabled.
4. Use `A3GameWorldSessionSubsystem.Instance` to query session state and
   snapshots.
