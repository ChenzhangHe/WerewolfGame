'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const code=source.split('// BEGIN SAVED REPLAY LINK')[1].split('// END SAVED REPLAY LINK')[0];
async function check(search,fail=false){
 const calls=[];
 const ctx=vm.createContext({URLSearchParams,window:{location:{search}},loadReplay:async body=>{calls.push(['load',body.id]);if(fail)throw Error('Replay not found.');},refresh:async()=>calls.push(['refresh']),notice:(text)=>calls.push(['notice',text])});
 vm.runInContext(code,ctx);await vm.runInContext('initializeSession()',ctx);return calls;
}
(async()=>{
 assert.deepEqual(await check('?replay=codex-pair-28000-06'),[['load','codex-pair-28000-06']]);
 assert.deepEqual(await check(''),[['refresh']]);
 assert.deepEqual(await check('?replay=missing',true),[['load','missing'],['refresh'],['notice','Replay not found.']]);
 console.log('Saved replay links: explicit game, default session and rejected ID fallback passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
