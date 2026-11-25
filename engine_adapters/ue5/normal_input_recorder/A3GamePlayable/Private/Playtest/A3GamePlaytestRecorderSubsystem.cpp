#include "Playtest/A3GamePlaytestRecorderSubsystem.h"

#include "HAL/PlatformFileManager.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/DefaultValueHelper.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "UnrealClient.h"
#include "Engine/World.h"
#include "AudioMixerBlueprintLibrary.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/DateTime.h"
#include "Misc/CoreDelegates.h"
#include "CoreGlobals.h"
#include "Common/UdpSocketBuilder.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/SlateApplication.h"
#include "InputKeyEventArgs.h"
#include "Input/Events.h"
#include "Layout/WidgetPath.h"
#include "Widgets/SViewport.h"
#include "Widgets/SWindow.h"
#include "Framework/Application/SlateUser.h"
#include "InputCoreTypes.h"
#include "Misc/App.h"
#include "Animation/SkeletalMeshActor.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SceneCapture2D.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/TextureRenderTarget2D.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "Slate/SceneViewport.h"
#include "Misc/Paths.h"
#if PLATFORM_MAC
#include <dlfcn.h>
#endif
#include "UObject/UObjectIterator.h"
#include "UObject/UnrealType.h"
#include "Misc/PackageName.h"
#include "UObject/UObjectIterator.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "Camera/PlayerCameraManager.h"

// Background recording (opt-in -A3BackgroundFocus): like Unity's runInBackground, the game process
// reports focus to itself so focus-gated game logic keeps running while the recording window is in
// the background. No window activation, no OS input.
static bool A3BackgroundAlwaysFocused() { return true; }

// ---- End-of-take asset photos (opt-in -A3AssetShots=<plan.json>) ----
namespace
{
struct FA3ShotView { const TCHAR* Name; float Yaw; float Pitch; };
const FA3ShotView GA3Views[] = {
    {TEXT("front"), 180.f, 10.f}, {TEXT("right"), 270.f, 10.f}, {TEXT("back"), 0.f, 10.f},
    {TEXT("three_quarter_top"), 135.f, 40.f}};

FString PackageOf(const UObject* Object)
{
    return Object ? Object->GetOutermost()->GetName() : FString();
}

UObject* LoadPackageAsset(const FString& Package)
{
    const FString Path = Package + TEXT(".") + FPackageName::GetShortName(Package);
    return StaticLoadObject(UObject::StaticClass(), nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
}

bool SavePng(UTextureRenderTarget2D* Target, const FString& File)
{
    FTextureRenderTargetResource* Resource = Target->GameThread_GetRenderTargetResource();
    if (!Resource) return false;
    TArray<FColor> Pixels;
    if (!Resource->ReadPixels(Pixels) || Pixels.Num() != Target->SizeX * Target->SizeY) return false;
    for (FColor& P : Pixels) P.A = 255;
    TArray64<uint8> Png;
    FImageUtils::PNGCompressImageArray(Target->SizeX, Target->SizeY,
        TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
    return Png.Num() > 0 && FFileHelper::SaveArrayToFile(Png, *File);
}
}  // namespace

static void A3CaptureAssetShots(UWorld* World, const FString& PlanPath, const FString& OutDir)
{
    TArray<TSharedPtr<FJsonValue>> Results;
    FString Text;
    TSharedPtr<FJsonObject> Plan;
    if (!World || !FFileHelper::LoadFileToString(Text, *PlanPath) ||
        !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Plan) || !Plan.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("A3 asset shots: invalid plan %s"), *PlanPath);
        return;
    }
    IFileManager::Get().MakeDirectory(*OutDir, true);
    const int32 Size = Plan->HasField(TEXT("size")) ? static_cast<int32>(Plan->GetNumberField(TEXT("size"))) : 640;

    // Time cap (a slow / log-flooded game must not push the take past the host's exit deadline):
    // assets not reached in time are reported as not shot (not evaluable), never as failed.
    const double ShotsStart = FPlatformTime::Seconds();
    const double ShotsBudget = Plan->HasField(TEXT("max_seconds")) ? Plan->GetNumberField(TEXT("max_seconds")) : 75.0;
    for (const TSharedPtr<FJsonValue>& AssetValue : Plan->GetArrayField(TEXT("assets")))
    {
        const TSharedPtr<FJsonObject> Asset = AssetValue->AsObject();
        const FString Id = Asset->GetStringField(TEXT("id"));
        if (FPlatformTime::Seconds() - ShotsStart > ShotsBudget)
        {
            auto Skip = MakeShared<FJsonObject>();
            Skip->SetStringField(TEXT("id"), Id);
            Skip->SetStringField(TEXT("error"), TEXT("asset shot time cap reached (game too slow); not shot"));
            Results.Add(MakeShared<FJsonValueObject>(Skip));
            continue;
        }
        TSet<FString> Packages;
        for (const TSharedPtr<FJsonValue>& P : Asset->GetArrayField(TEXT("packages"))) Packages.Add(P->AsString());

        auto Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("id"), Id);
        TArray<UPrimitiveComponent*> Components;
        for (TObjectIterator<UStaticMeshComponent> It; It; ++It)
            if (It->GetWorld() == World && It->IsRegistered() && Packages.Contains(PackageOf(It->GetStaticMesh())))
                Components.Add(*It);
        for (TObjectIterator<USkeletalMeshComponent> It; It; ++It)
            if (It->GetWorld() == World && It->IsRegistered() && Packages.Contains(PackageOf(It->GetSkeletalMeshAsset())))
                Components.Add(*It);
        Row->SetNumberField(TEXT("placed_components"), Components.Num());
        // Keep what the player can actually see: drop permanently hidden components, then frame one
        // copy near the player (objects) or the scene pieces around the player (scenes) - never the
        // union of copies spread over the whole level.
        TArray<UPrimitiveComponent*> Visible;
        for (UPrimitiveComponent* C : Components)
        {
            const AActor* Owner = C->GetOwner();
            if (C->IsVisible() && !C->bHiddenInGame && !(Owner && Owner->IsHidden())) Visible.Add(C);
        }
        Row->SetNumberField(TEXT("visible_components"), Visible.Num());
        // Placement is decided by existence in the running scene, not by visibility at this moment
        // (e.g. a cinematic hides the rider at take end): hidden placed components are unhidden for the
        // shot only and restored afterwards.
        TArray<TPair<UPrimitiveComponent*, bool>> Restore;
        TArray<TPair<AActor*, bool>> RestoreActors;
        if (Visible.Num() == 0 && Components.Num() > 0)
        {
            Row->SetBoolField(TEXT("hidden_at_capture_unhidden_for_shot"), true);
            for (UPrimitiveComponent* C : Components)
            {
                Restore.Add(TPair<UPrimitiveComponent*, bool>(C, C->bHiddenInGame != 0));
                C->SetHiddenInGame(false);
                C->SetVisibility(true);
                if (AActor* Owner = C->GetOwner()) { RestoreActors.Add(TPair<AActor*, bool>(Owner, Owner->IsHidden())); Owner->SetActorHiddenInGame(false); }
            }
        }
        else
            Components = Visible;
        FVector Focus = FVector::ZeroVector;
        if (APlayerController* PC = World->GetFirstPlayerController())
            Focus = PC->GetPawn() ? PC->GetPawn()->GetActorLocation()
                  : (PC->PlayerCameraManager ? PC->PlayerCameraManager->GetCameraLocation() : FVector::ZeroVector);
        if (Components.Num() > 0)
        {
            const bool bScene = Asset->GetStringField(TEXT("kind")) == TEXT("3d_scene");
            if (bScene)
            {
                TArray<UPrimitiveComponent*> Near;
                const float R = 8000.f;          // ~80 m around the player
                for (UPrimitiveComponent* C : Components)
                    if (C->Bounds.GetBox().ComputeSquaredDistanceToPoint(Focus) <= R * R) Near.Add(C);
                if (Near.Num() == 0)
                {
                    UPrimitiveComponent* Closest = Components[0];
                    for (UPrimitiveComponent* C : Components)
                        if (C->Bounds.GetBox().ComputeSquaredDistanceToPoint(Focus) <
                            Closest->Bounds.GetBox().ComputeSquaredDistanceToPoint(Focus)) Closest = C;
                    const FVector At = Closest->Bounds.Origin;
                    for (UPrimitiveComponent* C : Components)
                        if (C->Bounds.GetBox().ComputeSquaredDistanceToPoint(At) <= R * R) Near.Add(C);
                }
                Row->SetStringField(TEXT("framing"), TEXT("scene pieces within ~80 m of the player"));
                Components = Near;
            }
            else
            {
                // One copy = the component nearest the player plus the components of the same actor
                // that touch it (a multi-part object); far-apart instances are other copies.
                UPrimitiveComponent* Nearest = Components[0];
                for (UPrimitiveComponent* C : Components)
                    if (C->Bounds.GetBox().ComputeSquaredDistanceToPoint(Focus) <
                        Nearest->Bounds.GetBox().ComputeSquaredDistanceToPoint(Focus)) Nearest = C;
                const FBox Seed = Nearest->Bounds.GetBox().ExpandBy(Nearest->Bounds.SphereRadius);
                TArray<UPrimitiveComponent*> Copy;
                for (UPrimitiveComponent* C : Components)
                    if (C == Nearest || (C->GetOwner() == Nearest->GetOwner() && Seed.Intersect(C->Bounds.GetBox())))
                        Copy.Add(C);
                Row->SetNumberField(TEXT("placed_copies"), Components.Num() - Copy.Num() + 1);
                Row->SetStringField(TEXT("framing"), TEXT("the placed copy nearest the player"));
                Components = Copy;
            }
        }

        // Imported but not placed: spawn one temporary copy in the same level (marked "spawned").
        TArray<AActor*> Spawned;
        if (Components.Num() == 0)
        {
            for (const FString& Package : Packages)
            {
                UObject* Mesh = LoadPackageAsset(Package);
                FActorSpawnParameters Params;
                Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
                const FVector Where = Focus + FVector(0.f, 0.f, 3000.f + 2000.f * Spawned.Num());
                if (UStaticMesh* Static = Cast<UStaticMesh>(Mesh))
                {
                    AStaticMeshActor* A = World->SpawnActor<AStaticMeshActor>(Where, FRotator::ZeroRotator, Params);
                    A->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
                    A->GetStaticMeshComponent()->SetStaticMesh(Static);
                    Spawned.Add(A);
                    Components.Add(A->GetStaticMeshComponent());
                }
                else if (USkeletalMesh* Skeletal = Cast<USkeletalMesh>(Mesh))
                {
                    ASkeletalMeshActor* A = World->SpawnActor<ASkeletalMeshActor>(Where, FRotator::ZeroRotator, Params);
                    A->GetSkeletalMeshComponent()->SetSkeletalMeshAsset(Skeletal);
                    Spawned.Add(A);
                    Components.Add(A->GetSkeletalMeshComponent());
                }
            }
        }
        Row->SetBoolField(TEXT("spawned"), Spawned.Num() > 0);
        Row->SetNumberField(TEXT("components"), Components.Num());

        for (UPrimitiveComponent* C : Components) { C->UpdateComponentToWorld(); C->UpdateBounds(); }
        FBox Bounds(ForceInit);
        for (UPrimitiveComponent* C : Components) Bounds += C->Bounds.GetBox();
        // A scene mesh can span the whole level: frame the part around the player.
        if (Asset->GetStringField(TEXT("kind")) == TEXT("3d_scene") && Bounds.IsValid && Bounds.GetExtent().Size() > 8000.f)
        {
            const FVector Anchor = Bounds.GetClosestPointTo(Focus);   // the part of the scene nearest the player
            const FBox Around(Anchor - FVector(8000.f, 8000.f, 4000.f), Anchor + FVector(8000.f, 8000.f, 4000.f));
            const FBox Clipped = Bounds.Overlap(Around);
            if (Clipped.IsValid && Clipped.GetVolume() > 0.f) { Bounds = Clipped; Row->SetBoolField(TEXT("clipped_to_player_area"), true); }
        }
        if (Components.Num() == 0 || !Bounds.IsValid)
        {
            Row->SetStringField(TEXT("error"), TEXT("no mesh component found or loadable for this asset"));
            Results.Add(MakeShared<FJsonValueObject>(Row));
            for (AActor* A : Spawned) A->Destroy();
            continue;
        }

