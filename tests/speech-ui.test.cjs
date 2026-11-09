'use strict';
// Exercise the shipped speech integration and manual event handlers with a tiny
// DOM and local speech API. No browser audio, network, or paid model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const controller = source.split('// BEGIN LOCAL SPEECH CONTROLLER')[1].split('// END LOCAL SPEECH CONTROLLER')[0];
const integration = source.slice(source.indexOf('  const speechPlayer = createSpeechPlayer'), source.indexOf('  function readLocale()'));
const renderer = source.slice(source.indexOf('  function renderEvents(events)'), source.indexOf('  function renderDossier()'));
const toggleHandler = source.slice(source.indexOf("  $('speech-toggle').addEventListener('click'"), source.indexOf("  window.addEventListener('pagehide'"));
assert.ok(controller && integration && renderer && toggleHandler, 'Locate the actual shipped speech code.');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
    this.listeners = {}; this.textContent = ''; this.hidden = false; this.disabled = false;
    this.isConnected = false; this.parentElement = null; this.scrollTop = 0;
    this.className = ''; this.classes = new Set();
    this.classList = { toggle: (name, enabled) => {
      const next = enabled === undefined ? !this.classes.has(name) : enabled;
      if (next) this.classes.add(name); else this.classes.delete(name);
      return next;
    } };
  }
  setConnected(connected) { this.isConnected = connected; this.children.forEach((child) => child.setConnected(connected)); }
  append(...children) {
    for (const child of children) { child.parentElement = this; child.setConnected(this.isConnected); this.children.push(child); }
  }
  replaceChildren(...children) { this.children.forEach((child) => child.setConnected(false)); this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  click() { this.listeners.click?.({ target: this }); }
  closest(selector) {
    for (let current = this; current; current = current.parentElement)
      if (selector === '.event' && current.className.split(/\s+/).includes('event')) return current;
    return null;
  }
  get scrollHeight() { return this.children.length * 20; }
}

function rig() {
  const elements = new Map();
  for (const id of ['speech-toggle', 'speech-status', 'seats', 'transcript', 'event-count']) {
    const element = new Element(); element.setConnected(true); elements.set(id, element);
  }
  const spoken = [], calls = { refresh: 0, render: 0, seats: 0 };
  const synth = {
    cancels: 0,
    getVoices() { return [{ lang: 'en-US', localService: true }, { lang: 'zh-CN', localService: true }]; },
    speak(utterance) { spoken.push(utterance); }, cancel() { this.cancels += 1; },
    addEventListener() {},
  };
  class Utterance { constructor(text) { this.text = text; } }
  const state = {
    locale: 'en', mode: 'mystery', followSeat: 1, at: null, snapshot: null,
    autoSpeech: false, speechEpoch: 0, speechScope: '', speechEvents: null,
    speechStep: null, speechError: '', speechGameLanguage: null, speechHandlingError: false,
    lastEventSignature: '', autoScroll: false,
  };
  function buttons() {
    const found = [];
    function walk(element) {
      if (element.dataset.speechKey !== undefined) found.push(element);
      element.children.forEach(walk);
    }
    walk(elements.get('transcript')); return found;
  }
  const context = vm.createContext({
    window: { speechSynthesis: synth, SpeechSynthesisUtterance: Utterance }, state,
    $: (id) => elements.get(id), document: { querySelectorAll: () => buttons() },
    t: (key, values = {}) => `${key}${values.name ? `:${values.name}` : ''}`,
    node: (tag, className = '', text) => {
      const element = new Element(tag); element.className = className;
      if (text !== undefined) element.textContent = String(text); return element;
    },
    getPlayers: () => state.snapshot?.players || [],
    playerName: (seat) => `Player ${seat}`,
    renderSeats: () => { calls.seats += 1; },
    eventText: (event) => event.text,
    phaseName: (phase) => phase || '',
    phaseIsNight: (event) => event.phase === 'night',
    isPrivate: (event) => event.audience !== 'public',
    refresh: () => { calls.refresh += 1; },
  });
  vm.runInContext(controller + '\n' + integration + '\n' + renderer + '\n' + toggleHandler + `
    function render() {
      renderEvents(state.snapshot?.events || []);
      syncSpeech(state.snapshot);
    }
    globalThis.ui = { speechPlayer, syncSpeech, resetSpeechView, changePerspective,
      renderSpeechControls, renderEvents, speechKey, speechLanguage };
  `, context);
  function deliver(events, extra = {}) {
    state.snapshot = { language: 'en', day: 1, step: events.length, events, players: [], ...extra };
    calls.render += 1;
    vm.runInContext('render()', context);
  }
  return { state, synth, spoken, calls, elements, buttons, deliver, ui: context.ui,
    toggle: () => elements.get('speech-toggle').click(),
    end(index = spoken.length - 1) { spoken[index].onend(); },
  };
}

