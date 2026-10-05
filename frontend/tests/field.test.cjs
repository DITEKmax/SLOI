// Deterministic canvas lifecycle checks; no browser or GPU required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/field.ts'), 'utf8');
const code = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2020}}).outputText + '\nglobalThis.SignalField = SignalField;';
let nextId = 0, draws = 0;
const timers = new Map(), frames = new Map(), docListeners = new Map(), motionListeners = new Map();
const motion = {matches: false, addEventListener: (k, f) => motionListeners.set(k, f), removeEventListener: k => motionListeners.delete(k)};
const document = {hidden: false, addEventListener: (k, f) => docListeners.set(k, f), removeEventListener: k => docListeners.delete(k)};
let observer;
const sandbox = {
 document, devicePixelRatio: 1, matchMedia: () => motion,
 ResizeObserver: class {constructor(callback) {this.callback = callback; observer = this} observe() {} disconnect() {this.disconnected = true}},
 requestAnimationFrame: callback => {const id = ++nextId; frames.set(id, callback); return id},
 cancelAnimationFrame: id => frames.delete(id),
 window: {setTimeout: (callback, delay) => {const id = ++nextId; timers.set(id, {callback, delay}); return id}, clearTimeout: id => timers.delete(id)}
};
vm.createContext(sandbox); vm.runInContext(code, sandbox);
const context = new Proxy({clearRect() {draws++}}, {get: (target, key) => target[key] || (() => {}), set: (target, key, value) => {target[key] = value; return true}});
const canvas = {width: 0, height: 0, getContext: () => context, getBoundingClientRect: () => ({width: 600, height: 180})};
let state = {theme: 'carbon', accent: '#c6f36b', progress: null, active: false, map: [], gpu: null};
const field = new sandbox.SignalField(canvas, () => state);
function step() {
 const first = timers.entries().next().value;
 assert.ok(first, 'expected a scheduled update'); timers.delete(first[0]); first[1].callback();
 const frame = frames.entries().next().value; assert.ok(frame); frames.delete(frame[0]); frame[1](1000);
}
function delay() {return timers.values().next().value.delay}
step(); assert.equal(draws, 1); assert.equal(delay(), 125, 'idle mode uses 8 fps');
state.active = true; field.refresh(); step(); assert.equal(draws, 2); assert.equal(delay(), 1000 / 30);
motion.matches = true; motionListeners.get('change')(); step(); assert.equal(draws, 3); assert.equal(delay(), 500);
step(); assert.equal(draws, 3, 'unchanged reduced-motion state does not redraw');
state.progress = 40; step(); assert.equal(draws, 4, 'new progress redraws a static reduced-motion frame');
document.hidden = true; docListeners.get('visibilitychange')(); assert.equal(timers.size, 0); assert.equal(frames.size, 0);
field.refresh(); assert.equal(timers.size, 0, 'hidden pages schedule no work');
document.hidden = false; docListeners.get('visibilitychange')(); step(); assert.equal(draws, 5);
field.destroy(); assert.equal(timers.size, 0); assert.equal(frames.size, 0); assert.equal(docListeners.size, 0); assert.equal(motionListeners.size, 0); assert.ok(observer.disconnected);
const noCanvasContext = new sandbox.SignalField({...canvas, getContext: () => null}, () => state);
assert.equal(timers.size, 0, 'unavailable canvas does not cause errors or schedule work'); noCanvasContext.destroy();
console.log('SignalField lifecycle checks passed: idle / active / reduced motion / visibility / cleanup.');