        ASceneCapture2D* CaptureActor = World->SpawnActor<ASceneCapture2D>();
        USceneCaptureComponent2D* Capture = CaptureActor->GetCaptureComponent2D();
        UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>();
        Target->ClearColor = FLinearColor(0.20f, 0.22f, 0.26f);
        Target->InitCustomFormat(Size, Size, PF_B8G8R8A8, false);
        Capture->TextureTarget = Target;
        Capture->bCaptureEveryFrame = false;
        Capture->bCaptureOnMovement = false;
        Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
        Capture->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
        for (UPrimitiveComponent* C : Components) Capture->ShowOnlyComponents.Add(C);
        Capture->FOVAngle = 35.f;
        const FVector Center = Bounds.GetCenter();
        const float Radius = FMath::Max(Bounds.GetExtent().Size(), 1.f);
        const float Distance = Radius / FMath::Sin(FMath::DegreesToRadians(Capture->FOVAngle * 0.5f)) * 1.05f;

        TArray<TSharedPtr<FJsonValue>> Files;
        // Placed in the running scene -> Game View (the level's lighting / post-processing, what the
        // player sees). Imported but not placed (spawned copy) -> Neutral View (unlit material colours).
        const TCHAR* Mode = Spawned.Num() > 0 ? TEXT("neutral") : TEXT("game");
        Row->SetStringField(TEXT("view_mode"), Mode);
        {
            const bool bGame = FCString::Strcmp(Mode, TEXT("game")) == 0;
            Capture->ShowFlags.SetLighting(bGame);
            for (const FA3ShotView& View : GA3Views)
            {
                const FVector Dir = FRotator(-View.Pitch, View.Yaw, 0.f).Vector();   // camera looks along Dir
                CaptureActor->SetActorLocationAndRotation(Center - Dir * Distance, Dir.Rotation());
                Capture->CaptureScene();
                const FString File = FPaths::Combine(OutDir, FString::Printf(TEXT("%s__%s__%s.png"), *Id, Mode, View.Name));
                auto F = MakeShared<FJsonObject>();
                F->SetStringField(TEXT("mode"), Mode);
                F->SetStringField(TEXT("view"), View.Name);
                F->SetStringField(TEXT("file"), FPaths::GetCleanFilename(File));
                F->SetBoolField(TEXT("ok"), SavePng(Target, File));
                Files.Add(MakeShared<FJsonValueObject>(F));
            }
        }
        Row->SetArrayField(TEXT("files"), Files);
        Row->SetStringField(TEXT("bounds"), Bounds.ToString());
        CaptureActor->Destroy();
        for (AActor* A : Spawned) A->Destroy();
        for (const auto& R : Restore) R.Key->SetHiddenInGame(R.Value);
        for (const auto& R : RestoreActors) R.Key->SetActorHiddenInGame(R.Value);
        Results.Add(MakeShared<FJsonValueObject>(Row));
    }
    TArray<TSharedPtr<FJsonValue>> Skeletal;
    for (TObjectIterator<USkeletalMeshComponent> It; It; ++It)
        if (It->GetWorld() == World && It->IsRegistered() && It->IsVisible() && !It->bHiddenInGame && Skeletal.Num() < 30)
            Skeletal.Add(MakeShared<FJsonValueString>(FString::Printf(TEXT("%s | %s"),
                It->GetOwner() ? *It->GetOwner()->GetName() : TEXT("-"), *PackageOf(It->GetSkeletalMeshAsset()))));
    auto Report = MakeShared<FJsonObject>();
    Report->SetArrayField(TEXT("visible_skeletal_meshes"), Skeletal);
    Report->SetStringField(TEXT("version"), TEXT("a3-asset-shots.v1"));
    Report->SetArrayField(TEXT("assets"), Results);
    FString Json;
    FJsonSerializer::Serialize(Report, TJsonWriterFactory<>::Create(&Json));
    FFileHelper::SaveStringToFile(Json, *FPaths::Combine(OutDir, TEXT("asset_shots.json")));
    UE_LOG(LogTemp, Display, TEXT("A3 asset shots: %d assets -> %s"), Results.Num(), *OutDir);
}



// ---- Event-triggered frames (opt-in -A3EventFrames) ----
// The game's own log lines (LogTemp / LogBlueprintUserMessages / LogScript, not the recorder's "A3 " lines)
// queue extra real screenshots at +0 / +250 / +700 ms after the line, so short effects and results that
// follow a game event are on record. Scheduled frames always keep priority; extra frames carry
// sample_at_ms = -1 and capture_ids ["event/<event_ms>/+<offset>"]. Nothing in the game is changed.
namespace A3EventFrames
{
    static FCriticalSection Lock;
    static TArray<double> Pending;          // platform seconds of game log lines not yet scheduled
    static bool bActive = false;
    struct FDevice : public FOutputDevice
    {
        virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
        {
            if (!bActive || !V) return;
            static const FName Temp(TEXT("LogTemp")), Bp(TEXT("LogBlueprintUserMessages")), Script(TEXT("LogScript"));
            if (Category != Temp && Category != Bp && Category != Script) return;
            if (FCString::Strncmp(V, TEXT("A3 "), 3) == 0) return;
            FScopeLock Guard(&Lock);
            if (Pending.Num() < 256) Pending.Add(FPlatformTime::Seconds());
        }
        virtual bool CanBeUsedOnAnyThread() const override { return true; }
    };
    static FDevice Device;
    static bool bRegistered = false;
    static TArray<TPair<double, FString>> Due;   // (take ms, capture id), ascending
    static int32 Taken = 0;
    static bool bPendingIsEvent = false;   // the in-flight screenshot is an event frame (own index / folder)
    static double ScheduledLagMs = 0.0;     // how late the last scheduled frame was taken (ms)
    static const int32 MaxFrames = 400;
    static double LastEventMs = -1e9;
    static void Start()
    {
        if (!bRegistered && GLog) { GLog->AddOutputDevice(&Device); bRegistered = true; }
        FScopeLock Guard(&Lock); Pending.Reset(); Due.Reset(); Taken = 0; LastEventMs = -1e9; ScheduledLagMs = 0.0; bActive = true;
    }
    static void Stop()
    {
        bActive = false;
        if (bRegistered && GLog) { GLog->RemoveOutputDevice(&Device); bRegistered = false; }
    }
    static void Drain(double StartedAt)
    {
        TArray<double> Now;
        { FScopeLock Guard(&Lock); Now = MoveTemp(Pending); Pending.Reset(); }
        for (double At : Now)
        {
            const double Ms = (At - StartedAt) * 1000.0;
            if (Ms < 0.0 || Ms - LastEventMs < 120.0) continue;      // a burst of lines = one event
            LastEventMs = Ms;
            for (int32 Off : {0, 250, 700})
                Due.Add(TPair<double, FString>(Ms + Off, FString::Printf(TEXT("event/%.0f/+%d"), Ms, Off)));
        }
        Due.Sort([](const TPair<double, FString>& A, const TPair<double, FString>& B) { return A.Key < B.Key; });
    }
}

// ---- State entry (opt-in -A3StateEntry=<json>, state-conditioned evaluation) ----
// {"calls":[{"object":"UVolcanoMechanic","member":"StartSection","kind":"method","args":["2"]}]}
// Live instances of the UCLASS type in this world; the member is reached only through UE reflection
// (UFUNCTION -> ProcessEvent, UPROPERTY -> ImportText). Anything else is reported as not reachable.
namespace A3Entry
{
    static TArray<TSharedPtr<FJsonObject>> Pending;   // calls not yet run, in plan order
    static TArray<TSharedPtr<FJsonValue>> Rows;
    static FString Out;
    static double StartSec = 0.0;
    static bool bActive = false;
}

