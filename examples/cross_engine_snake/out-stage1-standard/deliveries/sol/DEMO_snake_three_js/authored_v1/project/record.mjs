import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const [url,out,planFile]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,...(process.env.A3GAME_CHROMIUM?{executablePath:process.env.A3GAME_CHROMIUM}:{}),args:['--enable-webgl','--use-angle=swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:800,height:600},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(url+'?test=1');await page.waitForFunction(()=>window.snake);
 const plan=JSON.parse(fs.readFileSync(planFile,'utf8'));
 const trace=[];const keys={RESET:'r',RIGHT:'ArrowRight',LEFT:'ArrowLeft',UP:'ArrowUp',DOWN:'ArrowDown'};
 for(const [index,item] of plan.steps.entries()){
   await page.keyboard.press(keys[item.action]);
   const state=await page.evaluate(()=>window.snake.state());
   const screenshot=`frames/${String(index).padStart(3,'0')}.png`;
   await page.screenshot({path:path.join(out,screenshot)});
   trace.push({index,action:item.action,scenario:item.scenario,state,screenshot});
 }
 fs.writeFileSync(path.join(out,'trace.json'),JSON.stringify(trace,null,2)+'\n');
 fs.writeFileSync(path.join(out,'runtime.json'),JSON.stringify({engine:'threejs',three:'0.180.0',browser:browser.version(),input:'Playwright browser keyboard events',renderer:await page.evaluate(()=>window.snake.renderer),errors},null,2));
 if(errors.length)throw new Error(errors.join('\n'));
}finally{await browser.close();}
