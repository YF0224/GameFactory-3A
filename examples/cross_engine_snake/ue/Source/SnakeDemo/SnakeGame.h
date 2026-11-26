#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameFramework/HUD.h"
#include "GameFramework/GameModeBase.h"
#include "SnakeGame.generated.h"

UCLASS()
class ASnakeHUD : public AHUD {
    GENERATED_BODY()
public:
    virtual void BeginPlay() override;
    virtual void Tick(float Delta) override;
    virtual void DrawHUD() override;
private:
    TArray<FIntPoint> Body;
    FString Direction, Pending, Output;
    int32 Eaten=0, Ticks=0, TestIndex=0;
    bool Alive=true, Won=false, Paused=false, Testing=false;
    float Elapsed=0;
    double NextAction=0;
    TArray<FString> Actions;
    TArray<TSharedPtr<FJsonValue>> Records;
    void Reset(); void Step(); void Turn(const FString& Action); void Handle(const FString& Action,bool Advance);
    void Right();void Left();void Up();void Down();void Restart();void Pause();
    void SaveFrame();void Finish();
    TSharedPtr<FJsonObject> State() const;
};

UCLASS()
class ASnakeGameMode : public AGameModeBase {
    GENERATED_BODY()
public:
    ASnakeGameMode();
};