static TSharedPtr<FJsonObject> A3RunOneEntryCall(UWorld* World, const TSharedPtr<FJsonObject>& Call)
{
        const TSharedPtr<FJsonObject>& C = Call;
        FString Object = C->GetStringField(TEXT("object")), Member = C->GetStringField(TEXT("member"));
        FString Kind = C->HasField(TEXT("kind")) ? C->GetStringField(TEXT("kind")) : TEXT("method");
        TArray<FString> Args;
        if (C->HasField(TEXT("args"))) for (const TSharedPtr<FJsonValue>& A : C->GetArrayField(TEXT("args"))) Args.Add(A->AsString());
        FString Error, Route; int32 Targets = 0;
        FString Bare = Object;
        if (Bare.Len() > 1 && (Bare[0] == 'U' || Bare[0] == 'A') && FChar::IsUpper(Bare[1])) Bare = Bare.Mid(1);
        UClass* Cls = FindFirstObject<UClass>(*Bare, EFindFirstObjectOptions::NativeFirst);
        if (!Cls) Cls = FindFirstObject<UClass>(*Object, EFindFirstObjectOptions::NativeFirst);
        TArray<UObject*> Live;
        if (Cls)
            for (TObjectIterator<UObject> It; It; ++It)
                if (It->IsA(Cls) && !It->IsTemplate() && It->GetWorld() == World) Live.Add(*It);
        if (!Cls) Error = TEXT("class not found by reflection (needs UCLASS): ") + Object;
        else if (Live.Num() == 0) Error = TEXT("no live instance in this world: ") + Object;
        else if (Kind == TEXT("field"))
        {
            FProperty* Prop = Cls->FindPropertyByName(FName(*Member));
            if (!Prop) Error = TEXT("field not reachable (needs UPROPERTY): ") + Member;
            else
            {
                Route = TEXT("uproperty");
                for (UObject* O : Live)
                    if (Prop->ImportText_InContainer(Args.Num() ? *Args[0] : TEXT(""), O, O, PPF_None)) ++Targets;
                if (!Targets) Error = TEXT("value not accepted by the property");
            }
        }
        else if (UFunction* Fn = Cls->FindFunctionByName(FName(*Member)))
        {
            Route = TEXT("ufunction");
            const int32 Size = FMath::Max(1, (int32)Fn->ParmsSize);
            for (UObject* O : Live)
            {
                TArray<uint8> Buf; Buf.SetNumZeroed(Size);
                int32 I = 0; bool Ok = true;
                for (TFieldIterator<FProperty> P(Fn); P && (P->PropertyFlags & CPF_Parm); ++P)
                {
                    P->InitializeValue_InContainer(Buf.GetData());
                    if (!(P->PropertyFlags & CPF_ReturnParm) && I < Args.Num())
                        Ok &= P->ImportText_InContainer(*Args[I++], Buf.GetData(), nullptr, PPF_None) != nullptr;
                }
                if (Ok) { O->ProcessEvent(Fn, Buf.GetData()); ++Targets; } else Error = TEXT("argument not accepted");
                for (TFieldIterator<FProperty> P(Fn); P && (P->PropertyFlags & CPF_Parm); ++P) P->DestroyValue_InContainer(Buf.GetData());
            }
        }
        else if (C->HasField(TEXT("symbol")) && C->HasField(TEXT("image")) && C->HasField(TEXT("sig")))
        {
            // Native route (user-authorized 2026-11-11): a plain C++ method of the game's OWN class, resolved by the
            // host from the delivered header (scalar return / parameters only) to its symbol in the game's module.
            // Safeguards: the image must be a module of this project (under the project's Binaries folder, never
            // the engine), already loaded by the game; the symbol is looked up only in that image.
#if PLATFORM_MAC
            const FString Image = FPaths::ConvertRelativePathToFull(C->GetStringField(TEXT("image")));
            // a module of THIS project: its Binaries folder or one of its own plugins' Binaries (never the engine, never
            // the evaluation recorder plugin)
            const FString ProjectBin = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
            const bool bRecorderImage = FPaths::ConvertRelativePathToFull(C->GetStringField(TEXT("image"))).Contains(TEXT("/A3GamePlayable/"));
            const FString Symbol = C->GetStringField(TEXT("symbol")), Sig = C->GetStringField(TEXT("sig"));
            void* Handle = Image.StartsWith(ProjectBin) ? dlopen(TCHAR_TO_UTF8(*Image), RTLD_LAZY | RTLD_NOLOAD) : nullptr;
            void* Addr = Handle ? dlsym(Handle, TCHAR_TO_UTF8(*Symbol)) : nullptr;
            Dl_info Info;
            const bool bOwnImage = Addr && dladdr(Addr, &Info) && Info.dli_fname &&
                FPaths::ConvertRelativePathToFull(UTF8_TO_TCHAR(Info.dli_fname)).StartsWith(ProjectBin);
            if (!Image.StartsWith(ProjectBin) || !Image.Contains(TEXT("/Binaries/")) || bRecorderImage)
                Error = TEXT("native image is not a game module of this project: ") + Image;
            else if (!Handle) Error = TEXT("game module not loaded: ") + Image;
            else if (!Addr || !bOwnImage) Error = TEXT("symbol not found in the game module: ") + Symbol;
            else
            {
                Route = TEXT("native_symbol");
                const bool bStatic = Sig.StartsWith(TEXT("S:"));
                const FString P = Sig.Mid(2);
                auto I = [&](int32 K) { return FCString::Atoi(*Args[K]); };
                auto Fl = [&](int32 K) { return FCString::Atof(*Args[K]); };
                auto D = [&](int32 K) { return (double)FCString::Atod(*Args[K]); };
                auto Bo = [&](int32 K) { return Args[K] == TEXT("1") || Args[K].Equals(TEXT("true"), ESearchCase::IgnoreCase); };
                if (Args.Num() != P.Len()) Error = TEXT("argument count does not match the declared signature");
                else if (P.Len() > 3) Error = TEXT("more than 3 parameters is not supported");
                const TArray<UObject*> TargetObjs = bStatic ? TArray<UObject*>{nullptr} : Live;
                for (UObject* O : TargetObjs)
                {
                    if (!Error.IsEmpty()) break;
                    // Itanium ABI: non-virtual member = function with 'this' first; scalar args in registers.
                    if (P == TEXT("")) { if (bStatic) ((void(*)())Addr)(); else ((void(*)(UObject*))Addr)(O); }
                    else if (P == TEXT("i")) { if (bStatic) ((void(*)(int32))Addr)(I(0)); else ((void(*)(UObject*, int32))Addr)(O, I(0)); }
                    else if (P == TEXT("f")) { if (bStatic) ((void(*)(float))Addr)(Fl(0)); else ((void(*)(UObject*, float))Addr)(O, Fl(0)); }
                    else if (P == TEXT("d")) { if (bStatic) ((void(*)(double))Addr)(D(0)); else ((void(*)(UObject*, double))Addr)(O, D(0)); }
                    else if (P == TEXT("b")) { if (bStatic) ((void(*)(bool))Addr)(Bo(0)); else ((void(*)(UObject*, bool))Addr)(O, Bo(0)); }
                    else if (P == TEXT("h")) { if (bStatic) ((void(*)(uint8))Addr)((uint8)I(0)); else ((void(*)(UObject*, uint8))Addr)(O, (uint8)I(0)); }
                    else if (P == TEXT("ii")) { if (bStatic) ((void(*)(int32,int32))Addr)(I(0),I(1)); else ((void(*)(UObject*,int32,int32))Addr)(O,I(0),I(1)); }
                    else if (P == TEXT("if")) { if (bStatic) ((void(*)(int32,float))Addr)(I(0),Fl(1)); else ((void(*)(UObject*,int32,float))Addr)(O,I(0),Fl(1)); }
                    else if (P == TEXT("fi")) { if (bStatic) ((void(*)(float,int32))Addr)(Fl(0),I(1)); else ((void(*)(UObject*,float,int32))Addr)(O,Fl(0),I(1)); }
                    else if (P == TEXT("ff")) { if (bStatic) ((void(*)(float,float))Addr)(Fl(0),Fl(1)); else ((void(*)(UObject*,float,float))Addr)(O,Fl(0),Fl(1)); }
                    else if (P == TEXT("ib")) { if (bStatic) ((void(*)(int32,bool))Addr)(I(0),Bo(1)); else ((void(*)(UObject*,int32,bool))Addr)(O,I(0),Bo(1)); }
                    else if (P == TEXT("bi")) { if (bStatic) ((void(*)(bool,int32))Addr)(Bo(0),I(1)); else ((void(*)(UObject*,bool,int32))Addr)(O,Bo(0),I(1)); }
                    // const FString& parameters (passed as a pointer to a live FString)
                    else if (P == TEXT("s")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&))Addr)(A0); else ((void(*)(UObject*,const FString&))Addr)(O,A0); }
                    else if (P == TEXT("ss")) { const FString A0 = Args[0], A1 = Args[1]; if (bStatic) ((void(*)(const FString&,const FString&))Addr)(A0,A1); else ((void(*)(UObject*,const FString&,const FString&))Addr)(O,A0,A1); }
                    else if (P == TEXT("si")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&,int32))Addr)(A0,I(1)); else ((void(*)(UObject*,const FString&,int32))Addr)(O,A0,I(1)); }
                    else if (P == TEXT("is")) { const FString A1 = Args[1]; if (bStatic) ((void(*)(int32,const FString&))Addr)(I(0),A1); else ((void(*)(UObject*,int32,const FString&))Addr)(O,I(0),A1); }
                    else if (P == TEXT("sf")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&,float))Addr)(A0,Fl(1)); else ((void(*)(UObject*,const FString&,float))Addr)(O,A0,Fl(1)); }
                    // three parameters (string first or numbers only)
                    else if (P == TEXT("sii")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&,int32,int32))Addr)(A0,I(1),I(2)); else ((void(*)(UObject*,const FString&,int32,int32))Addr)(O,A0,I(1),I(2)); }
                    else if (P == TEXT("sif")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&,int32,float))Addr)(A0,I(1),Fl(2)); else ((void(*)(UObject*,const FString&,int32,float))Addr)(O,A0,I(1),Fl(2)); }
                    else if (P == TEXT("sib")) { const FString A0 = Args[0]; if (bStatic) ((void(*)(const FString&,int32,bool))Addr)(A0,I(1),Bo(2)); else ((void(*)(UObject*,const FString&,int32,bool))Addr)(O,A0,I(1),Bo(2)); }
                    else if (P == TEXT("ssi")) { const FString A0 = Args[0], A1 = Args[1]; if (bStatic) ((void(*)(const FString&,const FString&,int32))Addr)(A0,A1,I(2)); else ((void(*)(UObject*,const FString&,const FString&,int32))Addr)(O,A0,A1,I(2)); }
                    else if (P == TEXT("iii")) { if (bStatic) ((void(*)(int32,int32,int32))Addr)(I(0),I(1),I(2)); else ((void(*)(UObject*,int32,int32,int32))Addr)(O,I(0),I(1),I(2)); }
                    else if (P == TEXT("fff")) { if (bStatic) ((void(*)(float,float,float))Addr)(Fl(0),Fl(1),Fl(2)); else ((void(*)(UObject*,float,float,float))Addr)(O,Fl(0),Fl(1),Fl(2)); }
                    else if (P == TEXT("iif")) { if (bStatic) ((void(*)(int32,int32,float))Addr)(I(0),I(1),Fl(2)); else ((void(*)(UObject*,int32,int32,float))Addr)(O,I(0),I(1),Fl(2)); }
                    else { Error = TEXT("unsupported native signature ") + Sig; break; }
                    ++Targets;
                }
            }
#else
            Error = TEXT("native route is only available on Mac");
#endif
        }
        else Error = TEXT("method not reachable (needs UFUNCTION or a resolvable native method): ") + Member;
        TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
        R->SetStringField(TEXT("object"), Object); R->SetStringField(TEXT("member"), Member);
        R->SetStringField(TEXT("kind"), Kind); R->SetStringField(TEXT("route"), Route);
        R->SetNumberField(TEXT("targets"), Targets);
        R->SetBoolField(TEXT("ok"), Error.IsEmpty() && Targets > 0); R->SetStringField(TEXT("error"), Error);
        UE_LOG(LogTemp, Display, TEXT("A3 state entry call %s.%s route=%s targets=%d %s"), *Object, *Member, *Route, Targets, *Error);
        R->SetNumberField(TEXT("at_ms"), C->HasField(TEXT("at_ms")) ? C->GetNumberField(TEXT("at_ms")) : 0.0);
        R->SetNumberField(TEXT("t_ms"), (FPlatformTime::Seconds() - A3Entry::StartSec) * 1000.0);
        return R;
}

static void A3EntryTick(UWorld* World)
{
    // Timed state-entry / direct-trigger calls: each runs once its at_ms (after the take start) is reached.
    if (!A3Entry::bActive || !World) return;
    const double ElapsedMs = (FPlatformTime::Seconds() - A3Entry::StartSec) * 1000.0;
    bool bRan = false;
    while (A3Entry::Pending.Num() > 0)
    {
        const TSharedPtr<FJsonObject> Next = A3Entry::Pending[0];
        const double At = Next->HasField(TEXT("at_ms")) ? Next->GetNumberField(TEXT("at_ms")) : 0.0;
        if (At > ElapsedMs) break;
        A3Entry::Pending.RemoveAt(0);
        A3Entry::Rows.Add(MakeShared<FJsonValueObject>(A3RunOneEntryCall(World, Next)));
        bRan = true;
    }
    if (!bRan) return;
    TSharedPtr<FJsonObject> OutObj = MakeShared<FJsonObject>();
    OutObj->SetNumberField(TEXT("at_ms"), 0.0);
    OutObj->SetNumberField(TEXT("pending"), A3Entry::Pending.Num());
    OutObj->SetArrayField(TEXT("calls"), A3Entry::Rows);
    FString Text; TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Text);
    FJsonSerializer::Serialize(OutObj.ToSharedRef(), W);
    FFileHelper::SaveStringToFile(Text, *FPaths::Combine(A3Entry::Out, TEXT("state_entry_result.json")));
    if (A3Entry::Pending.Num() == 0) { A3Entry::bActive = false; UE_LOG(LogTemp, Display, TEXT("A3 state entry: done")); }
}

static void A3RunStateEntry(UWorld* World, const FString& PlanPath, const FString& OutDir)
{
    FString Raw; TSharedPtr<FJsonObject> Plan;
    if (!FFileHelper::LoadFileToString(Raw, *PlanPath) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Raw), Plan) || !Plan.IsValid())
    { UE_LOG(LogTemp, Error, TEXT("A3 state entry: invalid plan %s"), *PlanPath); return; }
    A3Entry::Pending.Reset(); A3Entry::Rows.Reset();
    for (const TSharedPtr<FJsonValue>& V : Plan->GetArrayField(TEXT("calls"))) A3Entry::Pending.Add(V->AsObject());
    A3Entry::Out = OutDir; A3Entry::StartSec = FPlatformTime::Seconds(); A3Entry::bActive = true;
    UE_LOG(LogTemp, Display, TEXT("A3 state entry: begin"));   // game lines from here on belong to the entry
    A3EntryTick(World);
}

// ---- Map travel hand-over ----
struct FA3TakeCarry
{
    bool bCaptureSlateUI;
    bool bRequireStartupFrame;
    bool bStartupFrameComplete;
    double StartupFrameArmedAt;
    double StartupFrameCompletedAt;
    uint64 StartupFrameArmedCounter;
    uint64 StartupFrameCompletedCounter;
    FVector2D NativeViewportPoint;
    int64 NativeViewportLastSeq;
    bool bNativeSlateMouse;
    bool bNativeSlateClosed;
    int32 NativeSlateUser;
    int32 NativeSlateVirtualSlot;
    TSharedPtr<FSlateVirtualUserHandle> NativeSlateUserHandle;
    TWeakPtr<SWindow> NativeSlateWindow;
    FString NativeSlateWindowId;
    TSet<FKey> NativeSlateButtons;
    FString NativeSlateAction;
    FVector2D NativeSlatePoint;
    FVector2D NativeSlateFraction;
    int64 NativeSlateLastSeq;
    FSocket* NativeInputSocket;
    FString NativeInputToken;
    int32 NativeInputPort;
    TSet<FName> NativePressedKeys;
    TArray<TSharedPtr<class FJsonObject>> SparsePoints;
    TSharedPtr<class FJsonObject> PendingSparsePoint;
    FString PendingSparsePath;
    double PendingSparseTimeMs;
    double SparseWarmupMs;
    int32 SparseNextPoint;
    bool bSparse;
    double LastClockObservationMs;
    FString OutputDir;
    FString FramesDir;
    double StartedAt;
    double NextCaptureAt;
    double DurationSeconds;
    double CaptureInterval;
    int32 FrameIndex;
    bool bArmed;
    bool bRecording;
    bool bAudioPending;
    double AudioStopAt;
    double AudioSizeChangedAt;
    int64 AudioLastSize;
};
static TOptional<FA3TakeCarry> GA3TakeCarry;

