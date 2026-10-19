// Rasterize reviewed sign poses into on/off lights. This module does not invent signs.
const HAND_LINKS = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[0,17],[17,18],[18,19],[19,20]];
const BODY_LINKS = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24]];

function checkPoints(points, count, name) {
  if (!Array.isArray(points) || (count !== null && points.length !== count) || points.length > 500) throw new Error(`Invalid ${name} landmarks.`);
  for (const point of points) {
    if (!Array.isArray(point) || point.length < 2 || !point.every(Number.isFinite) || point[0] < 0 || point[0] > 1 || point[1] < 0 || point[1] > 1) throw new Error(`Invalid ${name} coordinates.`);
  }
}

export function validateSequence(sequence) {
  if (!sequence || typeof sequence.gloss !== "string" || !sequence.gloss.trim() || !Array.isArray(sequence.frames) || sequence.frames.length < 1 || sequence.frames.length > 6000) throw new Error("Invalid pose sequence.");
  let previous = -1;
  for (const frame of sequence.frames) {
    if (!Number.isFinite(frame.timeMs) || frame.timeMs < 0 || frame.timeMs <= previous || frame.timeMs > 60000) throw new Error("Frames need increasing timestamps within one minute.");
    previous = frame.timeMs;
    let present = false;
    for (const [key, count] of [["body",33],["leftHand",21],["rightHand",21],["face",null]]) {
      if (frame[key] !== undefined) { checkPoints(frame[key], count, key); present ||= frame[key].length > 0; }
    }
    if (!present) throw new Error("Each frame needs landmarks.");
  }
  return sequence;
}

export class LightBox {
  constructor(canvas, { columns=128, rows=96, onLabel=()=>{}, reducedMotion=false }={}) {
    this.canvas=canvas; this.context=canvas.getContext("2d");
    this.columns=columns; this.rows=rows; this.onLabel=onLabel; this.reducedMotion=reducedMotion;
    this.canvas.width=columns*4; this.canvas.height=rows*4;
    this.canvas.setAttribute("role","img"); this.canvas.setAttribute("aria-label","Sign pose light display; no sequence loaded");
    this.running=0; this.frameIndex=0; this.clear();
  }
  clear() { this.context.fillStyle="#101b28"; this.context.fillRect(0,0,this.canvas.width,this.canvas.height); }
  stop() { (this.animationHost??globalThis).cancelAnimationFrame(this.running); this.running=0; }
  pause() { this.stop(); }
  setReducedMotion(value) { this.reducedMotion=Boolean(value); if (value) this.pause(); }
  draw(frame) {
    const active=new Set();
    const point=p=>[Math.round(p[0]*(this.columns-1)),Math.round(p[1]*(this.rows-1))];
    const light=(x,y)=>active.add(y*this.columns+x);
    const line=(a,b)=>{
      let [x,y]=point(a); const [tx,ty]=point(b);
      const dx=Math.abs(tx-x), sx=x<tx?1:-1, dy=-Math.abs(ty-y), sy=y<ty?1:-1; let error=dx+dy;
      for (;;) { light(x,y); if (x===tx&&y===ty) break; const e=2*error; if(e>=dy){error+=dy;x+=sx;} if(e<=dx){error+=dx;y+=sy;} }
    };
    for (const key of ["body","leftHand","rightHand","face"]) {
      const points=frame[key]; if (!points) continue;
      const visible=p=>p&&(p.length<4||p[3]>.3);
      for (const p of points) if(visible(p))light(...point(p));
      const links=key==="body"?BODY_LINKS:key.endsWith("Hand")?HAND_LINKS:[];
      for (const [a,b] of links) if (visible(points[a])&&visible(points[b])) line(points[a],points[b]);
    }
    this.clear(); this.context.fillStyle="#82e8b7";
    for (const value of active) { const x=value%this.columns,y=Math.floor(value/this.columns); this.context.fillRect(x*4,y*4,3,3); }
  }
  load(sequence) {
    validateSequence(sequence); this.stop(); this.sequence=sequence; this.frameIndex=0; this.draw(sequence.frames[0]);
    this.canvas.setAttribute("aria-label",`Pose display: ${sequence.gloss}`); this.onLabel(sequence.gloss);
  }
  step() { if(this.sequence){this.pause(); this.frameIndex=Math.min(this.frameIndex+1,this.sequence.frames.length-1); this.draw(this.sequence.frames[this.frameIndex]);} }
  play({speed=1}={}) {
    if(!this.sequence) throw new Error("Load a pose sequence first.");
    if(!Number.isFinite(speed)||speed<0.25||speed>2) throw new Error("Speed must be between 0.25 and 2.");
    this.stop(); if(this.reducedMotion) return;
    const host=this.canvas.ownerDocument?.defaultView??globalThis;this.animationHost=host;
    const frames=this.sequence.frames, start=host.performance.now()-frames[this.frameIndex].timeMs/speed;
    let drawnFrame = this.frameIndex;
    const tick=now=>{
      const time=(now-start)*speed;
      while(this.frameIndex+1<frames.length&&frames[this.frameIndex+1].timeMs<=time) this.frameIndex++;
      if (drawnFrame !== this.frameIndex) {this.draw(frames[this.frameIndex]); drawnFrame = this.frameIndex;}
      if(this.frameIndex+1<frames.length) this.running=host.requestAnimationFrame(tick); else this.running=0;
    };
    this.running=host.requestAnimationFrame(tick);
  }
}

export class ReviewedPhraseBook {
  constructor(data) {
    if (!data || typeof data.language!=="string" || !data.language || typeof data.reviewer!=="string" || !data.reviewer.trim() || typeof data.source!=="string" || !data.source || !Array.isArray(data.phrases) || data.phrases.length>10000) throw new Error("Phrase books require language, reviewer, source, and phrases.");
    this.language=data.language; this.source=data.source; this.reviewer=data.reviewer; this.phrases=new Map();
    for(const entry of data.phrases) {
      if(typeof entry.text!=="string"||!entry.text.trim()) throw new Error("Invalid reviewed phrase.");
      const key=this.normalize(entry.text); if(this.phrases.has(key)) throw new Error("Duplicate reviewed phrase.");
      this.phrases.set(key,validateSequence(entry.sequence));
    }
  }
  normalize(text) { return text.normalize("NFKC").trim().replace(/\s+/g," ").toLocaleLowerCase("en"); }
  lookup(text) { return this.phrases.get(this.normalize(text)) ?? null; }
}
