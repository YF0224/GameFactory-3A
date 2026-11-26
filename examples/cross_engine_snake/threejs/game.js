import * as THREE from './node_modules/three/build/three.module.js';

const vectors = {RIGHT:[1,0],DOWN:[0,1],LEFT:[-1,0],UP:[0,-1]};
const foods = [[5,2],[5,4],[2,4],[2,1]];
const test = new URLSearchParams(location.search).has('test');
let body, direction, pending, eaten, alive, won, ticks, paused;
function reset() {
  body=[[3,2],[2,2],[1,2]]; direction=pending='RIGHT';
  eaten=ticks=0; alive=true; won=false; paused=false;
}
function turn(action) {
  const a=vectors[action], b=vectors[direction];
  if (a[0]!==-b[0] || a[1]!==-b[1]) pending=action;
}
function step() {
  if (!alive || won || paused) return;
  direction=pending;
  const v=vectors[direction], head=[body[0][0]+v[0],body[0][1]+v[1]];
  const eating=JSON.stringify(head)===JSON.stringify(foods[eaten]);
  const occupied=eating ? body : body.slice(0,-1);
  ticks++;
  if (head[0]<0||head[0]>=8||head[1]<0||head[1]>=6||occupied.some(p=>p[0]===head[0]&&p[1]===head[1])) alive=false;
  else {body.unshift(head); if(eating){eaten++;won=eaten>=3;} else body.pop();}
}
function state(){return {body:body.map(p=>[...p]),direction,food:foods[eaten],foods:eaten,alive,won,ticks};}
const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});
renderer.setSize(800,600); renderer.setPixelRatio(1);
renderer.setClearColor(0x141820); document.body.appendChild(renderer.domElement);
const scene=new THREE.Scene(), camera=new THREE.OrthographicCamera(0,800,0,600,-10,10);
const geometry=new THREE.PlaneGeometry(1,1);
const materials=Object.fromEntries(Object.entries({grid:0x232832,head:0x64f08c,body:0x2daa5a,food:0xf55a46,win:0x238746,dead:0xa5232d}).map(([k,color])=>[k,new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide})]));
const meshes=[];
function rect(x,y,w,h,kind){const mesh=new THREE.Mesh(geometry,materials[kind]);mesh.position.set(x+w/2,y+h/2,0);mesh.scale.set(w,h,1);scene.add(mesh);meshes.push(mesh);}
function render(){
  for(const m of meshes)scene.remove(m);meshes.length=0;
  if(won||!alive)rect(24,12,744,65,won?'win':'dead');
  for(let y=0;y<6;y++)for(let x=0;x<8;x++)rect(32+x*64,96+y*64,63,63,'grid');
  if(!won){const f=foods[eaten];rect(32+f[0]*64+12,96+f[1]*64+12,40,40,'food');}
  body.forEach((p,i)=>rect(32+p[0]*64+5,96+p[1]*64+5,54,54,i===0?'head':'body'));
  document.querySelector('#title').textContent=`THREE.JS SNAKE — ${won?'GOAL REACHED':!alive?'GAME OVER':paused?'PAUSED':'PLAYING'} · FOOD ${eaten}/3`;
  renderer.render(scene,camera);
}
const keys={ArrowRight:'RIGHT',KeyD:'RIGHT',ArrowLeft:'LEFT',KeyA:'LEFT',ArrowUp:'UP',KeyW:'UP',ArrowDown:'DOWN',KeyS:'DOWN'};
addEventListener('keydown',e=>{
  if(e.repeat)return;
  if(keys[e.code]){e.preventDefault();turn(keys[e.code]);if(test)step();}
  else if(e.code==='KeyR')reset();
  else if(e.code==='Space'){e.preventDefault();paused=!paused;}
  render();
});
reset();render();
if(!test)setInterval(()=>{step();render();},300);
// Read-only observation. Tests drive real browser key events through the listener above.
window.snake={state,renderer:renderer.getContext().getParameter(renderer.getContext().RENDERER)};