function speech(text, seat = 1, kind = 'speech', audience = 'public') {
  return { kind, text, seat, audience, day: 1, phase: 'discussion' };
}
function narration(text) { return { kind: 'dawn', text, day: 1, phase: 'day', audience: 'public' }; }
let passed = 0;
function test(name, run) { run(); passed += 1; process.stdout.write(`ok ${passed} - ${name}\n`); }

test('initial history and enabling voice never auto-read existing dialogue', () => {
  const r = rig(), events = [narration('Dawn.'), speech('An old claim.')];
  r.deliver(events); assert.equal(r.spoken.length, 0); r.toggle();
  assert.equal(r.state.autoSpeech, true); assert.equal(r.ui.speechPlayer.enabled, true);
  r.deliver(JSON.parse(JSON.stringify(events))); assert.equal(r.spoken.length, 0);
});

test('new public referee announcements and player speech are read in order, once per event', () => {
  const r = rig(), events = [narration('Dawn.')]; r.deliver(events); r.toggle();
  const updated = [...events, narration('Speaking order.'), speech('A new claim.', 2)];
  r.deliver(updated); assert.equal(r.spoken.length, 1); assert.equal(r.spoken[0].text, 'Speaking order.');
  r.deliver(JSON.parse(JSON.stringify(updated))); assert.equal(r.spoken.length, 1);
  r.end(); assert.equal(r.spoken.length, 2); assert.equal(r.spoken[1].text, 'A new claim.');
  r.end(); r.deliver(updated); assert.equal(r.spoken.length, 2);
});

test('manual past-speech control does not enable automatic narration', () => {
  const r = rig(); r.state.locale = 'zh'; r.deliver([speech('Earlier English speech.', 3)]);
  const button = r.buttons()[0]; button.click();
  assert.equal(r.spoken.length, 1); assert.equal(r.spoken[0].text, 'Earlier English speech.');
  assert.equal(r.spoken[0].voice.lang, 'en-US'); assert.equal(r.state.autoSpeech, false);
  assert.equal(button.attributes['aria-pressed'], 'true');
  assert.match(button.attributes['aria-label'], /Player 3/);
  r.deliver([speech('Earlier English speech.', 3), speech('Later speech.', 4)]);
  assert.equal(r.spoken.length, 1);
});

test('manual playback toggle stops current speech without opting into auto', () => {
  const r = rig(); r.deliver([speech('Read this once.', 3)]); const button = r.buttons()[0];
  button.click(); assert.notEqual(r.ui.speechPlayer.currentKey, null);
  button.click(); assert.equal(r.ui.speechPlayer.currentKey, null);
  assert.equal(r.state.autoSpeech, false); assert.equal(r.spoken.length, 1);
});

test('cross-view changes cancel private queue and immediately remove old projection', () => {
  const r = rig(); r.state.mode = 'omniscient'; r.deliver([]); r.toggle();
  r.deliver([speech('Private wolf speech one.', 1, 'wolf_discussion', [1, 2]),
    speech('Private wolf speech two.', 2, 'wolf_discussion', [1, 2])]);
  const staleButton = r.buttons()[0], staleUtterance = r.spoken[0];
  r.state.mode = 'mystery'; r.ui.changePerspective();
  assert.equal(r.state.snapshot, null); assert.equal(r.ui.speechPlayer.currentKey, null);
  assert.equal(staleButton.isConnected, false); assert.equal(r.buttons().length, 0);
  assert.equal(r.calls.refresh, 1); staleUtterance.onend(); staleButton.click();
  assert.equal(r.spoken.length, 1);
  r.deliver([speech('Public history from this perspective.', 4)]);
  assert.equal(r.spoken.length, 1, 'New projection is a baseline, not automatic replay.');
});

test('replay never automatically narrates history or appended events', () => {
  const r = rig(); r.state.at = 8; r.deliver([speech('Historical speech.')], { step: 8 }); r.toggle();
  r.deliver([speech('Historical speech.'), speech('Another historical speech.')], { step: 8 });
  assert.equal(r.spoken.length, 0);
  r.buttons()[1].click(); assert.equal(r.spoken.length, 1, 'Explicit historical playback remains possible.');
});

test('returning to live establishes a fresh baseline before reading new speech', () => {
  const r = rig(); r.state.at = 3; r.deliver([speech('Historical speech.')]); r.toggle();
  r.state.at = null; r.ui.changePerspective(); r.deliver([speech('Old live speech.')]);
  assert.equal(r.spoken.length, 0);
  r.deliver([speech('Old live speech.'), speech('Fresh live speech.')]);
  assert.equal(r.spoken.length, 1); assert.equal(r.spoken[0].text, 'Fresh live speech.');
});

