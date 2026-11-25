using UnrealBuildTool;

public class A3GamePlayable : ModuleRules
{
    public A3GamePlayable(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore",
            "MediaAssets"
        });

        PrivateDependencyModuleNames.AddRange(new[]
        {
            "ApplicationCore",
            "AudioMixer",
            "Json",
            "RenderCore",
            "Networking",
            "Sockets",
            "Slate",
            "SlateCore"
        });
    }
}