void UA3GamePlaytestRecorderSubsystem::SaveTakeForNextWorld()
{
    FA3TakeCarry C;
    C.bCaptureSlateUI = bCaptureSlateUI;
    C.bRequireStartupFrame = bRequireStartupFrame;
    C.bStartupFrameComplete = bStartupFrameComplete;
    C.StartupFrameArmedAt = StartupFrameArmedAt;
    C.StartupFrameCompletedAt = StartupFrameCompletedAt;
    C.StartupFrameArmedCounter = StartupFrameArmedCounter;
    C.StartupFrameCompletedCounter = StartupFrameCompletedCounter;
    C.NativeViewportPoint = NativeViewportPoint;
    C.NativeViewportLastSeq = NativeViewportLastSeq;
    C.bNativeSlateMouse = bNativeSlateMouse;
    C.bNativeSlateClosed = bNativeSlateClosed;
    C.NativeSlateUser = NativeSlateUser;
    C.NativeSlateVirtualSlot = NativeSlateVirtualSlot;
    C.NativeSlateUserHandle = NativeSlateUserHandle;
    C.NativeSlateWindow = NativeSlateWindow;
    C.NativeSlateWindowId = NativeSlateWindowId;
    C.NativeSlateButtons = NativeSlateButtons;
    C.NativeSlateAction = NativeSlateAction;
    C.NativeSlatePoint = NativeSlatePoint;
    C.NativeSlateFraction = NativeSlateFraction;
    C.NativeSlateLastSeq = NativeSlateLastSeq;
    C.NativeInputSocket = NativeInputSocket;
    C.NativeInputToken = NativeInputToken;
    C.NativeInputPort = NativeInputPort;
    C.NativePressedKeys = NativePressedKeys;
    C.SparsePoints = SparsePoints;
    C.PendingSparsePoint = PendingSparsePoint;
    C.PendingSparsePath = PendingSparsePath;
    C.PendingSparseTimeMs = PendingSparseTimeMs;
    C.SparseWarmupMs = SparseWarmupMs;
    C.SparseNextPoint = SparseNextPoint;
    C.bSparse = bSparse;
    C.LastClockObservationMs = LastClockObservationMs;
    C.OutputDir = OutputDir;
    C.FramesDir = FramesDir;
    C.StartedAt = StartedAt;
    C.NextCaptureAt = NextCaptureAt;
    C.DurationSeconds = DurationSeconds;
    C.CaptureInterval = CaptureInterval;
    C.FrameIndex = FrameIndex;
    C.bArmed = bArmed;
    C.bRecording = bRecording;
    C.bAudioPending = bAudioPending;
    C.AudioStopAt = AudioStopAt;
    C.AudioSizeChangedAt = AudioSizeChangedAt;
    C.AudioLastSize = AudioLastSize;
    GA3TakeCarry = MoveTemp(C);
}

void UA3GamePlaytestRecorderSubsystem::RestoreTakeFromPreviousWorld()
{
    const FA3TakeCarry& C = GA3TakeCarry.GetValue();
    bCaptureSlateUI = C.bCaptureSlateUI;
    bRequireStartupFrame = C.bRequireStartupFrame;
    bStartupFrameComplete = C.bStartupFrameComplete;
    StartupFrameArmedAt = C.StartupFrameArmedAt;
    StartupFrameCompletedAt = C.StartupFrameCompletedAt;
    StartupFrameArmedCounter = C.StartupFrameArmedCounter;
    StartupFrameCompletedCounter = C.StartupFrameCompletedCounter;
    NativeViewportPoint = C.NativeViewportPoint;
    NativeViewportLastSeq = C.NativeViewportLastSeq;
    bNativeSlateMouse = C.bNativeSlateMouse;
    bNativeSlateClosed = C.bNativeSlateClosed;
    NativeSlateUser = C.NativeSlateUser;
    NativeSlateVirtualSlot = C.NativeSlateVirtualSlot;
    NativeSlateUserHandle = C.NativeSlateUserHandle;
    NativeSlateWindow = C.NativeSlateWindow;
    NativeSlateWindowId = C.NativeSlateWindowId;
    NativeSlateButtons = C.NativeSlateButtons;
    NativeSlateAction = C.NativeSlateAction;
    NativeSlatePoint = C.NativeSlatePoint;
    NativeSlateFraction = C.NativeSlateFraction;
    NativeSlateLastSeq = C.NativeSlateLastSeq;
    NativeInputSocket = C.NativeInputSocket;
    NativeInputToken = C.NativeInputToken;
    NativeInputPort = C.NativeInputPort;
    NativePressedKeys = C.NativePressedKeys;
    SparsePoints = C.SparsePoints;
    PendingSparsePoint = C.PendingSparsePoint;
    PendingSparsePath = C.PendingSparsePath;
    PendingSparseTimeMs = C.PendingSparseTimeMs;
    SparseWarmupMs = C.SparseWarmupMs;
    SparseNextPoint = C.SparseNextPoint;
    bSparse = C.bSparse;
    LastClockObservationMs = C.LastClockObservationMs;
    OutputDir = C.OutputDir;
    FramesDir = C.FramesDir;
    StartedAt = C.StartedAt;
    NextCaptureAt = C.NextCaptureAt;
    DurationSeconds = C.DurationSeconds;
    CaptureInterval = C.CaptureInterval;
    FrameIndex = C.FrameIndex;
    bArmed = C.bArmed;
    bRecording = C.bRecording;
    bAudioPending = C.bAudioPending;
    AudioStopAt = C.AudioStopAt;
    AudioSizeChangedAt = C.AudioSizeChangedAt;
    AudioLastSize = C.AudioLastSize;
    GA3TakeCarry.Reset();
    if (bSparse)
        ScreenshotProcessedHandle = FScreenshotRequest::OnScreenshotRequestProcessed().AddUObject(
            this, &UA3GamePlaytestRecorderSubsystem::FinishSparseScreenshot);
    const double T = bRecording ? (FPlatformTime::Seconds() - StartedAt) * 1000.0 : -1.0;
    const FString Map = GetWorld() ? GetWorld()->GetMapName() : FString();
    FFileHelper::SaveStringToFile(FString::Printf(TEXT("{\"t_ms\":%.3f,\"event\":\"world_changed\",\"map\":\"%s\",\"frame_index\":%d}\n"),
        T, *Map.ReplaceCharWithEscapedChar(), FrameIndex), *FPaths::Combine(OutputDir, TEXT("world_changes.jsonl")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    UE_LOG(LogTemp, Display, TEXT("A3 playtest recorder continued take in new world %s (frame %d)"), *Map, FrameIndex);
}

void UA3GamePlaytestRecorderSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    UE_LOG(LogTemp, Log, TEXT("A3 playtest recorder initialized"));
    if (GA3TakeCarry.IsSet()) { RestoreTakeFromPreviousWorld(); return; }   // same take continues after map travel
    StartFromCommandLine();
}

bool UA3GamePlaytestRecorderSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void UA3GamePlaytestRecorderSubsystem::Deinitialize()
{
    // A live take survives the game's own map travel: hand it to the next world's recorder (socket, clock,
    // frame counter, schedule position, held inputs) instead of stopping. Engine exit still finalizes.
    if ((bArmed || bRecording || bAudioPending) && !IsEngineExitRequested())
    {
        if (StartupFrameEndHandle.IsValid()) { FCoreDelegates::OnEndFrame.Remove(StartupFrameEndHandle); StartupFrameEndHandle.Reset(); }
        if (ScreenshotProcessedHandle.IsValid())
        { FScreenshotRequest::OnScreenshotRequestProcessed().Remove(ScreenshotProcessedHandle); ScreenshotProcessedHandle.Reset(); }
        SaveTakeForNextWorld();
        bHandedOver = true;
        Super::Deinitialize();
        return;
    }
    StopRecording();
    CloseNativeInput();
    if (ScreenshotProcessedHandle.IsValid())
        FScreenshotRequest::OnScreenshotRequestProcessed().Remove(ScreenshotProcessedHandle);
    Super::Deinitialize();
}

void UA3GamePlaytestRecorderSubsystem::StartFromCommandLine()
{
    FString RequestedOutput;
    FString FpsValue;
    FString DurationValue;
    if (!FParse::Value(FCommandLine::Get(), TEXT("A3RecorderOutput="), RequestedOutput))
    {
        UE_LOG(LogTemp, Log, TEXT("A3 playtest recorder inactive: no output argument"));
        return;
    }
    FParse::Value(FCommandLine::Get(), TEXT("A3PlaytestFps="), FpsValue);
    FParse::Value(FCommandLine::Get(), TEXT("A3PlaytestDuration="), DurationValue);
    int32 Fps = 20;
    double Duration = 0.0;
    FDefaultValueHelper::ParseInt(FpsValue, Fps);
    FDefaultValueHelper::ParseDouble(DurationValue, Duration);
    if (Fps <= 0 || Duration <= 0.0)
    {
        return;
    }
    OutputDir = FPaths::ConvertRelativePathToFull(RequestedOutput);
    FramesDir = FPaths::Combine(OutputDir, TEXT("frames"));
    IFileManager::Get().MakeDirectory(*FramesDir, true);
    DurationSeconds = Duration;
    CaptureInterval = 1.0 / static_cast<double>(Fps);
    FrameIndex = 0;
    FString SchedulePath;
    if (FParse::Value(FCommandLine::Get(), TEXT("A3CaptureSchedule="), SchedulePath))
    {
        FString Text;
        TSharedPtr<FJsonObject> Schedule;
        if (!FFileHelper::LoadFileToString(Text, *SchedulePath) ||
            !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Schedule) || !Schedule.IsValid())
        { UE_LOG(LogTemp, Error, TEXT("Invalid native capture schedule")); return; }
        SparseWarmupMs = Schedule->GetNumberField(TEXT("warmup_ms"));
        for (auto Value : Schedule->GetArrayField(TEXT("points"))) SparsePoints.Add(Value->AsObject());
        bSparse = true;
        ScreenshotProcessedHandle = FScreenshotRequest::OnScreenshotRequestProcessed().AddUObject(
            this, &UA3GamePlaytestRecorderSubsystem::FinishSparseScreenshot);
    }
    // A versioned host handshake prevents an old recorder binary from silently
    // claiming the post-startup boundary. No Python/editor module dependency.
    FString ReadinessPolicy;
    if (FParse::Value(FCommandLine::Get(), TEXT("A3ReadinessGate="), ReadinessPolicy))
    {
        if (ReadinessPolicy != TEXT("post_core_ticker_frame.v1"))
        { UE_LOG(LogTemp, Error, TEXT("Unknown native readiness gate")); return; }
        bRequireStartupFrame = true;
    }
    if (FParse::Param(FCommandLine::Get(), TEXT("A3BackgroundFocus")))
    {
        FApp::SetHasFocusFunction(&A3BackgroundAlwaysFocused);
        UE_LOG(LogTemp, Display, TEXT("A3 playtest recorder: background focus policy active (FApp::HasFocus = true)"));
    }
    FString CaptureSurface;
    if (FParse::Value(FCommandLine::Get(), TEXT("A3CaptureSurface="), CaptureSurface))
    {
        if (CaptureSurface != TEXT("slate_window.v1") ||
            FParse::Param(FCommandLine::Get(), TEXT("RenderOffscreen")))
        { UE_LOG(LogTemp, Error, TEXT("Invalid native UI capture surface")); return; }
        bCaptureSlateUI = true;
    }
    FString SlateMousePolicy;
    if (FParse::Value(FCommandLine::Get(), TEXT("A3NativeSlateMouse="), SlateMousePolicy))
    {
        if (SlateMousePolicy != TEXT("viewport_button.v1") || !bCaptureSlateUI)
        { UE_LOG(LogTemp, Error, TEXT("Invalid native Slate mouse policy")); return; }
        bNativeSlateMouse = true;
    }
    // Opt-in adapter-only input. Bind loopback without address reuse: a
    // collision must fail admission rather than split input across candidates.
    if (FParse::Value(FCommandLine::Get(), TEXT("A3NativeInputPort="), NativeInputPort))
    {
        FParse::Value(FCommandLine::Get(), TEXT("A3NativeInputToken="), NativeInputToken);
        if (NativeInputPort < 1 || NativeInputPort > 65535 || NativeInputToken.IsEmpty())
        { UE_LOG(LogTemp, Error, TEXT("Invalid native playtest input lease/token")); return; }
        NativeInputSocket = FUdpSocketBuilder(TEXT("A3PlaytestNativeInput"))
            .AsNonBlocking().BoundToAddress(FIPv4Address::InternalLoopback)
            .BoundToPort(NativeInputPort);
        if (!NativeInputSocket)
        { UE_LOG(LogTemp, Error, TEXT("Native playtest input port occupied")); return; }
    }
    // The take clock starts when gameplay actually begins, not when the
    // world is created; map loading otherwise eats the whole window.
    bArmed = true;
    UE_LOG(LogTemp, Log, TEXT("A3 playtest recorder armed: %s (%d fps, %.2f sec after gameplay starts)"), *FramesDir, Fps, Duration);
}

void UA3GamePlaytestRecorderSubsystem::ObserveStartupFrameEnd()
{
    if (!bArmed || bRecording || bStartupFrameComplete) return;
    // UE 5.4 FEngineLoop broadcasts this AFTER the core ticker, which runs
    // Python startup scripts synchronously. Only latch; start on a later world
    // tick, after the entire end-frame delegate broadcast has returned.
    StartupFrameCompletedAt = FPlatformTime::Seconds();
    StartupFrameCompletedCounter = GFrameCounter;
    bStartupFrameComplete = true;
}

