using UnrealBuildTool;
public class SnakeDemo : ModuleRules {
    public SnakeDemo(ReadOnlyTargetRules Target) : base(Target) {
        PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[]{"Core","CoreUObject","Engine","InputCore","Json"});
    }
}
