'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
const fragment=source.slice(source.indexOf('  let replayTimer = null;'),source.indexOf('  function phaseName('));
const els=new Map();function el(id){if(!els.has(id))els.set(id,{listeners:{},replaceChildren(){},append(){},addEventListener(n,f){this.listeners[n]=f;}});return els.get(id);}
const state={snapshot:{read_only:true,step:0,max_step:3},at:0,requestVersion:0,busy:false};
const apiCalls=[];const timers=new Map();let seq=0,stopped=0;
const ctx=vm.createContext({state,$:el,node(){return {style:{},addEventListener(){}}},speechPlayer:{stop(){stopped++}},
 api:async(path,body)=>{apiCalls.push({path,body});return path==='/api/replays'?{replays:[]}:{};},
 refresh:async()=>{state.snapshot={read_only:true,step:state.at,max_step:3};},renderControls(){},notice(){},t:x=>x,openDialog(){},closeDialog(){},
 setTimeout:f=>{timers.set(++seq,f);return seq;},clearTimeout:id=>timers.delete(id)});
vm.runInContext(fragment,ctx);
(async()=>{
 await vm.runInContext('loadReplay({id:"saved"})',ctx);
 assert.equal(state.at,0);assert.equal(stopped,1);assert.equal(apiCalls[0].path,'/api/replays/load');
 apiCalls.length=0;
 await vm.runInContext('command("/api/step")',ctx);assert.equal(state.at,1);assert.equal(apiCalls.length,0);
 await vm.runInContext('command("/api/play")',ctx);assert.equal(timers.size,1);
 const [id,tick]=timers.entries().next().value;timers.delete(id);await tick();assert.equal(state.at,2);
 await vm.runInContext('command("/api/pause")',ctx);assert.equal(timers.size,0);assert.equal(apiCalls.length,0);
 console.log('Replay UI: load at start, mute old audio, local step/play/pause, and no inference control requests passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
