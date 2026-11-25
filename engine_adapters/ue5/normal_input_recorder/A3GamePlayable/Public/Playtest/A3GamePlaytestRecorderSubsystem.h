#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"
#include "Subsystems/WorldSubsystem.h"
#include "A3GamePlaytestRecorderSubsystem.generated.h"

class FSocket;
class SWindow;
class SWidget;
class FJsonObject;
class FSlateVirtualUserHandle;

UCLASS()
class A3GAMEPLAYABLE_API UA3GamePlaytestRecorderSubsystem
    : public UTickableWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickable() const override;
    virtual bool IsTickableWhenPaused() const override;

private:
    void StartFromCommandLine();
    // Map travel: the outgoing world's recorder hands its live take to the next world's recorder.
    void SaveTakeForNextWorld();
    void RestoreTakeFromPreviousWorld();
    bool bHandedOver = false;
    void ObserveStartupFrameEnd();
    bool bCaptureSlateUI = false;
    bool bRequireStartupFrame = false;
    bool bStartupFrameComplete = false;
    FDelegateHandle StartupFrameEndHandle;
    double StartupFrameArmedAt = 0.0;
    double StartupFrameCompletedAt = 0.0;
    uint64 StartupFrameArmedCounter = 0;
    uint64 StartupFrameCompletedCounter = 0;
    void PollNativeInput();
    void CloseNativeInput();
    void RouteNativeSlateMouse(const TSharedPtr<FJsonObject>& Message, double Seq);
    void RouteNativeViewportPointer(const TSharedPtr<FJsonObject>& Message, double Seq);
    FVector2D NativeViewportPoint = FVector2D(-1, -1);
    int64 NativeViewportLastSeq = -1;
    void CloseNativeSlateMouse();
    bool bNativeSlateMouse = false;
    bool bNativeSlateClosed = false;
    int32 NativeSlateUser = INDEX_NONE;
    int32 NativeSlateVirtualSlot = INDEX_NONE;
    TSharedPtr<FSlateVirtualUserHandle> NativeSlateUserHandle;
    TWeakPtr<SWindow> NativeSlateWindow;
    FString NativeSlateWindowId;
    TSet<FKey> NativeSlateButtons;
    TWeakPtr<SWidget> NativeSlateButton;
    FString NativeSlateAction;
    FVector2D NativeSlatePoint = FVector2D::ZeroVector;
    FVector2D NativeSlateFraction = FVector2D::ZeroVector;
    int64 NativeSlateLastSeq = -1;
    FSocket* NativeInputSocket = nullptr;
    FString NativeInputToken;
    int32 NativeInputPort = 0;
    TSet<FName> NativePressedKeys;
    void StopRecording();
    void WriteMarkerFile() const;
    void WriteReportFile() const;
    void FinishSparseScreenshot();
    TArray<TSharedPtr<class FJsonObject>> SparsePoints;
    TSharedPtr<class FJsonObject> PendingSparsePoint;
    FString PendingSparsePath;
    double PendingSparseTimeMs = 0.0;
    double SparseWarmupMs = 1000.0;
    int32 SparseNextPoint = -1;
    bool bSparse = false;
    double LastClockObservationMs = -100.0;
    FDelegateHandle ScreenshotProcessedHandle;

    FString OutputDir;
    FString FramesDir;
    double StartedAt = 0.0;
    double NextCaptureAt = 0.0;
    double DurationSeconds = 0.0;
    double CaptureInterval = 0.05;
    int32 FrameIndex = 0;
    bool bArmed = false;
    bool bRecording = false;
    bool bAudioPending = false;
    double AudioStopAt = 0.0;
    double AudioSizeChangedAt = 0.0;
    int64 AudioLastSize = -1;
};
