import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Flight,sampleGrid} from '../src/flight.js';
test('height sampling uses north-up coordinates and bounds',()=>{
 assert.equal(sampleGrid(new Float32Array([0,2,4,6]),2,2,1,1),3);
 assert.equal(sampleGrid(new Float32Array([0,2,4,6]),2,2,99,99),6);
});
test('actual movement and frame-rate independent flight',()=>{
 const a=new Flight(()=>0,()=>0),b=new Flight(()=>0,()=>0);
 for(let i=0;i<600;i++)a.update(1/60,{turn:.2,throttle:.3});
 for(let i=0;i<300;i++)b.update(1/30,{turn:.2,throttle:.3});
 assert.ok(Math.hypot(a.east-490,a.north-105)>100);
 assert.ok(Math.hypot(a.east-b.east,a.north-b.north)<.1);
 assert.ok(Math.abs(a.altitude-b.altitude)<.1);
});
test('terrain and obstacle clearance, bounds and stalled frame are bounded',()=>{
 const f=new Flight(()=>30,()=>75);f.altitude=12;
 for(let i=0;i<3000;i++)f.update(.1,{climb:-1,throttle:1});
 assert.ok(f.altitude>=84);assert.ok(f.east>=8&&f.east<=992&&f.north>=8&&f.north<=992);
 const before=f.time;f.update(10,{});assert.ok(f.time-before<.101);
 assert.ok(f.speed<=28);assert.ok(Number.isFinite(f.yaw));
});
test('reset returns all momentum to a known start',()=>{
 const f=new Flight(()=>0,()=>0);f.update(.1,{turn:1,mouseY:200});f.reset('village');
 assert.equal(f.east,860);assert.equal(f.turn,0);assert.equal(f.time,0);assert.equal(f.targetPitch,-.12);
});
