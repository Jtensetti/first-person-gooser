import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
const loader=new GLTFLoader();
const waterShaders=[];
export function animateWater(time){for(const s of waterShaders)s.uniforms.uWaterTime.value=time;}
function seaMaterial(material){
 material.color.set('#315b60');material.roughness=.27;material.metalness=.32;
 material.onBeforeCompile=shader=>{
  shader.uniforms.uWaterTime={value:0};
  shader.vertexShader='varying vec3 vSea;\n'+shader.vertexShader;
  shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvSea=(modelMatrix*vec4(position,1.)).xyz;');
  shader.fragmentShader='varying vec3 vSea; uniform float uWaterTime;\n'+shader.fragmentShader;
  shader.fragmentShader=shader.fragmentShader.replace('#include <normal_fragment_begin>','#include <normal_fragment_begin>\nvec3 ripple=vec3(sin(vSea.x*.13+vSea.z*.07+uWaterTime*.4)*.035,0.,cos(vSea.z*.17-vSea.x*.06+uWaterTime*.3)*.035); normal=normalize(normal+mat3(viewMatrix)*ripple);');
  waterShaders.push(shader);
 };
}

function mergeStatic(root){
 root.updateMatrixWorld(true);const bins=new Map();
 root.traverse(o=>{
  if(!o.isMesh)return;
  let g=o.geometry.clone().applyMatrix4(o.matrixWorld);
  if(g.index)g=g.toNonIndexed();
  const m=o.material;
  const key=m.uuid+'|'+Object.keys(g.attributes).sort().join(',');
  if(!bins.has(key))bins.set(key,{material:m,geometries:[],name:o.name});
  bins.get(key).geometries.push(g);
 });
 const group=new T.Group();
 for(const b of bins.values()){
  const g=mergeGeometries(b.geometries);if(!g)throw new Error('Could not merge landscape geometry');
  const mesh=new T.Mesh(g,b.material);mesh.name=b.name;mesh.receiveShadow=true;mesh.castShadow=true;
  mesh.material.envMapIntensity=.35;
  // Exported normal maps carry detail; correct sRGB is supplied by GLTFLoader.
  if(mesh.material.name.includes('water')){mesh.castShadow=false;mesh.receiveShadow=false;seaMaterial(mesh.material);}
  group.add(mesh);
 }
 return group;
}
function coloredPrototype(root,name){
 root.updateMatrixWorld(true);const parts=[];
 root.traverse(o=>{
  if(!o.isMesh)return;
  let parent=o,found=false;while(parent){if(parent.name.startsWith('asset-'+name))found=true;parent=parent.parent;}
  if(!found)return;
  let g=o.geometry.clone().applyMatrix4(o.matrixWorld);if(g.index)g=g.toNonIndexed();
  for(const key of Object.keys(g.attributes))if(!['position','normal'].includes(key))g.deleteAttribute(key);
  const c=o.material.color,colors=[];for(let i=0;i<g.attributes.position.count;i++)colors.push(c.r,c.g,c.b);
  g.setAttribute('color',new T.Float32BufferAttribute(colors,3));parts.push(g);
 });
 if(!parts.length)throw new Error('Missing vegetation prototype '+name);
 return mergeGeometries(parts);
}
function crownTexture(){
 const c=document.createElement('canvas');c.width=c.height=256;const ctx=c.getContext('2d');let s=472;
 const rnd=()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};
 ctx.strokeStyle='#554833';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(128,250);ctx.lineTo(126,94);ctx.stroke();
 for(let i=0;i<850;i++){
  const a=rnd()*Math.PI*2,r=Math.sqrt(rnd()),x=128+Math.cos(a)*r*105,y=112+Math.sin(a)*r*93;
  const light=50+rnd()*60+(1-r)*15;ctx.fillStyle=`rgb(${light*.76},${light},${light*.47})`;
  ctx.beginPath();ctx.ellipse(x,y,3+rnd()*8,2+rnd()*6,rnd()*3,0,7);ctx.fill();
 }
 const tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;return tex;
}
function farTree(){
 const pieces=[];
 for(const a of [0,Math.PI/2]){
  const g=new T.PlaneGeometry(.65,1);g.translate(0,.5,0);g.rotateY(a);pieces.push(g);
 }
 return {geometry:mergeGeometries(pieces),material:new T.MeshStandardMaterial({map:crownTexture(),alphaTest:.4,side:T.DoubleSide,roughness:1})};
}
export async function loadLandscape(scene,progress){
 const response=await fetch('./world/world.json');if(!response.ok)throw new Error('Pilotdata saknas. Kör stage_runtime.py först.');
 const manifest=await response.json();const all=[];let completed=0;
 if(manifest.horizon){
  const r=await fetch('./world/'+manifest.horizon);if(!r.ok)throw new Error('Omgivningen kunde inte läsas');
  const h=await r.json(),g=new T.BufferGeometry();
  g.setAttribute('position',new T.Float32BufferAttribute(h.positions,3));g.setAttribute('color',new T.Float32BufferAttribute(h.colors,3));g.setIndex(h.indices);g.computeVertexNormals();
  scene.add(new T.Mesh(g,new T.MeshStandardMaterial({vertexColors:true,roughness:.9})));
  if(h.water_indices?.length){const water=g.clone();water.deleteAttribute('color');water.setIndex(h.water_indices);water.computeVertexNormals();const mat=new T.MeshStandardMaterial();seaMaterial(mat);mat.envMapIntensity=.35;scene.add(new T.Mesh(water,mat));}
 }
 // Sequential GPU admission avoids four concurrent texture/geometry spikes.
 for(const tile of manifest.tiles){
  const gltf=await loader.loadAsync('./world/'+tile.glb);
  const group=mergeStatic(gltf.scene);group.position.set(tile.east,0,-tile.north);scene.add(group);
  const response=await fetch('./world/'+tile.instances);if(!response.ok)throw new Error('Växtdata kunde inte läsas');
  for(const p of await response.json())all.push({...p,x:tile.east+p.position[0],y:p.position[2],z:-(tile.north+p.position[1])});
  progress(++completed/6,`Landskapet ${completed} / 4`);
 }
 const proto=await loader.loadAsync('./world/prototype-assets.glb');progress(5/6,'Vingar, träd och sommarljus');
 const leaves=new T.MeshStandardMaterial({vertexColors:true,roughness:.88,side:T.DoubleSide});
 const highTree=new T.InstancedMesh(coloredPrototype(proto.scene,'broadleaf'),leaves,650);
 const far=farTree(),lowTree=new T.InstancedMesh(far.geometry,far.material,6000);
 highTree.castShadow=true;highTree.receiveShadow=true;lowTree.castShadow=false;
 const crops={};
 for(const kind of new Set(all.filter(p=>p.asset!=='broadleaf').map(p=>p.asset))){
  const obj=new T.InstancedMesh(coloredPrototype(proto.scene,kind),leaves,1600);obj.receiveShadow=true;obj.castShadow=false;crops[kind]=obj;scene.add(obj);
 }
 scene.add(highTree,lowTree);
 for(const m of [highTree,lowTree,...Object.values(crops)]){m.count=0;m.frustumCulled=false;m.instanceMatrix.setUsage(T.DynamicDrawUsage);}
 const dummy=new T.Object3D();const trees=all.filter(p=>p.asset==='broadleaf'),plants=all.filter(p=>p.asset!=='broadleaf');
 let lastX=Infinity,lastZ=Infinity,lastQuality='';
 function set(mesh,index,p){dummy.position.set(p.x,p.y,p.z);dummy.rotation.set(0,p.yaw,0);dummy.scale.setScalar(p.height_m);dummy.updateMatrix();mesh.setMatrixAt(index,dummy.matrix);}
 function update(east,north,quality,force=false){
  if(!force&&Math.hypot(east-lastX,-north-lastZ)<12&&lastQuality===quality)return;
  lastX=east;lastZ=-north;lastQuality=quality;
  const near=quality==='high'?160:quality==='light'?55:85;
  const limit=quality==='light'?150:quality==='high'?650:180;
  const ordered=trees.map(p=>({p,d:(p.x-east)**2+(p.z+north)**2})).sort((a,b)=>a.d-b.d);
  let hi=0,lo=0;
  for(const {p,d} of ordered){if(d>1050**2)continue;if(d<near**2&&hi<limit)set(highTree,hi++,p);else set(lowTree,lo++,p);}
  highTree.count=hi;lowTree.count=lo;highTree.instanceMatrix.needsUpdate=true;lowTree.instanceMatrix.needsUpdate=true;
  const counts={};for(const kind in crops)counts[kind]=0;
  const radius=quality==='high'?105:quality==='light'?40:70;
  for(const p of plants)if((p.x-east)**2+(p.z+north)**2<radius**2&&counts[p.asset]<1600)set(crops[p.asset],counts[p.asset]++,p);
  for(const kind in crops){crops[kind].count=counts[kind];crops[kind].instanceMatrix.needsUpdate=true;}
 }
 return {manifest,update,counts:()=>({treesNear:highTree.count,treesFar:lowTree.count,crops:Object.values(crops).reduce((a,m)=>a+m.count,0),sourceInstances:all.length})};
}

