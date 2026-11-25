/** Native GLB -> fixed, textured multi-view evidence. No vendor previews. */
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const [assetArg, outputArg, playwrightArg, browserArg, presetArg] = process.argv.slice(2);
if (!assetArg || !outputArg || !playwrightArg) throw Error('usage: render.mjs model.glb output_dir playwright_root [browser]');
const asset = path.resolve(assetArg), out = path.resolve(outputArg);
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const {chromium} = require(path.resolve(playwrightArg, 'node_modules/playwright'));
const threeRoot = path.join(here, 'node_modules/three');
const roots = {'/three/':threeRoot, '/asset/':path.dirname(asset)};
const html = `<!doctype html><html><head><style>body{margin:0}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script></head>
<body><script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';
import {KTX2Loader} from 'three/addons/loaders/KTX2Loader.js';
import {MeshoptDecoder} from 'three/addons/libs/meshopt_decoder.module.js';
window.ready = (async()=>{
const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
renderer.setSize(768,768); renderer.setPixelRatio(1);
renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure=1; document.body.appendChild(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color('#c4cad1');
scene.add(new THREE.HemisphereLight(0xffffff,0x4b5263,2.2));
for(const [pos,power] of [[[4,6,5],3], [[-4,3,-3],2], [[0,4,-5],1.5]]){
 const l=new THREE.DirectionalLight(0xffffff,power);l.position.set(...pos);scene.add(l);
}
const loader=new GLTFLoader();const draco=new DRACOLoader();
draco.setDecoderPath('/three/examples/jsm/libs/draco/gltf/');loader.setDRACOLoader(draco);
const ktx=new KTX2Loader().setTranscoderPath('/three/examples/jsm/libs/basis/').detectSupport(renderer);
loader.setKTX2Loader(ktx);loader.setMeshoptDecoder(MeshoptDecoder);
const gltf=await loader.loadAsync('/asset/'+${JSON.stringify(encodeURIComponent(path.basename(asset)))});
const object=gltf.scene;
// Evidence uses one fixed light rig for all assets. Preserve authored light
// settings in facts, but do not add their energy to the measurement fixture.
// glTF directional intensity can be hundreds of lux and clip this view rig.
const authoredLights=[];
object.traverse(o=>{if(o.isLight){authoredLights.push({name:o.name,type:o.type,
 intensity:o.intensity,color:o.color.toArray(),original_visible:o.visible});o.visible=false;}});
object.updateMatrixWorld(true);
const box=new THREE.Box3().setFromObject(object);const size=box.getSize(new THREE.Vector3());
if(box.isEmpty() || !Number.isFinite(size.length()) || size.length()<=0)throw Error('empty/invalid geometry');
const native={min:box.min.toArray(),max:box.max.toArray(),size:size.toArray()};
const center=box.getCenter(new THREE.Vector3());object.position.sub(center);scene.add(object);
// The same native asset and material graph are used for every camera. No mesh repair/scaling.
const radius=size.length()/2;const camera=new THREE.PerspectiveCamera(35,1,radius/100, radius*100);
let triangles=0,vertices=0,meshes=0;const textures=new Set();const materials=new Set();
object.traverse(o=>{if(o.isMesh){meshes++;const g=o.geometry;vertices+=g.attributes.position?.count||0;
triangles+=(g.index?g.index.count:g.attributes.position?.count||0)/3;
for(const m of (Array.isArray(o.material)?o.material:[o.material])){materials.add(m.uuid);
for(const v of Object.values(m))if(v?.isTexture)textures.add(v.uuid);}}});
window.facts={three_revision:THREE.REVISION, renderer:'three-webgl-native-materials',native_bbox:native,
lighting_protocol:'fixed-fixture-authored-lights-disabled.v2',authored_lights:authoredLights,
scale_calibrated:false, triangles,vertices,meshes,materials:materials.size,textures:textures.size,
webgl:renderer.getContext().getParameter(renderer.getContext().VERSION), animations:gltf.animations.length};
window.view=async function(azimuth,elevation,zoom=1,target=[0,0,0]){
const a=azimuth*Math.PI/180,e=elevation*Math.PI/180;
const dist=radius/Math.sin(camera.fov*Math.PI/360)*1.12*zoom;
camera.position.set(dist*Math.sin(a)*Math.cos(e),dist*Math.sin(e),dist*Math.cos(a)*Math.cos(e));
camera.position.add(new THREE.Vector3(...target));
camera.lookAt(...target);camera.updateProjectionMatrix();renderer.render(scene,camera);
await new Promise(r=>requestAnimationFrame(r));};
await window.view(0,15);return true;
})();window.ready.catch(e=>window.renderError=String(e));
</script></body></html>`;
const mime = p=>({'.js':'text/javascript','.wasm':'application/wasm','.glb':'model/gltf-binary','.png':'image/png','.jpg':'image/jpeg','.ktx2':'image/ktx2'}[path.extname(p)]||'application/octet-stream');
const server=http.createServer(async(req,res)=>{
 try{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/'){res.setHeader('Content-Type','text/html');return res.end(html);}
  const prefix=Object.keys(roots).find(p=>url.pathname.startsWith(p));if(!prefix){res.writeHead(404);return res.end();}
  const root=await fs.realpath(roots[prefix]);const target=await fs.realpath(path.resolve(root,decodeURIComponent(url.pathname.slice(prefix.length))));
  if(!target.startsWith(root+path.sep)){res.writeHead(403);return res.end();}
  res.setHeader('Content-Type',mime(target));res.end(await fs.readFile(target));
 }catch{res.writeHead(404);res.end();}
});
let browser;
try{
 await fs.mkdir(out,{recursive:true});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,...(browserArg?{executablePath:browserArg}:{}),args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:768,height:768},deviceScaleFactor:1});
 // Asset URIs cannot cause external network fetches, including redirects.
 await page.route('**/*',route=>{const u=route.request().url();return (u.startsWith(origin+'/')||u.startsWith('data:')||u.startsWith('blob:'))?route.continue():route.abort();});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 page.on('requestfailed',r=>errors.push('request failed: '+r.url()));
 await page.goto(origin,{waitUntil:'networkidle',timeout:120000});
 await page.evaluate(()=>window.ready);
 const facts=await page.evaluate(()=>window.facts);
 const objectViews=[['front',0,10],['right',90,10],['back',180,10],['left',270,10],['top_oblique',45,60],['bottom_oblique',225,-40]];
 const sceneViews=[['global',45,30],['top',0,89],['global_side',135,20],
 ['region_nw',45,55,0.6,[-0.25,0,-0.25]],['region_ne',45,55,0.6,[0.25,0,-0.25]],
 ['region_sw',225,55,0.6,[-0.25,0,0.25]],['region_se',225,55,0.6,[0.25,0,0.25]]];
 const views=presetArg==='scene'?sceneViews:objectViews;
 const nativeSize=facts.native_bbox.size;
 const evidence=[];
 for(const [id,a,e,zoom=1,region=[0,0,0]] of views){const target=region.map((v,i)=>v*nativeSize[i]);
 await page.evaluate(([a,e,z,t])=>window.view(a,e,z,t),[a,e,zoom,target]);
 const filename=id+'.png';await page.screenshot({path:path.join(out,filename)});evidence.push({id,filename,azimuth_deg:a,elevation_deg:e,zoom,target_normalized:region,target_native:target});}
 if(errors.length)throw Error('renderer resource/errors: '+errors.join('; '));
 await fs.writeFile(path.join(out,'render.json'),JSON.stringify({facts,preset:presetArg||'object',normalization:{translation:'negative native bbox center',scale:1,background:'#c4cad1',image_size:[768,768]},views:evidence,lighting:'fixed hemisphere + three white directional lights',browser:browser.version()},null,2));
 console.log(JSON.stringify({status:'ok',views:evidence.length,three_revision:facts.three_revision}));
}finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