void UA3GamePlaytestRecorderSubsystem::StopRecording()
{
    if (StartupFrameEndHandle.IsValid())
    {
        FCoreDelegates::OnEndFrame.Remove(StartupFrameEndHandle);
        StartupFrameEndHandle.Reset();
    }
    CloseNativeSlateMouse();
    A3EventFrames::Stop();
    bArmed = false;
    bRecording = false;
}

void UA3GamePlaytestRecorderSubsystem::WriteMarkerFile() const
{
    const FString Path = FPaths::Combine(OutputDir, TEXT("play_started.json"));
    const double Wall = (FDateTime::UtcNow().GetTicks() - FDateTime(1970,1,1).GetTicks()) / 10000000.0;
    auto Row = MakeShared<FJsonObject>();
    Row->SetBoolField(TEXT("native_recorder"), true);
    Row->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
    Row->SetNumberField(TEXT("recorder_elapsed_ms"), 0);
    Row->SetNumberField(TEXT("native_origin_seconds"), StartedAt);
    Row->SetNumberField(TEXT("wall_origin_seconds"), Wall);
    Row->SetNumberField(TEXT("world_origin_seconds"), GetWorld()->GetTimeSeconds());
    if (bRequireStartupFrame)
    {
        auto Gate = MakeShared<FJsonObject>();
        Gate->SetStringField(TEXT("policy"), TEXT("post_core_ticker_frame.v1"));
        Gate->SetNumberField(TEXT("armed_native_seconds"), StartupFrameArmedAt);
        Gate->SetNumberField(TEXT("completed_native_seconds"), StartupFrameCompletedAt);
        Gate->SetNumberField(TEXT("armed_frame"), StartupFrameArmedCounter);
        Gate->SetNumberField(TEXT("completed_frame"), StartupFrameCompletedCounter);
        Gate->SetNumberField(TEXT("ready_frame"), GFrameCounter);
        Row->SetObjectField(TEXT("startup_boundary"), Gate);
    }
    if (bCaptureSlateUI)
    {
        auto Surface = MakeShared<FJsonObject>();
        Surface->SetStringField(TEXT("policy"), TEXT("slate_window.v1"));
        Surface->SetBoolField(TEXT("show_ui"), true);
        Surface->SetBoolField(TEXT("slate_initialized"), FSlateApplication::IsInitialized());
        UGameViewportClient* VC = GetWorld()->GetGameViewport();
        Surface->SetBoolField(TEXT("game_window_valid"), VC && VC->GetWindow().IsValid());
        Row->SetObjectField(TEXT("capture_surface"), Surface);
    }
    if (NativeInputSocket)
    {
        Row->SetStringField(TEXT("native_input_token"), NativeInputToken);
        Row->SetNumberField(TEXT("native_input_port"), NativeInputPort);
        Row->SetStringField(TEXT("native_input_source"), TEXT("A3GamePlayable_native_viewport"));
        if (bNativeSlateMouse)
        {
            Row->SetStringField(TEXT("slate_mouse_policy"), TEXT("viewport_button.v1"));
            Row->SetStringField(TEXT("slate_mouse_window_id"), NativeSlateWindowId);
        }
    }
    FString Json;
    FJsonSerializer::Serialize(Row, TJsonWriterFactory<>::Create(&Json));
    FFileHelper::SaveStringToFile(Json, *Path);
}

void UA3GamePlaytestRecorderSubsystem::WriteReportFile() const
{
    const bool bOk = FrameIndex > 0;
    const FString Path = FPaths::Combine(OutputDir, TEXT("_editor_report.json"));
    const FString Json = FString::Printf(
        TEXT("{\n  \"schema_version\": \"gamefactory3a.ue5.playtest_native_report.v1\",\n")
        TEXT("  \"source\": \"native_recorder\",\n  \"ok\": %s,\n  \"frames\": %d,\n  \"errors\": [%s]\n}\n"),
        bOk ? TEXT("true") : TEXT("false"),
        FrameIndex,
        bOk ? TEXT("") : TEXT("\"no frames were captured\""));
    FFileHelper::SaveStringToFile(Json, *Path);
}

void UA3GamePlaytestRecorderSubsystem::FinishSparseScreenshot()
{
    if (!bSparse || PendingSparsePath.IsEmpty()) return;
    if (A3EventFrames::bPendingIsEvent)
    {
        A3EventFrames::bPendingIsEvent = false;
        if (IFileManager::Get().FileSize(*PendingSparsePath) > 32)
        {
            auto Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("frame_id"), FString::Printf(TEXT("FRAME:E%05d"), A3EventFrames::Taken));
            Row->SetStringField(TEXT("path"), FPaths::Combine(TEXT("event_frames"), FPaths::GetCleanFilename(PendingSparsePath)));
            Row->SetNumberField(TEXT("t_ms"), PendingSparseTimeMs);
            Row->SetNumberField(TEXT("capture_end_t_ms"), (FPlatformTime::Seconds()-StartedAt)*1000.0);
            Row->SetNumberField(TEXT("sample_at_ms"), -1);
            Row->SetArrayField(TEXT("capture_ids"), PendingSparsePoint->GetArrayField(TEXT("capture_ids")));
            Row->SetStringField(TEXT("engine"), TEXT("ue5"));
            Row->SetStringField(TEXT("trigger"), TEXT("game_log_line"));
            FString Line;
            FJsonSerializer::Serialize(Row, TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line));
            FFileHelper::SaveStringToFile(Line+TEXT("\n"), *FPaths::Combine(OutputDir,TEXT("event_frame_index.jsonl")),
                FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
        }
        PendingSparsePath.Empty(); PendingSparsePoint.Reset();
        return;
    }
    if (IFileManager::Get().FileSize(*PendingSparsePath) > 32)
    {
        auto Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("frame_id"), FString::Printf(TEXT("FRAME:%05d"), FrameIndex));
        Row->SetStringField(TEXT("path"), FPaths::Combine(TEXT("frames"), FPaths::GetCleanFilename(PendingSparsePath)));
        Row->SetNumberField(TEXT("t_ms"), PendingSparseTimeMs);
        Row->SetNumberField(TEXT("capture_end_t_ms"), (FPlatformTime::Seconds()-StartedAt)*1000.0);
        Row->SetNumberField(TEXT("sample_at_ms"), PendingSparsePoint.IsValid() ? PendingSparsePoint->GetNumberField(TEXT("at_ms")) : -1);
        TArray<TSharedPtr<FJsonValue>> Ids;
        if (PendingSparsePoint.IsValid()) Ids = PendingSparsePoint->GetArrayField(TEXT("capture_ids"));
        else Ids.Add(MakeShared<FJsonValueString>(TEXT("readiness")));
        Row->SetArrayField(TEXT("capture_ids"), Ids);
        Row->SetStringField(TEXT("engine"), TEXT("ue5"));
        Row->SetStringField(TEXT("source"), bCaptureSlateUI ?
            TEXT("FScreenshotRequest_native_slate_window") : TEXT("FScreenshotRequest_native_viewport"));
        if (bCaptureSlateUI) Row->SetStringField(TEXT("capture_policy"), TEXT("slate_window.v1"));
        FString Line;
        FJsonSerializer::Serialize(Row, TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line));
        FFileHelper::SaveStringToFile(Line+TEXT("\n"), *FPaths::Combine(OutputDir,TEXT("frame_index.jsonl")),
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    }
    else UE_LOG(LogTemp,Error,TEXT("Native sparse screenshot missing: %s"),*PendingSparsePath);
    PendingSparsePath.Empty(); PendingSparsePoint.Reset();
}

void UA3GamePlaytestRecorderSubsystem::CloseNativeInput()
{
    // Release through the same game viewport; never synthesize desktop input.
    UGameViewportClient* VC = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
    if (VC && VC->Viewport)
        for (const FName Key : NativePressedKeys)
            VC->InputKey(FInputKeyEventArgs(VC->Viewport, FInputDeviceId::CreateFromInternalId(0),
                FKey(Key), IE_Released));
    NativePressedKeys.Empty();
    if (NativeInputSocket)
    {
        NativeInputSocket->Close();
        ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(NativeInputSocket);
        NativeInputSocket = nullptr;
    }
}



