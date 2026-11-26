#include "SnakeGame.h"
#include "Modules/ModuleManager.h"
#include "GameFramework/PlayerController.h"
#include "Components/InputComponent.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "HighResScreenshot.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/EngineVersion.h"
#include "Json.h"

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl,SnakeDemo,"SnakeDemo");
static const FIntPoint Foods[]={FIntPoint(5,2),FIntPoint(5,4),FIntPoint(2,4),FIntPoint(2,1)};
static FIntPoint VectorFor(const FString& A) {
    if(A=="RIGHT")return FIntPoint(1,0); if(A=="LEFT")return FIntPoint(-1,0);
    return A=="DOWN"?FIntPoint(0,1):FIntPoint(0,-1);
}
ASnakeGameMode::ASnakeGameMode(){HUDClass=ASnakeHUD::StaticClass();DefaultPawnClass=nullptr;}
void ASnakeHUD::Reset(){Body={FIntPoint(3,2),FIntPoint(2,2),FIntPoint(1,2)};Direction=Pending="RIGHT";Eaten=Ticks=0;Alive=true;Won=Paused=false;Elapsed=0;}
void ASnakeHUD::Turn(const FString& Action){if(VectorFor(Action)!=VectorFor(Direction)*-1)Pending=Action;}
void ASnakeHUD::Step(){
    if(!Alive||Won||Paused)return;
    Direction=Pending;auto Head=Body[0]+VectorFor(Direction);bool Eating=Head==Foods[Eaten];Ticks++;
    bool Collision=false;for(int32 I=0;I<Body.Num()-(Eating?0:1);I++)if(Body[I]==Head)Collision=true;
    if(Head.X<0||Head.X>=8||Head.Y<0||Head.Y>=6||Collision)Alive=false;
    else{Body.Insert(Head,0);if(Eating){Eaten++;Won=Eaten>=3;}else Body.Pop();}
}
void ASnakeHUD::Handle(const FString& A,bool Advance){if(A=="RESET")Reset();else{Turn(A);if(Advance)Step();}}
void ASnakeHUD::Right(){Handle("RIGHT",false);}void ASnakeHUD::Left(){Handle("LEFT",false);}
void ASnakeHUD::Up(){Handle("UP",false);}void ASnakeHUD::Down(){Handle("DOWN",false);}
void ASnakeHUD::Restart(){Reset();}void ASnakeHUD::Pause(){Paused=!Paused;}
void ASnakeHUD::BeginPlay(){
    Super::BeginPlay();PrimaryActorTick.bCanEverTick=true;SetActorTickEnabled(true);Reset();
    auto PC=GetOwningPlayerController();EnableInput(PC);
    InputComponent->BindKey(EKeys::Right,IE_Pressed,this,&ASnakeHUD::Right);InputComponent->BindKey(EKeys::D,IE_Pressed,this,&ASnakeHUD::Right);
    InputComponent->BindKey(EKeys::Left,IE_Pressed,this,&ASnakeHUD::Left);InputComponent->BindKey(EKeys::A,IE_Pressed,this,&ASnakeHUD::Left);
    InputComponent->BindKey(EKeys::Up,IE_Pressed,this,&ASnakeHUD::Up);InputComponent->BindKey(EKeys::W,IE_Pressed,this,&ASnakeHUD::Up);
    InputComponent->BindKey(EKeys::Down,IE_Pressed,this,&ASnakeHUD::Down);InputComponent->BindKey(EKeys::S,IE_Pressed,this,&ASnakeHUD::Down);
    InputComponent->BindKey(EKeys::R,IE_Pressed,this,&ASnakeHUD::Restart);InputComponent->BindKey(EKeys::SpaceBar,IE_Pressed,this,&ASnakeHUD::Pause);
    Testing=FParse::Value(FCommandLine::Get(),TEXT("SnakeOut="),Output);
    if(Testing){Output=FPaths::ConvertRelativePathToFull(Output);FFileHelper::LoadFileToStringArray(Actions,*(Output/"actions.txt"));NextAction=FPlatformTime::Seconds()+2;}
}
TSharedPtr<FJsonObject> ASnakeHUD::State() const {
    auto S=MakeShared<FJsonObject>();TArray<TSharedPtr<FJsonValue>> Points;
    for(auto P:Body){TArray<TSharedPtr<FJsonValue>> Pair={MakeShared<FJsonValueNumber>(P.X),MakeShared<FJsonValueNumber>(P.Y)};Points.Add(MakeShared<FJsonValueArray>(Pair));}
    S->SetArrayField("body",Points);S->SetStringField("direction",Direction);
    S->SetArrayField("food",{MakeShared<FJsonValueNumber>(Foods[Eaten].X),MakeShared<FJsonValueNumber>(Foods[Eaten].Y)});
    S->SetNumberField("foods",Eaten);S->SetBoolField("alive",Alive);S->SetBoolField("won",Won);S->SetNumberField("ticks",Ticks);return S;
}
void ASnakeHUD::SaveFrame(){
    auto R=MakeShared<FJsonObject>();R->SetNumberField("index",TestIndex);R->SetStringField("action",Actions[TestIndex]);R->SetObjectField("state",State());
    FString Screenshot=FString::Printf(TEXT("frames/%03d.png"),TestIndex);R->SetStringField("screenshot",Screenshot);Records.Add(MakeShared<FJsonValueObject>(R));
    FScreenshotRequest::RequestScreenshot(Output/Screenshot,false,false);
}
void ASnakeHUD::Finish(){
    FString Text;auto Writer=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Records,Writer);FFileHelper::SaveStringToFile(Text,*(Output/"trace.json"));
    auto Info=MakeShared<FJsonObject>();Info->SetStringField("engine","ue");Info->SetStringField("version",FEngineVersion::Current().ToString());
    Info->SetStringField("input","in-engine scripted commands through shared gameplay handler");
    Text.Empty();auto RuntimeWriter=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Info,RuntimeWriter);FFileHelper::SaveStringToFile(Text,*(Output/"runtime.json"));
    GetOwningPlayerController()->ConsoleCommand("quit");
}
void ASnakeHUD::Tick(float Delta){
    Super::Tick(Delta);
    if(Testing){
        if(FPlatformTime::Seconds()<NextAction||FScreenshotRequest::IsScreenshotRequested())return;
        if(TestIndex>=Actions.Num()){Finish();return;}
        Handle(Actions[TestIndex],true);SaveFrame();TestIndex++;NextAction=FPlatformTime::Seconds()+.3;
    }else{Elapsed+=Delta;if(Elapsed>=.3f){Elapsed=0;Step();}}
}
void ASnakeHUD::DrawHUD(){
    Super::DrawHUD();if(!Canvas)return;
    auto C=[](uint8 R,uint8 G,uint8 B){return FLinearColor::FromSRGBColor(FColor(R,G,B));};
    DrawRect(C(20,24,32),0,0,Canvas->SizeX,Canvas->SizeY);
    if(Won||!Alive)DrawRect(Won?C(35,135,70):C(165,35,45),24,12,744,65);
    FString Status=Won?"GOAL REACHED":!Alive?"GAME OVER":Paused?"PAUSED":"PLAYING";
    DrawText(FString::Printf(TEXT("UE SNAKE - %s  FOOD %d/3"),*Status,Eaten),FLinearColor::White,32,24,GEngine->GetLargeFont(),1.2f);
    for(int32 Y=0;Y<6;Y++)for(int32 X=0;X<8;X++)DrawRect(C(35,40,50),32+X*64,96+Y*64,63,63);
    if(!Won){auto F=Foods[Eaten];DrawRect(C(245,90,70),44+F.X*64,108+F.Y*64,40,40);}
    for(int32 I=0;I<Body.Num();I++){auto P=Body[I];DrawRect(I==0?C(100,240,140):C(45,170,90),37+P.X*64,101+P.Y*64,54,54);}
    DrawText(TEXT("Arrows / WASD: turn   R: restart   Space: pause\nEat 3 apples. Avoid walls and yourself."),FLinearColor::White,32,510,GEngine->GetSmallFont(),1.2f);
}
