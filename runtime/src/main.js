import './style.css';
import * as T from 'three';
import {Flight,sampleGrid,clamp} from './flight.js';
import {createGoose} from './goose-camera.js';
import {loadLandscape,atmosphere,animateWater} from './landscape.js';

const $=id=>document.getElementById(id),canvas=$('world');
let renderer,scene,camera,foreground,gooseCamera,goose,landscape,flight;
let ready=false,started=false,playing=false,photo=false,quality='balanced',sensitivity=1,calm=matchMedia('(prefers-reduced-motion: reduce)').matches;
let last=performance.now(),elapsed=0,frameCount=0,mouseX=0,mouseY=0,toastUntil=0,lastToast='',soundEnabled=false,audio,windGain;
let dragging=false,dragX=0,dragY=0,lastRender=0;
canvas.tabIndex=0;
const keys=new Set(),frameTimes=[];
const metrics={ready:false,errors:[],frames:0,drawCalls:0,triangles:0,loadSeconds:0};
window.__GOOSEN__={getSnapshot:()=>({...metrics,playing,photo,pointerLocked:document.pointerLockElement===canvas,quality,flight:flight?.snapshot(),vegetation:landscape?.counts(),frameMs:frameTimes.length?frameTimes.reduce((a,b)=>a+b,0)/frameTimes.length:0})};
function toast(text,duration=4000){$('toast').textContent=text;$('toast').classList.add('visible');toastUntil=performance.now()+duration;}
function progress(f,text){$('loading-bar').style.width=Math.round(f*100)+'%';$('load-status').textContent=text;}
function clearInput(){keys.clear();mouseX=mouseY=0;dragging=false;}
function pause(){playing=false;clearInput();document.body.classList.remove('flying');if(document.pointerLockElement)document.exitPointerLock();}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());}
function openDialog(id){pause();photo=false;document.body.classList.remove('photo');$('photo-panel').hidden=true;closeDialogs();$(id).showModal();updateMap();}
async function lock(){try{await canvas.requestPointerLock();}catch{toast('Dra med vänster musknapp för att styra · A/D svänger · E/Q ändrar höjd',6500);}}
function fly(){
 if(!ready)return;closeDialogs();photo=false;$('photo-panel').hidden=true;document.body.classList.remove('photo');
 started=true;playing=true;clearInput();document.body.classList.add('started','flying');
 $('welcome').inert=true;$('welcome').setAttribute('aria-hidden','true');canvas.focus({preventScroll:true});
 if(audio?.state==='suspended')audio.resume();
 lock();toast('A/D svänger · W/S ändrar fart · E/Q ändrar höjd · Esc pausar',6500);
}
function photoMode(){if(!ready)return;pause();closeDialogs();photo=true;document.body.classList.add('photo');$('photo-panel').hidden=false;}
function exitPhoto(){photo=false;document.body.classList.remove('photo');$('photo-panel').hidden=true;openDialog('pause-dialog');}
function makeSound(){
 if(audio)return;
 audio=new AudioContext();const buffer=audio.createBuffer(1,audio.sampleRate*3,audio.sampleRate);const data=buffer.getChannelData(0);
 for(let i=0;i<data.length;i++)data[i]=Math.random()*2-1;
 const source=audio.createBufferSource();source.buffer=buffer;source.loop=true;const filter=audio.createBiquadFilter();filter.type='lowpass';filter.frequency.value=720;
 windGain=audio.createGain();windGain.gain.value=0;source.connect(filter).connect(windGain).connect(audio.destination);source.start();
}
$('fly-button').onclick=fly;$('resume-button').onclick=fly;
$('pause-button').onclick=()=>openDialog('pause-dialog');
document.querySelector('.brand').onclick=e=>{e.preventDefault();if(started)openDialog('pause-dialog');};
$('map-button').onclick=$('minimap-button').onclick=()=>openDialog('map-dialog');
$('settings-button').onclick=()=>openDialog('settings-dialog');$('help-button').onclick=()=>openDialog('help-dialog');
$('photo-button').onclick=photoMode;$('photo-close').onclick=exitPhoto;
$('restart-button').onclick=()=>{flight.reset();landscape.update(flight.east,flight.north,quality,true);fly();};
document.querySelectorAll('[data-place]').forEach(b=>b.onclick=()=>{flight.reset(b.dataset.place);landscape.update(flight.east,flight.north,quality,true);fly();});
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>{const resume=b.closest('dialog').id==='pause-dialog';closeDialogs();if(started){if(resume)fly();else openDialog('pause-dialog');}});
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('cancel',e=>{e.preventDefault();if(d.id!=='pause-dialog'){closeDialogs();if(started)openDialog('pause-dialog');}}));
$('quality').onchange=e=>{quality=e.target.value;resize();landscape?.update(flight.east,flight.north,quality,true);};
$('sensitivity').oninput=e=>sensitivity=Number(e.target.value);
$('fov').oninput=e=>{camera.fov=gooseCamera.fov=Number(e.target.value);camera.updateProjectionMatrix();gooseCamera.updateProjectionMatrix();goose.resize(gooseCamera.fov,gooseCamera.aspect);};
$('show-goose').onchange=e=>goose.root.visible=e.target.checked;
$('calm-camera').checked=calm;$('calm-camera').onchange=e=>calm=e.target.checked;
$('sound-button').onclick=()=>{makeSound();audio.resume();soundEnabled=!soundEnabled;$('sound-button').textContent=soundEnabled?'Ljud på':'Ljud av';$('sound-button').setAttribute('aria-pressed',String(soundEnabled));$('sound-button').setAttribute('aria-label',soundEnabled?'Stäng av vindljud':'Slå på vindljud');};
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{toast('Helskärm stöds inte här. Använd webbläsarens helskärmsläge.');}}
$('fullscreen-button').onclick=fullscreen;
$('capture-button').onclick=()=>{render();canvas.toBlob(blob=>{if(!blob){toast('Bilden kunde inte sparas');return;}const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='Gasen-Smygehuk-'+new Date().toISOString().replace(/[:.]/g,'-')+'.png';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);toast('Bilden sparas i Hämtade filer');},'image/png');};
canvas.addEventListener('pointerdown',e=>{if(playing&&e.button===0&&document.pointerLockElement!==canvas){dragging=true;dragX=e.clientX;dragY=e.clientY;canvas.setPointerCapture(e.pointerId);canvas.focus({preventScroll:true});}});
canvas.addEventListener('pointermove',e=>{if(playing&&dragging&&document.pointerLockElement!==canvas){mouseX+=(e.clientX-dragX)*sensitivity;mouseY+=(e.clientY-dragY)*sensitivity;dragX=e.clientX;dragY=e.clientY;}});
canvas.addEventListener('pointerup',()=>dragging=false);
canvas.addEventListener('pointercancel',()=>dragging=false);
canvas.addEventListener('dblclick',()=>{if(playing)lock();});
document.addEventListener('mousemove',e=>{if(playing&&document.pointerLockElement===canvas){mouseX+=e.movementX*sensitivity;mouseY+=e.movementY*sensitivity;}});
document.addEventListener('pointerlockchange',()=>{if(!document.pointerLockElement&&playing){openDialog('pause-dialog');}});
document.addEventListener('keydown',e=>{
 if(e.target.matches('input,select'))return;
 if(['Space','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code))e.preventDefault();
 if(e.repeat){keys.add(e.code);return;}
 if(e.code==='Escape'){if(photo)exitPhoto();else if(started&&!document.querySelector('dialog[open]'))openDialog('pause-dialog');return;}
 if(document.querySelector('dialog[open]'))return;
 if(e.code==='KeyM'&&started)openDialog('map-dialog');else if(e.code==='KeyP'&&started)photoMode();else if(e.code==='KeyF')fullscreen();else keys.add(e.code);
});
document.addEventListener('keyup',e=>keys.delete(e.code));
window.addEventListener('blur',()=>{if(playing)openDialog('pause-dialog');clearInput();});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&playing)openDialog('pause-dialog');});
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();pause();toast('Grafiken avbröts. Ladda om sidan för att fortsätta.',60000);metrics.errors.push('WebGL context lost');});
const labels=['N','NÖ','Ö','SÖ','S','SV','V','NV'];
for(let i=-16;i<=24;i++){const s=document.createElement('span');s.className='compass-label';s.textContent=labels[((i%8)+8)%8];$('compass-track').append(s);}
const mapImage=new Image();mapImage.src='./world/map.jpg';
function updateMap(){
 if(!flight||!mapImage.complete||!mapImage.naturalWidth)return;
 const ctx=$('minimap').getContext('2d');ctx.clearRect(0,0,240,240);ctx.save();ctx.translate(120,120);ctx.rotate(flight.yaw);ctx.scale(.5,.5);ctx.translate(-flight.east,-(1000-flight.north));ctx.drawImage(mapImage,0,0,1000,1000);ctx.strokeStyle='#f4e6b0';ctx.lineWidth=2;ctx.strokeRect(0,0,1000,1000);ctx.restore();
 // The dialog image is square-cropped to its container; use true map coordinates.
 $('map-position').style.left=flight.east/10+'%';$('map-position').style.top=(1000-flight.north)/10+'%';$('map-position').style.transform=`translate(-50%,-50%) rotate(${flight.yaw-Math.PI/2}rad)`;
}
function resize(){if(!renderer||!gooseCamera)return;const ratio=quality==='high'?Math.min(devicePixelRatio,1.6):quality==='light'?.8:Math.min(devicePixelRatio,1.15);renderer.setPixelRatio(ratio);renderer.setSize(innerWidth,innerHeight,false);camera.aspect=gooseCamera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();gooseCamera.updateProjectionMatrix();goose?.resize(gooseCamera.fov,gooseCamera.aspect);renderer.shadowMap.enabled=quality!=='light';}
window.addEventListener('resize',resize);
function render(){if(!renderer)return;renderer.info.reset();renderer.autoClear=true;renderer.render(scene,camera);renderer.autoClear=false;renderer.clearDepth();renderer.render(foreground,gooseCamera);metrics.drawCalls=renderer.info.render.calls;metrics.triangles=renderer.info.render.triangles;}
function tick(now){
 requestAnimationFrame(tick);const raw=(now-last)/1000;last=now;const dt=Math.min(raw,.05);elapsed+=dt;
 if(!ready||document.hidden)return;
 if(!playing&&now-lastRender<50)return;
 lastRender=now;
 if(playing){
  const has=key=>keys.has(key)?1:0;
  flight.update(dt,{turn:has('KeyD')+has('ArrowRight')-has('KeyA')-has('ArrowLeft'),throttle:has('KeyW')-has('KeyS'),climb:has('KeyE')+has('Space')+has('ArrowUp')-has('KeyQ')-has('ArrowDown'),level:has('KeyR'),mouseX,mouseY});
  mouseX=mouseY=0;
  if(flight.edge&&lastToast!=='edge'){toast('Pilotområdets kant · gåsen vänder inåt');lastToast='edge';}else if(!flight.edge)lastToast='';
 }
 camera.position.set(flight.east,flight.altitude,-flight.north);
 camera.rotation.set(flight.pitch-.2,-flight.yaw,calm?0:flight.bank*.35,'YXZ');
 goose.update(playing?flight.time:elapsed*.25,flight,calm);
 animateWater(elapsed);
 landscape.update(flight.east,flight.north,quality);
 if(frameCount++%8===0){
  $('altitude').textContent=Math.round(flight.agl);$('speed').textContent=Math.round(flight.speed*3.6);
  $('flight-state').textContent=flight.lift?'Säker höjd':flight.vertical>2?'Stiger':flight.vertical<-2?'Sjunker':'Segelflygning';
  const angle=((flight.yaw*180/Math.PI)%360+360)%360;
  $('compass-track').style.transform=`translateX(${-16*60-angle/45*60-30}px)`;
  $('heading').textContent=labels[Math.round(angle/45)%8]+' · '+Math.round(angle)+'°';updateMap();
 }
 if(now>toastUntil)$('toast').classList.remove('visible');
 if(windGain)windGain.gain.setTargetAtTime(soundEnabled&&playing?.025*(flight.speed/14):0,audio.currentTime,.3);
 render();metrics.frames++;if(playing){frameTimes.push(raw*1000);if(frameTimes.length>180)frameTimes.shift();}
}
async function start(){
 try{
  renderer=new T.WebGLRenderer({canvas,antialias:true,preserveDrawingBuffer:true,powerPreference:'high-performance'});renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=.98;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.info.autoReset=false;
  scene=new T.Scene();camera=new T.PerspectiveCamera(70,innerWidth/innerHeight,.3,5500);
  const lights=atmosphere(scene);
  const pmrem=new T.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(scene,.06,.1,5500).texture;pmrem.dispose();
  foreground=new T.Scene();gooseCamera=new T.PerspectiveCamera(70,innerWidth/innerHeight,.03,10);foreground.add(new T.HemisphereLight('#eaf1ef','#8b7852',1.4));const key=new T.DirectionalLight('#ffe4b9',2.2);key.position.set(-3,5,1);foreground.add(key);
  goose=await createGoose();foreground.add(goose.root);resize();requestAnimationFrame(tick);
  landscape=await loadLandscape(scene,progress);
  const [ground,clearance]=await Promise.all(['ground','clearance'].map(async n=>{const r=await fetch('./world/'+n+'.f32');if(!r.ok)throw new Error('Höjddata saknas');return new Float32Array(await r.arrayBuffer());}));
  const m=landscape.manifest;if(ground.length!==m.grid_size**2||clearance.length!==ground.length)throw new Error('Höjdmodellens storlek stämmer inte');
  const sample=data=>(e,n)=>sampleGrid(data,m.grid_size,m.step,e,n);
  flight=new Flight(sample(ground),sample(clearance));
  landscape.update(flight.east,flight.north,quality,true);
  camera.position.set(flight.east,flight.altitude,-flight.north);camera.rotation.set(flight.pitch-.2,-flight.yaw,0,'YXZ');
  await renderer.compileAsync(scene,camera);await renderer.compileAsync(foreground,gooseCamera);
  ready=metrics.ready=true;metrics.loadSeconds=performance.now()/1000;progress(1,'Redo när du är.');$('fly-label').textContent='Börja flyga';$('fly-button').disabled=false;
  lights.sun.target.updateMatrixWorld();
 }catch(error){console.error(error);metrics.errors.push(String(error));$('load-status').textContent='Kunde inte starta: '+error.message;$('load-status').classList.add('error');$('fly-label').textContent='Ladda om sidan';$('fly-button').disabled=false;$('fly-button').onclick=()=>location.reload();}
}
start();