// ---- Viewport pointer (viewport_pointer.v1): mouse anywhere in the game viewport, in-engine only ----
// move: the game viewport's own mouse-move handler (FSceneViewport::OnMouseMove) updates the cursor position
//   the game reads (GetMousePosition / hit-under-cursor); no OS cursor is moved.
// down / up: if a Slate SButton (UMG button) is under the point, the click is routed to it through Slate with
//   the recorder's own virtual user (as viewport_button.v1); otherwise the button goes to the game through
//   UGameViewportClient::InputKey - the same path as the keyboard (canvas HUD buttons, world clicks).
// wheel: MouseScrollUp / MouseScrollDown key press + release and the MouseWheelAxis axis.
void UA3GamePlaytestRecorderSubsystem::RouteNativeViewportPointer(const TSharedPtr<FJsonObject>& Message, double Seq)
{
    FString Phase, Policy, ActionId, Button;
    double X = 0, Y = 0, Wheel = 0;
    Message->TryGetStringField(TEXT("button"), Button);
    Message->TryGetNumberField(TEXT("wheel"), Wheel);
    if (!bRecording || !FMath::IsFinite(Seq) || Seq < 0 || Seq != FMath::FloorToDouble(Seq) ||
        !Message->TryGetStringField(TEXT("phase"), Phase) ||
        !Message->TryGetStringField(TEXT("policy"), Policy) || Policy != TEXT("viewport_pointer.v1") ||
        !Message->TryGetStringField(TEXT("action_id"), ActionId) || ActionId.IsEmpty() ||
        !Message->TryGetNumberField(TEXT("x"), X) || !Message->TryGetNumberField(TEXT("y"), Y) ||
        !FMath::IsFinite(X) || !FMath::IsFinite(Y) || X < 0 || X > 1 || Y < 0 || Y > 1 ||
        (Phase != TEXT("move") && Phase != TEXT("down") && Phase != TEXT("up") && Phase != TEXT("wheel")) ||
        ((Phase == TEXT("down") || Phase == TEXT("up")) &&
         Button != TEXT("left") && Button != TEXT("right") && Button != TEXT("middle"))) return;
    auto Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("type"), TEXT("viewport_pointer"));
    { FString EchoKey; Message->TryGetStringField(TEXT("key"), EchoKey); Row->SetStringField(TEXT("key"), EchoKey); }
    Row->SetStringField(TEXT("policy"), Policy);
    Row->SetStringField(TEXT("action_id"), ActionId);
    Row->SetStringField(TEXT("phase"), Phase);
    Row->SetStringField(TEXT("button"), Button);
    Row->SetNumberField(TEXT("x"), X); Row->SetNumberField(TEXT("y"), Y);
    Row->SetNumberField(TEXT("wheel"), Wheel);
    Row->SetNumberField(TEXT("seq"), Seq);
    Row->SetStringField(TEXT("token"), NativeInputToken);
    Row->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
    Row->SetNumberField(TEXT("t_ms"), FPlatformTime::Seconds()*1000.0);
    Row->SetBoolField(TEXT("routed"), false); Row->SetBoolField(TEXT("handled"), false);
    Row->SetStringField(TEXT("route"), TEXT(""));
    auto Route = [&]() {
        if (Seq <= NativeViewportLastSeq) return;
        NativeViewportLastSeq = static_cast<int64>(Seq);
        UWorld* World = GetWorld();
        UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
        FSceneViewport* SV = VC ? VC->GetGameViewport() : nullptr;
        TSharedPtr<SViewport> ViewportWidget = VC ? VC->GetGameViewportWidget() : nullptr;
        if (!VC || !VC->Viewport || !SV || !ViewportWidget.IsValid()) return;
        const FGeometry& Geometry = ViewportWidget->GetCachedGeometry();
        const FVector2D Origin = Geometry.LocalToAbsolute(FVector2D::ZeroVector);
        const FVector2D End = Geometry.LocalToAbsolute(Geometry.GetLocalSize());
        const FVector2D Size = End - Origin;
        if (Size.X <= 1 || Size.Y <= 1) return;
        const FVector2D Point = Origin + FVector2D(X * (Size.X - 1), Y * (Size.Y - 1));
        const FVector2D Last = NativeViewportPoint.X < 0 ? Point : NativeViewportPoint;
        auto Rect = MakeShared<FJsonObject>();
        Rect->SetNumberField(TEXT("origin_x"), Origin.X); Rect->SetNumberField(TEXT("origin_y"), Origin.Y);
        Rect->SetNumberField(TEXT("width"), Size.X); Rect->SetNumberField(TEXT("height"), Size.Y);
        Rect->SetNumberField(TEXT("screen_x"), Point.X); Rect->SetNumberField(TEXT("screen_y"), Point.Y);
        Row->SetObjectField(TEXT("geometry"), Rect);
        // 1. cursor position, through the viewport's own handler. A positioning move (implicit, before a click /
        //    hold / wheel) is applied only when the game shows a cursor: with a hidden, captured cursor (mouse look)
        //    the click needs no position and the move would swing the camera.
        bool bImplicit = false; Message->TryGetBoolField(TEXT("implicit"), bImplicit);
        const bool bCursorShown = VC->Viewport->IsCursorVisible();
        const bool bApplyMove = (Phase == TEXT("move") && !bImplicit) || bCursorShown;
        Row->SetBoolField(TEXT("cursor_shown"), bCursorShown);
        Row->SetBoolField(TEXT("move_applied"), bApplyMove);
        TSet<FKey> Held;
        for (const FName K : NativePressedKeys)
            if (FKey(K).IsMouseButton()) Held.Add(FKey(K));
        if (bApplyMove)
        {
            FPointerEvent Move(0, 0, Point, Last, Held, FKey(), 0.0f, FModifierKeysState());
            SV->OnMouseMove(Geometry, Move);
            NativeViewportPoint = Point;
        }
        FIntPoint Cursor(-1, -1);
        VC->Viewport->GetMousePos(Cursor);
        Row->SetNumberField(TEXT("cursor_x"), Cursor.X); Row->SetNumberField(TEXT("cursor_y"), Cursor.Y);
        if (Phase == TEXT("move")) { Row->SetStringField(TEXT("route"), TEXT("viewport_move")); Row->SetBoolField(TEXT("routed"), true);
                                     Row->SetBoolField(TEXT("handled"), Cursor.X >= 0); return; }
        if (Phase == TEXT("wheel"))
        {
            const FKey Key = Wheel >= 0 ? EKeys::MouseScrollUp : EKeys::MouseScrollDown;
            const FInputDeviceId Device = FInputDeviceId::CreateFromInternalId(0);
            bool bH = VC->InputAxis(VC->Viewport, Device, EKeys::MouseWheelAxis, static_cast<float>(Wheel), FApp::GetDeltaTime());
            bH |= VC->InputKey(FInputKeyEventArgs(VC->Viewport, Device, Key, IE_Pressed));
            VC->InputKey(FInputKeyEventArgs(VC->Viewport, Device, Key, IE_Released));
            Row->SetStringField(TEXT("route"), TEXT("viewport_wheel")); Row->SetBoolField(TEXT("routed"), true);
            Row->SetBoolField(TEXT("handled"), bH); return;
        }
        const bool bDown = Phase == TEXT("down");
        const FKey Key = Button == TEXT("right") ? EKeys::RightMouseButton :
                         Button == TEXT("middle") ? EKeys::MiddleMouseButton : EKeys::LeftMouseButton;
        // 2a. a Slate / UMG button under the point: route the click to it (virtual user, owning window only)
        TSharedPtr<SWindow> Window = VC->GetWindow();
        FSlateApplication& Slate = FSlateApplication::Get();
        TSharedPtr<SWidget> HitButton;
        FWidgetPath Hit;
        if (Window.IsValid() && Key == EKeys::LeftMouseButton && Window->GetClientRectInScreen().ContainsPoint(Point))
        {
            TArray<TSharedRef<SWindow>> Windows; Windows.Add(Window.ToSharedRef());
            Hit = Slate.LocateWindowUnderMouse(Point, Windows, false, 0);
            if (Hit.IsValid() && Hit.GetWindow() == Window.ToSharedRef())
                for (int32 Index = Hit.Widgets.Num() - 1; Index >= 0; --Index)
                    if (Hit.Widgets[Index].Widget->GetType() == FName(TEXT("SButton")))
                    { HitButton = Hit.Widgets[Index].Widget; break; }
        }
        if (HitButton.IsValid() && HitButton->IsEnabled())
        {
            if (NativeSlateUser == INDEX_NONE)
            {
                TSet<int32> ExistingUsers;
                Slate.ForEachUser([&](FSlateUser& Existing) { ExistingUsers.Add(Existing.GetUserIndex()); }, true);
                for (int32 Candidate = 64; Candidate < 128; ++Candidate)
                {
                    TSharedPtr<FSlateVirtualUserHandle> Handle = Slate.FindOrCreateVirtualUser(Candidate);
                    if (ExistingUsers.Contains(Handle->GetUserIndex()) || Handle.GetSharedReferenceCount() != 1) continue;
                    NativeSlateUser = Handle->GetUserIndex(); NativeSlateVirtualSlot = Candidate; NativeSlateUserHandle = Handle;
                    break;
                }
            }
            if (NativeSlateUser != INDEX_NONE)
            {
                if (bDown) NativeSlateButtons.Add(EKeys::LeftMouseButton); else NativeSlateButtons.Remove(EKeys::LeftMouseButton);
                FPointerEvent SMove(NativeSlateUser, 0, Point, NativeSlatePoint, NativeSlateButtons, FKey(), 0.0f, FModifierKeysState());
                Slate.RoutePointerMoveEvent(Hit, SMove, false);
                NativeSlatePoint = Point;
                FPointerEvent Event(NativeSlateUser, 0, Point, Point, NativeSlateButtons, EKeys::LeftMouseButton, 0.0f, FModifierKeysState());
                const FReply Reply = bDown ? Slate.RoutePointerDownEvent(Hit, Event) : Slate.RoutePointerUpEvent(Hit, Event);
                Row->SetStringField(TEXT("route"), TEXT("slate_button")); Row->SetStringField(TEXT("hit_widget"), TEXT("SButton"));
                Row->SetBoolField(TEXT("routed"), true); Row->SetBoolField(TEXT("handled"), Reply.IsEventHandled());
                Row->SetNumberField(TEXT("user_index"), NativeSlateUser);
                return;
            }
        }
        // 2b. everything else in the viewport: the button goes to the game like a keyboard key
        const bool bH = VC->InputKey(FInputKeyEventArgs(VC->Viewport, FInputDeviceId::CreateFromInternalId(0),
                                                         Key, bDown ? IE_Pressed : IE_Released));
        if (bDown) NativePressedKeys.Add(Key.GetFName()); else NativePressedKeys.Remove(Key.GetFName());
        Row->SetStringField(TEXT("route"), TEXT("viewport_input_key"));
        Row->SetBoolField(TEXT("routed"), true); Row->SetBoolField(TEXT("handled"), bH);
    };
    Route();
    FString Line;
    FJsonSerializer::Serialize(Row, TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line));
    FFileHelper::SaveStringToFile(Line+TEXT("\n"), *FPaths::Combine(OutputDir,TEXT("native_input.jsonl")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
}

void UA3GamePlaytestRecorderSubsystem::RouteNativeSlateMouse(const TSharedPtr<FJsonObject>& Message, double Seq)
{
    // Current contract deliberately supports button clicks only, in this game's
    // viewport. No widget selection by label/name and no direct UMG callback.
    FString Phase, Policy, ActionId, Button;
    double X = 0, Y = 0;
    if (!bNativeSlateMouse || bNativeSlateClosed || !bRecording || !FSlateApplication::IsInitialized() ||
        !FMath::IsFinite(Seq) || Seq < 0 || Seq > MAX_int32 || Seq != FMath::FloorToDouble(Seq) ||
        !Message->TryGetStringField(TEXT("phase"), Phase) ||
        !Message->TryGetStringField(TEXT("policy"), Policy) || Policy != TEXT("viewport_button.v1") ||
        !Message->TryGetStringField(TEXT("action_id"), ActionId) || ActionId.IsEmpty() ||
        !Message->TryGetStringField(TEXT("button"), Button) || Button != TEXT("left") ||
        !Message->TryGetNumberField(TEXT("x"), X) || !Message->TryGetNumberField(TEXT("y"), Y) ||
        !FMath::IsFinite(X) || !FMath::IsFinite(Y) || X < 0 || X > 1 || Y < 0 || Y > 1 ||
        (Phase != TEXT("down") && Phase != TEXT("up"))) return;
    auto Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("type"), TEXT("slate_mouse"));
    Row->SetStringField(TEXT("policy"), Policy);
    Row->SetStringField(TEXT("action_id"), ActionId);
    Row->SetStringField(TEXT("key"), TEXT("lmb"));
    Row->SetStringField(TEXT("button"), Button);
    Row->SetStringField(TEXT("phase"), Phase);
    Row->SetNumberField(TEXT("x"), X); Row->SetNumberField(TEXT("y"), Y);
    Row->SetNumberField(TEXT("seq"), Seq);
    Row->SetStringField(TEXT("token"), NativeInputToken);
    Row->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
    Row->SetNumberField(TEXT("t_ms"), FPlatformTime::Seconds()*1000.0);
    Row->SetStringField(TEXT("source"), TEXT("FSlateApplication::RoutePointer_window_local.v1"));
    Row->SetStringField(TEXT("window_id"), NativeSlateWindowId);
    Row->SetBoolField(TEXT("routed"), false); Row->SetBoolField(TEXT("handled"), false);
    Row->SetBoolField(TEXT("owning_window"), false); Row->SetBoolField(TEXT("virtual_user"), false);
    Row->SetNumberField(TEXT("pointer_index"), 0);
    auto Route = [&]() {
        if (Seq <= NativeSlateLastSeq) return;
        NativeSlateLastSeq = static_cast<int64>(Seq); // No replay even after rejected geometry.
        UWorld* World = GetWorld();
        UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
        TSharedPtr<SWindow> Window = NativeSlateWindow.Pin();
        if (!VC || !Window.IsValid() || VC->GetWindow() != Window) return;
        TSharedPtr<SViewport> ViewportWidget = VC->GetGameViewportWidget();
        if (!ViewportWidget.IsValid()) return;
        FSlateApplication& Slate = FSlateApplication::Get();
        if (NativeSlateUser == INDEX_NONE)
        {
            // Public API only. Reject any handle that existed before this call;
            // never borrow an authored WidgetInteractionComponent's virtual user.
            TSet<int32> ExistingUsers;
            Slate.ForEachUser([&](FSlateUser& Existing) { ExistingUsers.Add(Existing.GetUserIndex()); }, true);
            for (int32 Candidate = 64; Candidate < 128; ++Candidate)
            {
                TSharedPtr<FSlateVirtualUserHandle> Handle = Slate.FindOrCreateVirtualUser(Candidate);
                if (ExistingUsers.Contains(Handle->GetUserIndex()) || Handle.GetSharedReferenceCount() != 1) continue;
                NativeSlateUser = Handle->GetUserIndex();
                NativeSlateVirtualSlot = Candidate;
                NativeSlateUserHandle = Handle;
                break;
            }
            if (!NativeSlateUserHandle.IsValid()) return;
        }
        TSharedPtr<FSlateUser> User = Slate.GetUser(NativeSlateUser);
        // Public UE API: IsVirtualUser() is exactly !Cursor.IsValid().
        if (!User.IsValid() || !User->IsVirtualUser()) return;
        Row->SetBoolField(TEXT("virtual_user"), true);
        Row->SetNumberField(TEXT("user_index"), NativeSlateUser);
        Row->SetNumberField(TEXT("virtual_slot"), NativeSlateVirtualSlot);
        Row->SetBoolField(TEXT("fresh_virtual_user"), NativeSlateUserHandle.IsValid() && NativeSlateUserHandle.GetSharedReferenceCount() == 1);
        const FGeometry& Geometry = ViewportWidget->GetCachedGeometry();
        const FVector2D Origin = Geometry.LocalToAbsolute(FVector2D::ZeroVector);
        const FVector2D End = Geometry.LocalToAbsolute(Geometry.GetLocalSize());
        const FVector2D Size = End - Origin;
        if (Size.X <= 1 || Size.Y <= 1) return;
        const FVector2D Point = Origin + FVector2D(X * (Size.X - 1), Y * (Size.Y - 1));
        const FSlateRect ClientRect = Window->GetClientRectInScreen();
        if (!ClientRect.ContainsPoint(Point)) return;
        TArray<TSharedRef<SWindow>> Windows;
        Windows.Add(Window.ToSharedRef());
        FWidgetPath Hit = Slate.LocateWindowUnderMouse(Point, Windows, false, NativeSlateUser);
        if (!Hit.IsValid() || Hit.GetWindow() != Window.ToSharedRef()) return;
        TSharedPtr<SWidget> HitButton;
        for (int32 Index = Hit.Widgets.Num() - 1; Index >= 0; --Index)
            if (Hit.Widgets[Index].Widget->GetType() == FName(TEXT("SButton")))
            { HitButton = Hit.Widgets[Index].Widget; break; }
        if (!HitButton.IsValid() || !HitButton->IsEnabled()) return;
        const bool bDown = Phase == TEXT("down");
        if (bDown && (!NativeSlateButtons.IsEmpty() || User->HasCapture(0))) return;
        if (!bDown && (NativeSlateButtons.Num() != 1 || NativeSlateAction != ActionId ||
                NativeSlateFraction != FVector2D(X, Y) || NativeSlateButton.Pin() != HitButton)) return;
        if (User->HasCapture(0))
        {
            FWidgetPath Captor = User->GetCaptorPath(0);
            if (!Captor.IsValid() || Captor.GetWindow() != Window.ToSharedRef()) return;
        }
        auto Rect = MakeShared<FJsonObject>();
        Rect->SetNumberField(TEXT("origin_x"), Origin.X); Rect->SetNumberField(TEXT("origin_y"), Origin.Y);
        Rect->SetNumberField(TEXT("width"), Size.X); Rect->SetNumberField(TEXT("height"), Size.Y);
        Rect->SetNumberField(TEXT("screen_x"), Point.X); Rect->SetNumberField(TEXT("screen_y"), Point.Y);
        Row->SetObjectField(TEXT("geometry"), Rect);
        Row->SetBoolField(TEXT("owning_window"), true); Row->SetStringField(TEXT("hit_widget"), TEXT("SButton"));
        // Normal Slate hover establishes IsHovered, required by SButton's up
        // handling. This is an event on a virtual pointer, not an OS cursor move.
        FPointerEvent Move(NativeSlateUser, 0, Point, NativeSlatePoint, NativeSlateButtons,
                           FKey(), 0.0f, FModifierKeysState());
        Slate.RoutePointerMoveEvent(Hit, Move, false);
        NativeSlatePoint = Point;
        if (bDown)
        {
            NativeSlateButtons.Add(EKeys::LeftMouseButton); NativeSlateAction = ActionId;
            NativeSlateButton = HitButton; NativeSlateFraction = FVector2D(X, Y);
        }
        else NativeSlateButtons.Remove(EKeys::LeftMouseButton);
        FPointerEvent Event(NativeSlateUser, 0, Point, Point, NativeSlateButtons,
                            EKeys::LeftMouseButton, 0.0f, FModifierKeysState());
        const FReply Reply = bDown ? Slate.RoutePointerDownEvent(Hit, Event) : Slate.RoutePointerUpEvent(Hit, Event);
        Row->SetBoolField(TEXT("routed"), true); Row->SetBoolField(TEXT("handled"), Reply.IsEventHandled());
        if (!bDown) { NativeSlateAction.Empty(); NativeSlateButton.Reset(); }
    };
    Route();
    FString Line;
    FJsonSerializer::Serialize(Row, TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line));
    FFileHelper::SaveStringToFile(Line+TEXT("\n"), *FPaths::Combine(OutputDir,TEXT("native_input.jsonl")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
}

void UA3GamePlaytestRecorderSubsystem::CloseNativeSlateMouse()
{
    if (!bNativeSlateMouse || bNativeSlateClosed) return;
    bNativeSlateClosed = true;
    const bool bPending = !NativeSlateButtons.IsEmpty();
    bool bReleased = NativeSlateUser == INDEX_NONE;
    if (FSlateApplication::IsInitialized() && NativeSlateUser != INDEX_NONE)
    {
        FSlateApplication& Slate = FSlateApplication::Get();
        if (TSharedPtr<FSlateUser> User = Slate.GetUser(NativeSlateUser))
        {
            // Cancel, never synthesize a click-on-up during abnormal cleanup.
            User->ReleaseAllCapture();
            NativeSlateButtons.Empty();
            FPointerEvent Leave(NativeSlateUser, 0, NativeSlatePoint, NativeSlatePoint,
                                NativeSlateButtons, FKey(), 0.0f, FModifierKeysState());
            Slate.RoutePointerMoveEvent(FWidgetPath(), Leave, false);
            NativeSlateUserHandle.Reset(); // Its destructor unregisters only our user.
        }
        bReleased = !Slate.GetUser(NativeSlateUser).IsValid();
    }
    auto Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("policy"), TEXT("viewport_button.v1"));
    Row->SetStringField(TEXT("token"), NativeInputToken);
    Row->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
    Row->SetStringField(TEXT("window_id"), NativeSlateWindowId);
    Row->SetBoolField(TEXT("pending_before_cleanup"), bPending);
    Row->SetBoolField(TEXT("virtual_user_released"), bReleased);
    FString Text;
    FJsonSerializer::Serialize(Row, TJsonWriterFactory<>::Create(&Text));
    FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir,TEXT("native_pointer_cleanup.json")));
}

