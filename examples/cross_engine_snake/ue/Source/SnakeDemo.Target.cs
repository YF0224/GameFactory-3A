using UnrealBuildTool;
using System.Collections.Generic;
public class SnakeDemoTarget : TargetRules {
    public SnakeDemoTarget(TargetInfo Target) : base(Target) {
        Type=TargetType.Game;
        DefaultBuildSettings=BuildSettingsVersion.V5;
        IncludeOrderVersion=EngineIncludeOrderVersion.Unreal5_4;
        ExtraModuleNames.Add("SnakeDemo");
    }
}
