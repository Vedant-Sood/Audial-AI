// Extracts Sanket tone features from CREMA-D with Sanket's own voice engine (exact feature parity).
// Usage: node training/sanket/extract_crema.mjs <wav dir> <audial splits.json> <out.jsonl>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const E = require('../../browser/sanket/engine.js');
const Tone = require('../../browser/sanket/tone.js');

const [wavDir, splitsPath, outPath] = process.argv.slice(2);
const splits = JSON.parse(fs.readFileSync(splitsPath, 'utf8'));
const splitOf = {};
for (const [name, v] of Object.entries(splits)) for (const f of v.files) splitOf[f] = name;
const EMO = { ANG: 'angry', DIS: 'disgust', FEA: 'fear', HAP: 'happy', NEU: 'neutral', SAD: 'sad' };

function readWav(file) {
  const b = fs.readFileSync(file);
  let o = 12, rate = 16000, ch = 1, bits = 16, data = null;
  while (o + 8 <= b.length) {
    const id = b.toString('ascii', o, o + 4), len = b.readUInt32LE(o + 4);
    if (id === 'fmt ') { ch = b.readUInt16LE(o + 10); rate = b.readUInt32LE(o + 12); bits = b.readUInt16LE(o + 22); }
    if (id === 'data') { data = b.subarray(o + 8, o + 8 + len); break; }
    o += 8 + len + (len & 1);
  }
  if (!data || bits !== 16) throw new Error('unsupported wav ' + file);
  const n = Math.floor(data.length / 2 / ch), x = new Float32Array(n);
  for (let i = 0; i < n; i++) x[i] = data.readInt16LE(i * 2 * ch) / 32768;
  return { x, rate };
}

const pad = (sec) => { const s = new Float32Array(Math.round(sec * 16000)); for (let i = 0; i < s.length; i++) s[i] = (Math.random() * 2 - 1) * 0.0003; return s; };
const files = Object.keys(splitOf).sort();
const out = fs.createWriteStream(outPath);
let done = 0, skipped = 0;
const t0 = Date.now();
for (const f of files) {
  const p = path.join(wavDir, f);
  if (!fs.existsSync(p)) { skipped++; continue; }
  let w;
  try { w = readWav(p); } catch (e) { skipped++; continue; }
  const frames = [];
  const eng = new E.VoiceEngine({ sampleRate: w.rate, onSpeechFrame: (fr) => frames.push(fr) });
  const sig = new Float32Array(pad(0.5).length * 2 + w.x.length);
  sig.set(pad(0.5), 0); sig.set(w.x, pad(0.5).length); sig.set(pad(0.5), pad(0.5).length + w.x.length);
  for (let i = 0; i < sig.length; i += 128) eng.process(sig.subarray(i, i + 128));
  const x = Tone.features(frames);
  const [actor, sentence, emo, level] = f.replace('.wav', '').split('_');
  out.write(JSON.stringify({ file: f, actor, sentence, emotion: EMO[emo], level, split: splitOf[f], frames: frames.length, x }) + '\n');
  if (++done % 1000 === 0) console.log(done, 'clips', ((Date.now() - t0) / 1000).toFixed(0) + 's');
}
out.end();
console.log('done', done, 'skipped', skipped);