void UA3GamePlaytestRecorderSubsystem::PollNativeInput()
{
    if (!NativeInputSocket) return;
    uint32 Pending = 0;
    // Bounded per tick so invalid traffic cannot starve rendering.
    for (int32 Count = 0; Count < 256 && NativeInputSocket->HasPendingData(Pending); ++Count)
    {
        TArray<uint8> Bytes;
        Bytes.SetNumUninitialized(65508);
        int32 Read = 0;
        if (!NativeInputSocket->Recv(Bytes.GetData(), Bytes.Num()-1, Read) || Read <= 0) break;
        Bytes[Read] = 0;
        TSharedPtr<FJsonObject> Message;
        if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(
                FString(UTF8_TO_TCHAR(reinterpret_cast<const char*>(Bytes.GetData())))), Message)
                || !Message.IsValid()) continue;
        FString Token, Type, Key, Phase;
        double Seq = 0;
        if (!Message->TryGetStringField(TEXT("token"), Token) || Token != NativeInputToken ||
            !Message->TryGetStringField(TEXT("type"), Type) ||
            !Message->TryGetNumberField(TEXT("seq"), Seq)) continue;
        if (Type == TEXT("slate_mouse")) { RouteNativeSlateMouse(Message, Seq); continue; }
        if (Type == TEXT("viewport_pointer")) { RouteNativeViewportPointer(Message, Seq); continue; }
        if (Type != TEXT("key") || !Message->TryGetStringField(TEXT("key"), Key) ||
            !Message->TryGetStringField(TEXT("phase"), Phase)) continue;
        FString Canonical;
        const FString Lower = Key.ToLower();
        if (Lower.Len() == 1 && Lower[0] >= 'a' && Lower[0] <= 'z')
            Canonical = Lower.ToUpper();
        else if (Lower.Len() == 1 && Lower[0] >= '0' && Lower[0] <= '9')
        {
            // UE names the top-row digit keys "Zero".."Nine"; FKey("1") is invalid.
            static const TCHAR* DigitNames[] = {TEXT("Zero"), TEXT("One"), TEXT("Two"), TEXT("Three"),
                TEXT("Four"), TEXT("Five"), TEXT("Six"), TEXT("Seven"), TEXT("Eight"), TEXT("Nine")};
            Canonical = DigitNames[Lower[0] - '0'];
        }
        else
        {
            static const TMap<FString, FString> Aliases = {
                {TEXT("space"),TEXT("SpaceBar")}, {TEXT("enter"),TEXT("Enter")},
                {TEXT("return"),TEXT("Enter")}, {TEXT("escape"),TEXT("Escape")},
                {TEXT("leftshift"),TEXT("LeftShift")}, {TEXT("leftcontrol"),TEXT("LeftControl")},
                {TEXT("tab"),TEXT("Tab")}, {TEXT("lmb"),TEXT("LeftMouseButton")},
                {TEXT("rmb"),TEXT("RightMouseButton")}, {TEXT("left_arrow"),TEXT("Left")},
                {TEXT("right_arrow"),TEXT("Right")}, {TEXT("up_arrow"),TEXT("Up")},
                {TEXT("down_arrow"),TEXT("Down")},
                // extended keyboard (2026-11-11)
                {TEXT("rightshift"),TEXT("RightShift")}, {TEXT("rightcontrol"),TEXT("RightControl")},
                {TEXT("leftalt"),TEXT("LeftAlt")}, {TEXT("rightalt"),TEXT("RightAlt")},
                {TEXT("backspace"),TEXT("BackSpace")}, {TEXT("delete"),TEXT("Delete")},
                {TEXT("insert"),TEXT("Insert")}, {TEXT("home"),TEXT("Home")}, {TEXT("end"),TEXT("End")},
                {TEXT("pageup"),TEXT("PageUp")}, {TEXT("pagedown"),TEXT("PageDown")},
                {TEXT("capslock"),TEXT("CapsLock")}, {TEXT("comma"),TEXT("Comma")}, {TEXT("period"),TEXT("Period")},
                {TEXT("slash"),TEXT("Slash")}, {TEXT("backslash"),TEXT("Backslash")}, {TEXT("semicolon"),TEXT("Semicolon")},
                {TEXT("apostrophe"),TEXT("Apostrophe")}, {TEXT("minus"),TEXT("Hyphen")}, {TEXT("equals"),TEXT("Equals")},
                {TEXT("leftbracket"),TEXT("LeftBracket")}, {TEXT("rightbracket"),TEXT("RightBracket")},
                {TEXT("backquote"),TEXT("Tilde")}, {TEXT("mmb"),TEXT("MiddleMouseButton")},
                {TEXT("f1"),TEXT("F1")}, {TEXT("f2"),TEXT("F2")}, {TEXT("f3"),TEXT("F3")}, {TEXT("f4"),TEXT("F4")},
                {TEXT("f5"),TEXT("F5")}, {TEXT("f6"),TEXT("F6")}, {TEXT("f7"),TEXT("F7")}, {TEXT("f8"),TEXT("F8")},
                {TEXT("f9"),TEXT("F9")}, {TEXT("f10"),TEXT("F10")}, {TEXT("f11"),TEXT("F11")}, {TEXT("f12"),TEXT("F12")},
                {TEXT("numpad0"),TEXT("NumPadZero")}, {TEXT("numpad1"),TEXT("NumPadOne")}, {TEXT("numpad2"),TEXT("NumPadTwo")},
                {TEXT("numpad3"),TEXT("NumPadThree")}, {TEXT("numpad4"),TEXT("NumPadFour")}, {TEXT("numpad5"),TEXT("NumPadFive")},
                {TEXT("numpad6"),TEXT("NumPadSix")}, {TEXT("numpad7"),TEXT("NumPadSeven")}, {TEXT("numpad8"),TEXT("NumPadEight")},
                {TEXT("numpad9"),TEXT("NumPadNine")}, {TEXT("numpadenter"),TEXT("Enter")}};
            if (const FString* Alias = Aliases.Find(Lower)) Canonical = *Alias;
        }
        UGameViewportClient* VC = GetWorld()->GetGameViewport();
        const FKey NativeKey(*Canonical);
        const bool bRouted = !Canonical.IsEmpty() && NativeKey.IsValid() && VC && VC->Viewport &&
                            (Phase == TEXT("down") || Phase == TEXT("up"));
        bool bHandled = false;
        if (bRouted)
        {
            const bool bDown = Phase == TEXT("down");
            bHandled = VC->InputKey(FInputKeyEventArgs(VC->Viewport,
                FInputDeviceId::CreateFromInternalId(0), NativeKey, bDown ? IE_Pressed : IE_Released));
            if (bDown) NativePressedKeys.Add(NativeKey.GetFName());
            else NativePressedKeys.Remove(NativeKey.GetFName());
        }
        auto Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("seq"), Seq);
        Row->SetStringField(TEXT("key"), Key);
        Row->SetStringField(TEXT("phase"), Phase);
        Row->SetStringField(TEXT("token"), NativeInputToken);
        Row->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
        Row->SetNumberField(TEXT("t_ms"), FPlatformTime::Seconds()*1000.0);
        Row->SetBoolField(TEXT("routed"), bRouted);
        Row->SetBoolField(TEXT("handled"), bHandled);
        Row->SetStringField(TEXT("source"), TEXT("UGameViewportClient::InputKey"));
        FString Line;
        FJsonSerializer::Serialize(Row, TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line));
        FFileHelper::SaveStringToFile(Line+TEXT("\n"), *FPaths::Combine(OutputDir,TEXT("native_input.jsonl")),
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    }
}

