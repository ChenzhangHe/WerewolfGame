'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
const path = require('node:path');
const appSource = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const controller = appSource.split('// BEGIN LOCAL SPEECH CONTROLLER')[1].split('// END LOCAL SPEECH CONTROLLER')[0];
vm.runInContext(controller, context);
const factory = context.createSpeechPlayer;
let passed = 0;
function test(name, run) { run(); passed += 1; process.stdout.write(`ok ${passed} - ${name}\n`); }
function rig(voices = [
  { name: 'Local English', lang: 'en-US', localService: true },
  { name: 'Local Chinese', lang: 'zh-CN', localService: true },
]) {
  const states = [], spoken = [], listeners = {};
  const synth = {
    voices, cancels: 0, getVoices() { return this.voices; },
    speak(utterance) { spoken.push(utterance); },
    cancel() { this.cancels += 1; },
    addEventListener(name, listener) { listeners[name] = listener; },
  };
  class Utterance { constructor(text) { this.text = text; } }
  const player = factory({ synth, Utterance, onState: (update) => states.push(update) });
  return { synth, states, spoken, listeners, player, Utterance };
}

test('construction and enable never play audio; disabled play is rejected', () => {
  const r = rig(); assert.equal(r.spoken.length, 0); assert.equal(r.player.enabled, false);
  assert.equal(r.player.play('Hello', 'en', 'one'), false);
  assert.equal(r.player.enable('en'), true); assert.equal(r.spoken.length, 0);
});
test('remote/default/mismatching/unspecified-local voices never enable', () => {
  for (const voice of [{ lang: 'en-US', localService: false }, { lang: 'en-US' }, { lang: 'zh-CN', localService: true }]) {
    const r = rig([voice]); assert.equal(r.player.enable('en'), false); assert.equal(r.player.enabled, false);
    assert.equal(r.player.play('Hello', 'en', 1), false); assert.equal(r.spoken.length, 0);
  }
});
test('English and Chinese select matching local voices only', () => {
  const r = rig(); r.player.enable('en'); assert.equal(r.player.play('Hello.', 'en', 'en1'), true);
  assert.equal(r.spoken[0].voice.name, 'Local English'); assert.equal(r.spoken[0].lang, 'en-US');
  r.player.enable('zh'); assert.equal(r.player.play('你好。', 'zh', 'zh1'), true);
  assert.equal(r.spoken[1].voice.name, 'Local Chinese'); assert.equal(r.player.play('Hello', 'en', 'bad'), false);
});
test('manual play cancels old audio and ignores stale completion/error', () => {
  const r = rig(); r.player.enable('en'); r.player.play('First.', 'en', 'one'); const old = r.spoken[0];
  r.player.play('Second.', 'en', 'two'); assert.equal(r.player.currentKey, 'two');
  old.onend(); old.onerror({ error: 'canceled' }); assert.equal(r.player.currentKey, 'two');
  r.spoken[1].onend(); assert.equal(r.player.currentKey, null);
});
test('stop and disable clear queued speech and protect cancellation callbacks', () => {
  const r = rig(); r.player.enable('en'); r.player.enqueue('One.', 'en', 1); r.player.enqueue('Two.', 'en', 2);
  const old = r.spoken[0]; r.player.stop(); old.onend(); assert.equal(r.spoken.length, 1); assert.equal(r.player.currentKey, null);
  assert.equal(r.player.enabled, true); r.player.play('Three.', 'en', 3); const third = r.spoken[1];
  r.player.disable(); third.onend(); assert.equal(r.player.enabled, false); assert.equal(r.player.currentKey, null);
});
test('synchronous cancel callback cannot end a new utterance', () => {
  const r = rig(); r.player.enable('en'); r.player.play('One.', 'en', 1);
  r.synth.cancel = () => r.spoken.at(-1)?.onend(); r.player.play('Two.', 'en', 2);
  assert.equal(r.player.currentKey, 2); assert.equal(r.spoken.length, 2);
});
test('queue is bounded to four waiting, duplicates excluded, overflow explicit', () => {
  const r = rig(); r.player.enable('en');
  for (let i = 0; i < 5; i++) assert.equal(r.player.enqueue(`Speech ${i}`, 'en', i), true);
  assert.equal(r.player.enqueue('Duplicate', 'en', 1), false);
  assert.equal(r.player.enqueue('Overflow', 'en', 5), false); assert.equal(r.states.at(-1).reason, 'queue_full');
  assert.equal(r.spoken.length, 1);
  for (let i = 0; i < 5; i++) r.spoken[i].onend();
  assert.equal(r.spoken.length, 5); assert.equal(r.player.currentKey, null);
});
test('manual play discards queued automatic playback', () => {
  const r = rig(); r.player.enable('en'); r.player.enqueue('One.', 'en', 1); r.player.enqueue('Two.', 'en', 2);
  r.player.play('Manual.', 'en', 'manual'); r.spoken[1].onend(); assert.equal(r.spoken.length, 2);
});
test('late voices notify availability without auto-enabling or playing', () => {
  const r = rig([]); assert.equal(r.player.enable('zh'), false);
  r.synth.voices.push({ lang: 'zh-CN', localService: true }); r.listeners.voiceschanged();
  assert.equal(r.states.at(-1).type, 'voiceschanged'); assert.equal(r.states.at(-1).available, true);
  assert.equal(r.player.enabled, false); assert.equal(r.spoken.length, 0); assert.equal(r.player.enable('zh'), true);
});
test('voice disappearance prevents fallback to remote default', () => {
  const r = rig(); r.player.enable('en'); r.synth.voices = [{ lang: 'en-US', localService: false }];
  assert.equal(r.player.play('Hello', 'en', 'one'), false); assert.equal(r.spoken.length, 0);
});
test('synthesis errors clear active/pending speech and notify safely', () => {
  const r = rig(); r.player.enable('en'); r.player.enqueue('One.', 'en', 1); r.player.enqueue('Two.', 'en', 2);
  r.spoken[0].onerror({ error: 'network' }); assert.equal(r.player.currentKey, null); assert.equal(r.spoken.length, 1);
  assert.equal(r.states.at(-1).reason, 'synthesis_interrupted');
});
test('speak and constructor failures are contained', () => {
  const r = rig(); r.player.enable('en'); r.synth.speak = () => { throw new Error('No audio'); };
  assert.equal(r.player.play('One.', 'en', 1), false); assert.equal(r.player.currentKey, null);
  const bad = factory({ synth: r.synth, Utterance: class { constructor() { throw new Error(); } } });
  bad.enable('en'); assert.equal(bad.play('One.', 'en', 1), false);
});
test('missing API and malformed or huge text fail without speech', () => {
  assert.equal(factory().enable('en'), false); const r = rig(); r.player.enable('en');
  for (const text of ['', '  ', null, {}, 'x'.repeat(1201)]) assert.equal(r.player.play(text, 'en', 1), false);
  assert.equal(r.player.play('Hello', 'en', {}), false); assert.equal(r.player.enable('fr'), false);
  assert.equal(r.spoken.length, 0);
});
test('state callback stop/disable reentrancy cannot accidentally start playback', () => {
  const r = rig(); let player;
  player = factory({ synth: r.synth, Utterance: r.Utterance, onState: (event) => { if (event.type === 'start') player.disable(); } });
  player.enable('en'); assert.equal(player.play('One.', 'en', 1), false); assert.equal(r.spoken.length, 0);
});
process.stdout.write(`${passed} local speech tests passed.\n`);
