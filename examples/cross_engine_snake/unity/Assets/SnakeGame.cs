using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

// A complete playable Unity Snake. The test driver uses the same command/step
// functions as keyboard play, with deterministic ticks and native screenshots.
public class SnakeGame : MonoBehaviour
{
    static readonly Vector2Int[] Foods = { new Vector2Int(5,2), new Vector2Int(5,4), new Vector2Int(2,4), new Vector2Int(2,1) };
    readonly List<Vector2Int> body = new List<Vector2Int>();
    string direction, pending;
    int eaten, ticks;
    bool alive, won, paused, recording;
    float elapsed;
    string output;
    readonly List<string> records = new List<string>();

    static Vector2Int Vector(string action) {
        switch(action) {
            case "RIGHT": return Vector2Int.right;
            case "LEFT": return Vector2Int.left;
            case "DOWN": return Vector2Int.up; // Board Y increases down the screen.
            default: return Vector2Int.down;
        }
    }
    void ResetGame() {
        body.Clear(); body.AddRange(new[]{new Vector2Int(3,2),new Vector2Int(2,2),new Vector2Int(1,2)});
        direction = pending = "RIGHT"; eaten = ticks = 0;
        alive = true; won = paused = false; elapsed = 0;
    }
    void Turn(string action) { if (Vector(action) != -Vector(direction)) pending=action; }
    void Step() {
        if (!alive || won || paused) return;
        direction=pending;
        var head=body[0]+Vector(direction);
        bool eating=head==Foods[eaten]; ticks++;
        bool collision=false;
        for(int i=0;i<body.Count-(eating?0:1);i++) if(body[i]==head) collision=true;
        if(head.x<0||head.x>=8||head.y<0||head.y>=6||collision) alive=false;
        else {
            body.Insert(0,head);
            if(eating) {eaten++; won=eaten>=3;} else body.RemoveAt(body.Count-1);
        }
    }
    void Handle(string action, bool advance) {
        if(action=="RESET") ResetGame(); else {Turn(action); if(advance)Step();}
    }
    void Start() {
        Application.targetFrameRate=30;
        Screen.SetResolution(800,600,false);
        ResetGame();
        var args=Environment.GetCommandLineArgs();
        for(int i=0;i<args.Length-1;i++) if(args[i]=="--snake-out") output=args[i+1];
        if(!String.IsNullOrEmpty(output)) {recording=true;StartCoroutine(RecordTest());}
    }
    void Update() {
        if(recording) return;
        if(Input.GetKeyDown(KeyCode.R)) Handle("RESET",false);
        if(Input.GetKeyDown(KeyCode.Space)) paused=!paused;
        if(Input.GetKeyDown(KeyCode.RightArrow)||Input.GetKeyDown(KeyCode.D))Handle("RIGHT",false);
        if(Input.GetKeyDown(KeyCode.LeftArrow)||Input.GetKeyDown(KeyCode.A))Handle("LEFT",false);
        if(Input.GetKeyDown(KeyCode.DownArrow)||Input.GetKeyDown(KeyCode.S))Handle("DOWN",false);
        if(Input.GetKeyDown(KeyCode.UpArrow)||Input.GetKeyDown(KeyCode.W))Handle("UP",false);
        elapsed+=Time.deltaTime;
        if(elapsed>=.3f){elapsed=0;Step();}
    }
    string StateJson() {
        var points=new List<string>(); foreach(var p in body)points.Add("["+p.x+","+p.y+"]");
        var f=Foods[eaten];
        return "{\"body\":["+String.Join(",",points)+"],\"direction\":\""+direction+"\",\"food\":["+f.x+","+f.y+"],\"foods\":"+eaten+",\"alive\":"+alive.ToString().ToLowerInvariant()+",\"won\":"+won.ToString().ToLowerInvariant()+",\"ticks\":"+ticks+"}";
    }
    IEnumerator RecordTest() {
        // Allow native window/screen resolution and IMGUI to settle.
        yield return null; yield return null;
        var actions=File.ReadAllLines(Path.Combine(output,"actions.txt"));
        for(int index=0;index<actions.Length;index++) {
            Handle(actions[index],true);
            yield return new WaitForEndOfFrame();
            string screenshot="frames/"+index.ToString("000")+".png";
            var texture=ScreenCapture.CaptureScreenshotAsTexture();
            File.WriteAllBytes(Path.Combine(output,screenshot),texture.EncodeToPNG());
            Destroy(texture);
            records.Add("{\"index\":"+index+",\"action\":\""+actions[index]+"\",\"state\":"+StateJson()+",\"screenshot\":\""+screenshot+"\"}");
            yield return null;
        }
        File.WriteAllText(Path.Combine(output,"trace.json"),"["+String.Join(",\n",records)+"]\n");
        File.WriteAllText(Path.Combine(output,"runtime.json"),JsonUtility.ToJson(new RuntimeInfo {version=Application.unityVersion,renderer=SystemInfo.graphicsDeviceName},true));
        Application.Quit(0);
    }
    [Serializable] class RuntimeInfo {
        public string engine="unity", version, renderer;
        public string input="in-engine scripted commands through shared gameplay handler";
    }
    static Color RGB(int r,int g,int b) {return new Color(r/255f,g/255f,b/255f,1);}
    static void Rect(float x,float y,float w,float h,Color color) {GUI.color=color;GUI.DrawTexture(new Rect(x,y,w,h),Texture2D.whiteTexture);GUI.color=Color.white;}
    void OnGUI() {
        Rect(0,0,800,600,RGB(20,24,32));
        if(won||!alive)Rect(24,12,744,65,won?RGB(35,135,70):RGB(165,35,45));
        var style=new GUIStyle(GUI.skin.label){fontSize=20};
        string status=won?"GOAL REACHED":!alive?"GAME OVER":paused?"PAUSED":"PLAYING";
        GUI.Label(new Rect(32,24,736,48),"UNITY SNAKE — "+status+" · FOOD "+eaten+"/3",style);
        for(int y=0;y<6;y++) for(int x=0;x<8;x++)Rect(32+x*64,96+y*64,63,63,RGB(35,40,50));
        if(!won){var f=Foods[eaten];Rect(44+f.x*64,108+f.y*64,40,40,RGB(245,90,70));}
        for(int i=0;i<body.Count;i++){var p=body[i];Rect(37+p.x*64,101+p.y*64,54,54,i==0?RGB(100,240,140):RGB(45,170,90));}
        GUI.Label(new Rect(32,510,736,60),"Arrows / WASD: turn   R: restart   Space: pause\nEat 3 apples. Avoid walls and yourself.",new GUIStyle(GUI.skin.label){fontSize=16});
    }
}
