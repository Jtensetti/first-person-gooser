export const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export const damp=(a,b,k,dt)=>a+(b-a)*(1-Math.exp(-k*dt));
export const angleDelta=(a,b)=>Math.atan2(Math.sin(b-a),Math.cos(b-a));
export function sampleGrid(data,size,step,east,north){
  const x=clamp(east/step,0,size-1),y=clamp(north/step,0,size-1);
  const i=Math.min(size-2,Math.floor(x)),j=Math.min(size-2,Math.floor(y));
  const u=x-i,v=y-j;
  return data[j*size+i]*(1-u)*(1-v)+data[j*size+i+1]*u*(1-v)+data[(j+1)*size+i]*(1-u)*v+data[(j+1)*size+i+1]*u*v;
}
export class Flight {
  constructor(ground,clearance){this.ground=ground;this.clearance=clearance;this.reset();}
  reset(place='harbour'){
    const p={harbour:[490,105,105,0],village:[860,550,85,-.4],fields:[260,730,100,Math.PI*.8]}[place];
    this.east=p[0];this.north=p[1];this.altitude=p[2];this.yaw=p[3];
    this.pitch=-.12;this.targetPitch=-.12;this.bank=0;this.turn=0;this.speed=14;this.targetSpeed=14;this.vertical=0;this.time=0;this.edge=false;this.lift=false;
  }
  update(dt,input={}){
    dt=clamp(dt,0,.1);
    this.targetPitch=clamp(this.targetPitch+(input.mouseY||0)*-.0015,-.48,.42);
    if(input.level)this.targetPitch=0;
    const steps=Math.max(1,Math.ceil(dt/(1/60))),h=dt/steps;
    const mouseTurn=dt?clamp((input.mouseX||0)*.0016/dt,-1,1):0;
    for(let i=0;i<steps;i++){
      this.time+=h;
      this.targetSpeed=clamp(this.targetSpeed+(input.throttle||0)*h*5,7,28);
      this.speed=damp(this.speed,this.targetSpeed,1.8,h);
      this.pitch=damp(this.pitch,this.targetPitch,3,h);
      const margin=Math.min(this.east,this.north,1000-this.east,1000-this.north);
      this.edge=margin<85;
      let turn=clamp((input.turn||0)*.7+mouseTurn,-1,1);
      if(this.edge){
        const home=Math.atan2(500-this.east,500-this.north);
        turn+=clamp(angleDelta(this.yaw,home)*2,-1.4,1.4)*clamp((85-margin)/55,0,1);
      }
      this.turn=damp(this.turn,turn,3.2,h);
      this.yaw+=this.turn*h;
      this.bank=damp(this.bank,-clamp(this.turn*.58,-.5,.5),3,h);
      this.east=clamp(this.east+Math.sin(this.yaw)*this.speed*Math.cos(this.pitch)*h,8,992);
      this.north=clamp(this.north+Math.cos(this.yaw)*this.speed*Math.cos(this.pitch)*h,8,992);
      const ahead=this.speed*1.5;
      const floor=Math.max(this.clearance(this.east,this.north),this.clearance(this.east+Math.sin(this.yaw)*ahead,this.north+Math.cos(this.yaw)*ahead))+9;
      const commanded=(input.climb||0)*9+this.speed*Math.sin(this.pitch);
      this.lift=this.altitude<floor+12;
      const v=this.lift?Math.max(commanded,(floor+12-this.altitude)*.9):commanded;
      this.vertical=damp(this.vertical,v,2.5,h);
      this.altitude=clamp(Math.max(floor,this.altitude+this.vertical*h),9,310);
    }
  }
  get agl(){return this.altitude-this.ground(this.east,this.north);}
  snapshot(){return {east:this.east,north:this.north,altitude:this.altitude,agl:this.agl,yaw:this.yaw,pitch:this.pitch,bank:this.bank,speed:this.speed,time:this.time,edge:this.edge,lift:this.lift};}
}