void UA3GamePlaytestRecorderSubsystem::Tick(float DeltaTime)
{
    if (bAudioPending)
    {
        const double Now = FPlatformTime::Seconds();
        const int64 Size = IFileManager::Get().FileSize(*FPaths::Combine(OutputDir, TEXT("audio.wav")));
        if (Size != AudioLastSize) { AudioLastSize = Size; AudioSizeChangedAt = Now; }
        if ((Size > 44 && Now - AudioSizeChangedAt >= 0.5) || Now - AudioStopAt >= 10.0)
        {
            const bool bCaptured = Size > 44 && Now - AudioSizeChangedAt >= 0.5;
            const FString Metadata = FString::Printf(
                TEXT("{\"status\":\"%s\",\"source\":\"game_output\",\"clock\":\"monotonic_session_ms\",\"start_t_ms\":0,")
                TEXT("\"synchronization_precision\":\"master submix buffer; not frame exact\",\"error\":\"%s\"}"),
                bCaptured ? TEXT("captured") : TEXT("capture_failed"),
                bCaptured ? TEXT("") : TEXT("wav_export_timeout_or_no_samples"));
            FFileHelper::SaveStringToFile(Metadata, *FPaths::Combine(OutputDir, TEXT("audio_capture.json")));
            bAudioPending = false;
            FPlatformMisc::RequestExit(false);
        }
        return;
    }
    if (!bArmed && !bRecording)
    {
        return;
    }
    if (bCaptureSlateUI)
    {
        UWorld* CaptureWorld = GetWorld();
        UGameViewportClient* VC = CaptureWorld ? CaptureWorld->GetGameViewport() : nullptr;
        // UE ProcessScreenShots otherwise falls back to viewport-only pixels.
        // Wait under the host deadline; never claim UI capture without Slate's
        // owning game window. This check also applies before later requests.
        if (!FSlateApplication::IsInitialized() || !VC || !VC->GetWindow().IsValid() ||
            GIsDumpingMovie || GIsHighResScreenshot) return;
    }
    if (!bRecording)
    {
        UWorld* World = GetWorld();
        if (World == nullptr || !World->HasBegunPlay())
        {
            // Still booting or loading the map; the take has not begun.
            return;
        }
        if (bRequireStartupFrame)
        {
            if (!bStartupFrameComplete)
            {
                if (!StartupFrameEndHandle.IsValid())
                {
                    StartupFrameArmedAt = FPlatformTime::Seconds();
                    StartupFrameArmedCounter = GFrameCounter;
                    StartupFrameEndHandle = FCoreDelegates::OnEndFrame.AddUObject(
                        this, &UA3GamePlaytestRecorderSubsystem::ObserveStartupFrameEnd);
                }
                // Host readiness timeout bounds this wait. No input polling,
                // capture, audio recording, or take-clock budget starts here.
                return;
            }
            if (GFrameCounter <= StartupFrameCompletedCounter) return;
            FCoreDelegates::OnEndFrame.Remove(StartupFrameEndHandle);
            StartupFrameEndHandle.Reset();
        }
        // Gameplay and the post-core-ticker boundary are observed. Establish
        // the unchanged full-duration take clock before any authored input.
        StartedAt = FPlatformTime::Seconds();
        NextCaptureAt = StartedAt;
        bRecording = true;
        if (FParse::Param(FCommandLine::Get(), TEXT("A3EventFrames")) && bSparse) A3EventFrames::Start();
        {   // opt-in state entry: before any authored input, at the take clock origin
            FString StateEntryPlan;
            if (FParse::Value(FCommandLine::Get(), TEXT("A3StateEntry="), StateEntryPlan))
                A3RunStateEntry(World, StateEntryPlan, OutputDir);
        }
        UAudioMixerBlueprintLibrary::StartRecordingOutput(World, static_cast<float>(DurationSeconds + 1.0), nullptr);
        FFileHelper::SaveStringToFile(TEXT("{\"status\":\"recording\",\"source\":\"game_output\"}"),
            *FPaths::Combine(OutputDir, TEXT("audio_capture.json")));
        if (bNativeSlateMouse)
        {
            UGameViewportClient* InputVC = World->GetGameViewport();
            if (InputVC && InputVC->GetWindow().IsValid())
            {
                NativeSlateWindow = InputVC->GetWindow();
                NativeSlateWindowId = FString::Printf(TEXT("%p"), InputVC->GetWindow().Get());
            }
        }
        WriteMarkerFile();
        UE_LOG(LogTemp, Log, TEXT("A3 playtest recorder started: %s (%.1f fps, %.2f sec)"), *FramesDir, 1.0 / CaptureInterval, DurationSeconds);
    }
    PollNativeInput();
    A3EntryTick(GetWorld());      // timed state-entry / direct-trigger calls (no-op when none)
    const double Now = FPlatformTime::Seconds();
    if (bSparse && (Now-StartedAt)*1000.0-LastClockObservationMs >= 50.0)
    {
        LastClockObservationMs = (Now-StartedAt)*1000.0;
        FString Clock = FString::Printf(TEXT("{\"t_ms\":%.6f,\"world_t_ms\":%.6f}\n"),
            LastClockObservationMs,GetWorld()->GetTimeSeconds()*1000.0);
        FFileHelper::SaveStringToFile(Clock,*FPaths::Combine(OutputDir,TEXT("clock_trace.jsonl")),
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
    }
    if (Now - StartedAt >= DurationSeconds)
    {
        StopRecording();
        WriteReportFile();
        // Opt-in end-of-take asset photos (game lighting + unlit) of the imported assets.
        FString AssetShotsPlan;
        if (FParse::Value(FCommandLine::Get(), TEXT("A3AssetShots="), AssetShotsPlan))
            A3CaptureAssetShots(GetWorld(), AssetShotsPlan, FPaths::Combine(OutputDir, TEXT("asset_shots")));
        // Finish the take like the Godot/Unity recorders do, so the host
        // does not sit through its kill timeout.
        UAudioMixerBlueprintLibrary::StopRecordingOutput(GetWorld(), EAudioRecordingExportType::WavFile,
            TEXT("audio"), OutputDir + TEXT("/"), nullptr, nullptr);
        bAudioPending = true;
        AudioStopAt = Now;
        AudioSizeChangedAt = Now;
        return;
    }
    if (bSparse)
    {
        if (!PendingSparsePath.IsEmpty() || FScreenshotRequest::IsScreenshotRequested()) return;
        const double TakeMs = (Now-StartedAt)*1000.0;
        bool bScheduledDue = SparseNextPoint < 0 || (SparseNextPoint < SparsePoints.Num() &&
            TakeMs >= SparseWarmupMs + SparsePoints[SparseNextPoint]->GetNumberField(TEXT("at_ms")));
        // Event frames only with spare capture time: the next scheduled slot is >= 400 ms away and scheduled
        // capture is not running behind (the last scheduled frame was taken within 300 ms of its slot).
        const double NextSlotMs = SparseNextPoint >= 0 && SparseNextPoint < SparsePoints.Num()
            ? SparseWarmupMs + SparsePoints[SparseNextPoint]->GetNumberField(TEXT("at_ms")) : 1e12;
        const bool bSpare = NextSlotMs - TakeMs >= 400.0 && A3EventFrames::ScheduledLagMs <= 300.0;
        if (!bScheduledDue && A3EventFrames::bActive && !bSpare) A3EventFrames::Drain(StartedAt);   // keep queue fresh
        if (!bScheduledDue && A3EventFrames::bActive && bSpare)
        {   // scheduled slots first; otherwise an event-triggered frame that is due
            A3EventFrames::Drain(StartedAt);
            while (A3EventFrames::Due.Num() && TakeMs - A3EventFrames::Due[0].Key > 400.0) A3EventFrames::Due.RemoveAt(0);
            if (A3EventFrames::Due.Num() && TakeMs >= A3EventFrames::Due[0].Key && A3EventFrames::Taken < A3EventFrames::MaxFrames)
            {
                TSharedPtr<FJsonObject> P = MakeShared<FJsonObject>();
                P->SetNumberField(TEXT("at_ms"), -1);
                TArray<TSharedPtr<FJsonValue>> Ids; Ids.Add(MakeShared<FJsonValueString>(A3EventFrames::Due[0].Value));
                P->SetArrayField(TEXT("capture_ids"), Ids);
                A3EventFrames::Due.RemoveAt(0); ++A3EventFrames::Taken;
                PendingSparsePoint = P;
                PendingSparseTimeMs = TakeMs;
                A3EventFrames::bPendingIsEvent = true;     // separate folder + index: scheduled-frame audits untouched
                PendingSparsePath = FPaths::Combine(OutputDir, TEXT("event_frames"),
                    FString::Printf(TEXT("e%05d.png"), A3EventFrames::Taken));
                FScreenshotRequest::RequestScreenshot(PendingSparsePath, bCaptureSlateUI, false);
                return;
            }
        }
        // Slow game: when scheduled capture is > 1 s behind, skip overdue context-only slots (no criterion) so the
        // action / criterion slots stay on time. Each skip is written to capture_skipped.jsonl.
        while (SparseNextPoint >= 0 && SparseNextPoint + 1 < SparsePoints.Num())
        {
            const TSharedPtr<FJsonObject>& P0 = SparsePoints[SparseNextPoint];
            const double Late = TakeMs - SparseWarmupMs - P0->GetNumberField(TEXT("at_ms"));
            const bool bContext = !P0->HasField(TEXT("criterion_ids")) || P0->GetArrayField(TEXT("criterion_ids")).Num() == 0;
            // secondary action frames (100 ms before / 300 ms after an action) may also go; each action keeps
            // its end-of-action and +1 s result frames
            bool bSecondary = P0->HasField(TEXT("capture_ids")) && P0->GetArrayField(TEXT("capture_ids")).Num() > 0;
            if (bSecondary)
                for (const TSharedPtr<FJsonValue>& C : P0->GetArrayField(TEXT("capture_ids")))
                {
                    const FString Id = C->AsString();
                    if (!Id.StartsWith(TEXT("pre/")) && !Id.StartsWith(TEXT("post300/")) && !Id.StartsWith(TEXT("baseline/")))
                    { bSecondary = false; break; }
                }
            if (Late <= 1000.0 || !(bContext || bSecondary)) break;
            FFileHelper::SaveStringToFile(FString::Printf(TEXT("{\"at_ms\":%.0f,\"late_ms\":%.1f,\"reason\":\"capture behind on a slow game; context-only or secondary action slot\"}\n"),
                P0->GetNumberField(TEXT("at_ms")), Late), *FPaths::Combine(OutputDir, TEXT("capture_skipped.jsonl")),
                FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
            ++SparseNextPoint;
        }
        if (SparseNextPoint >= SparsePoints.Num()) return;
        if (SparseNextPoint >= 0)
        {
            PendingSparsePoint = SparsePoints[SparseNextPoint];
            if ((Now-StartedAt)*1000.0 < SparseWarmupMs+PendingSparsePoint->GetNumberField(TEXT("at_ms")))
            { PendingSparsePoint.Reset(); return; }
        }
        PendingSparseTimeMs = (Now-StartedAt)*1000.0;
        if (PendingSparsePoint.IsValid())
            A3EventFrames::ScheduledLagMs = PendingSparseTimeMs - SparseWarmupMs - PendingSparsePoint->GetNumberField(TEXT("at_ms"));
        PendingSparsePath = FPaths::Combine(FramesDir,FString::Printf(TEXT("f%05d.png"),++FrameIndex));
        ++SparseNextPoint;
        FScreenshotRequest::RequestScreenshot(PendingSparsePath, bCaptureSlateUI, false);
        return;
    }
    if (Now < NextCaptureAt || FScreenshotRequest::IsScreenshotRequested())
    {
        return;
    }
    // Capture through the engine's screenshot pipeline (same as HighResShot):
    // it encodes a real PNG from the game viewport. Reading the viewport
    // with ReadPixels during the world tick hits an invalid render target
    // in -game mode and yields black frames. With the opt-in UI policy, UE
    // takes the owning game SWindow through Slate's RHI backbuffer readback;
    // this includes its UI, not desktop/foreground-window pixels. Preserve
    // the complete engine PNG: no resize, crop, or post-capture compositing.
    const FString Filename = FPaths::Combine(
        FramesDir,
        FString::Printf(TEXT("f%05d.png"), ++FrameIndex));
    FScreenshotRequest::RequestScreenshot(Filename, bCaptureSlateUI, false);
    NextCaptureAt += CaptureInterval;
}

TStatId UA3GamePlaytestRecorderSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(UA3GamePlaytestRecorderSubsystem, STATGROUP_Tickables);
}

bool UA3GamePlaytestRecorderSubsystem::IsTickable() const
{
    return bArmed || bRecording || bAudioPending;
}

// The recorded game may enter its own pause menu. The take clock uses wall time;
// keep the recorder's deadline, input relay and audio-export exit progressing
// while World::IsPaused, without unpausing or editing authored gameplay.
bool UA3GamePlaytestRecorderSubsystem::IsTickableWhenPaused() const
{
    return IsInitialized() && (bRecording || bAudioPending);
}