export function atmosphere(scene){
 const sky=new T.Mesh(new T.SphereGeometry(4000,32,20),new T.ShaderMaterial({side:T.BackSide,depthWrite:false,uniforms:{top:{value:new T.Color('#789baa')},horizon:{value:new T.Color('#dac7a2')}},vertexShader:'varying vec3 vP; void main(){vP=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',fragmentShader:'varying vec3 vP; uniform vec3 top; uniform vec3 horizon; void main(){float h=clamp(normalize(vP).y,0.,1.); vec3 col=mix(horizon,top,pow(h,.4)); float sun=pow(max(0.,dot(normalize(vP),normalize(vec3(-.6,.18,.7)))),400.); col+=vec3(1.,.68,.27)*sun*.9;gl_FragColor=vec4(col,1.);\n#include <tonemapping_fragment>\n #include <colorspace_fragment> }'}));
 scene.add(sky);scene.fog=new T.FogExp2('#bac1b1',.00125);
 scene.add(new T.HemisphereLight('#e2eff1','#8b815b',1.45));
 const sun=new T.DirectionalLight('#ffdfab',2.7);sun.position.set(-250,500,400);sun.target.position.set(500,0,-500);scene.add(sun,sun.target);
 sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-350,right:350,top:350,bottom:-350,near:10,far:1500});sun.shadow.bias=-.0003;sun.shadow.normalBias=.4;
 return {sun,sky};
}