test('history shrink or a new-game reset cancels current and queued speech', () => {
  const r = rig(); r.deliver([]); r.toggle(); r.deliver([speech('Old one.'), speech('Old two.')], { step: 20 });
  const old = r.spoken[0]; r.deliver([], { step: 0 }); old.onend();
  assert.equal(r.ui.speechPlayer.currentKey, null); assert.equal(r.spoken.length, 1);
  r.deliver([speech('New game speech.')], { step: 1 });
  assert.equal(r.spoken.length, 2); assert.equal(r.spoken[1].text, 'New game speech.');
});

test('same-length changed event prefix cancels old audio without narrating replacement', () => {
  const r = rig(); r.deliver([]); r.toggle(); r.deliver([speech('Original speech.')]); const old = r.spoken[0];
  r.deliver([speech('Changed projection speech.')]); old.onend();
  assert.equal(r.ui.speechPlayer.currentKey, null); assert.equal(r.spoken.length, 1);
});

test('overflow disables auto playback, clears queue, and presents backlog status', () => {
  const r = rig(); r.deliver([]); r.toggle();
  const events = Array.from({ length: 6 }, (_, index) => speech(`Speech ${index}.`, index + 1));
  r.deliver(events); assert.equal(r.spoken.length, 1);
  assert.equal(r.state.autoSpeech, false); assert.equal(r.ui.speechPlayer.enabled, false);
  assert.equal(r.ui.speechPlayer.currentKey, null); assert.equal(r.state.speechError, 'queue_full');
  assert.equal(r.elements.get('speech-status').textContent, 'voiceBacklog');
  r.spoken[0].onend(); assert.equal(r.spoken.length, 1);
  r.toggle(); r.deliver(events); assert.equal(r.spoken.length, 1, 'Re-enabling does not replay discarded backlog.');
  r.deliver([...events, speech('Now caught up.', 7)]); assert.equal(r.spoken.length, 2);
});

test('a game language change revokes auto opt-in until the viewer enables the new language', () => {
  const r = rig(); r.deliver([]); r.toggle(); r.deliver([speech('English speech.')]); const old = r.spoken[0];
  r.ui.resetSpeechView(); r.deliver([], { language: 'zh', step: 0 }); old.onend();
  assert.equal(r.spoken.length, 1); assert.equal(r.state.autoSpeech, false);
  assert.equal(r.ui.speechPlayer.enabled, false); assert.equal(r.state.speechError, '');
  r.deliver([speech('中文发言。')], { language: 'zh', step: 1 });
  assert.equal(r.spoken.length, 1);
  r.toggle(); r.deliver([speech('中文发言。'), speech('新的中文发言。')], { language: 'zh', step: 2 });
  assert.equal(r.spoken.length, 2); assert.equal(r.spoken[1].voice.lang, 'zh-CN');
});

test('a throwing cancel API disables audio with bounded error handling, not recursive callbacks', () => {
  const r = rig(); r.deliver([]); r.toggle(); r.deliver([speech('An active speech.')]);
  let cancellations = 0;
  r.synth.cancel = () => { cancellations += 1; throw new Error('Synthetic browser cancellation failure.'); };
  assert.doesNotThrow(() => r.ui.speechPlayer.play('Manual replacement.', 'en', 'manual'));
  assert.equal(cancellations, 2, 'One failed cancellation plus one guarded cleanup cancellation.');
  assert.equal(r.state.autoSpeech, false); assert.equal(r.ui.speechPlayer.enabled, false);
  assert.equal(r.state.speechHandlingError, false); assert.equal(r.spoken.length, 1);
});

test('public referee playback is labeled as referee even when the event names a player', () => {
  const r = rig(); r.deliver([{...narration('Seat 3 self-explodes.'),kind:'explosion',seat:3}]);
  const button = r.buttons()[0]; button.click();
  assert.equal(r.spoken.length,1); assert.equal(r.spoken[0].text,'Seat 3 self-explodes.');
  assert.match(button.attributes['aria-label'], /referee/);
  assert.doesNotMatch(button.attributes['aria-label'], /Player 3/);
  assert.equal(r.elements.get('speech-status').textContent,'readingNow:referee');
});
test('private referee deliveries are not voiced or given play controls', () => {
  const r = rig(); r.state.mode='omniscient'; r.deliver([]); r.toggle();
  r.deliver([{...narration('PRIVATE_SEER_RESULT'),kind:'investigation',audience:'private',seat:4}]);
  assert.equal(r.spoken.length,0); assert.equal(r.buttons().length,0);
});

process.stdout.write(`${passed} speech UI integration tests passed.\n`);
