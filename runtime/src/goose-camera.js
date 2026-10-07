import * as T from 'three';

/** Original generated camera art on a deforming mesh, deliberately not a full 3D animal. */
export async function createGoose(){
 const texture=await new T.TextureLoader().loadAsync('./art/goose-rider.png');
 texture.colorSpace=T.SRGBColorSpace;texture.anisotropy=4;
 const material=new T.MeshBasicMaterial({map:texture,transparent:true,depthTest:false,depthWrite:false,toneMapped:false});
 const uniforms={gooseTime:{value:0},gooseFlap:{value:0},gooseBank:{value:0}};
 material.onBeforeCompile=shader=>{
  Object.assign(shader.uniforms,uniforms);
  shader.vertexShader='uniform float gooseTime; uniform float gooseFlap; uniform float gooseBank;\n'+shader.vertexShader;
  shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
    float wing=smoothstep(.18,.8,abs(position.x));
    transformed.y+=sin(gooseTime)*gooseFlap*wing;
    transformed.y+=position.x*gooseBank;
    transformed.x+=sin(gooseTime*.31)*.0015*(1.-wing);`);
 };
 const root=new T.Mesh(new T.PlaneGeometry(2,2,64,32),material);root.position.z=-1;root.frustumCulled=false;root.renderOrder=100;
 function resize(fov,aspect){
  const half=Math.tan(T.MathUtils.degToRad(fov)/2),ratio=.9*Math.min(aspect,1.8)/1.5;
  root.scale.set(half*aspect*1.015,half*ratio*1.015,1);root.position.y=-half+half*ratio;
 }
 return {root,resize,update(time,flight,calm=false){
  uniforms.gooseTime.value=time*4.8;
  uniforms.gooseFlap.value=calm?0:flight.vertical>2?.055:.009;
  uniforms.gooseBank.value=calm?0:flight.bank*.025;
 }};
}
