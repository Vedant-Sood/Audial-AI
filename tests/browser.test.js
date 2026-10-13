import { test } from "node:test";
import assert from "node:assert/strict";
import { ReviewedPhraseBook, LightBox, validateSequence } from "../browser/light-box.js";
import { BrowserAudioCapture, encodeWav } from "../browser/capture.js";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { foreground, displayEmotion } from "../browser/emotion.js";
import { expandISLPlan, ISLPlayback } from "../browser/isl-playback.js";

test("emotion indicators preserve a label and use readable foreground colors",()=>{
  const element={style:{},setAttribute(){}};
  displayEmotion(element,{tone:"happy"},{happy:"#000000",uncertain:"#ffffff"});
  assert.equal(element.textContent,"Happy");assert.equal(element.style.color,"#ffffff");
  displayEmotion(element,{tone:"unknown-model-label"},{happy:"#000000",uncertain:"#ffffff"});
  assert.equal(element.textContent,"Uncertain");assert.equal(element.style.color,"#000000");
  assert.throws(()=>foreground("url(remote)"));
});

const pose={gloss:"renderer fixture (not a sign)",frames:[{timeMs:0,face:[[.2,.2]]},{timeMs:100,face:[[.4,.4]]}]};

function playbackFixture(reducedMotion = false) {
  const shown=[], timers=new Map();let counter=0;
  const playback=new ISLPlayback({show:step=>shown.push(step.text),start:()=>{},pause:()=>{},advanceFrame:()=>true,remaining:()=>100,
    setTimer:fn=>{timers.set(++counter,fn);return counter;},clearTimer:id=>timers.delete(id),reducedMotion});
  return {playback, shown, timers, tick:()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn();}};
}
const mixedPlan={language:"ISL",sequences:[pose],steps:[{kind:"text",text:"unknown first"},{kind:"pose",text:"known middle",sequence_index:0},{kind:"text",text:"unknown last"}]};
test("default playback timers keep the browser global receiver",()=>{
  const savedSet=globalThis.setTimeout,savedClear=globalThis.clearTimeout;
  let scheduled=0,cleared=0;
  globalThis.setTimeout=function(){assert.equal(this,globalThis);scheduled++;return 1;};
  globalThis.clearTimeout=function(){assert.equal(this,globalThis);cleared++;};
  try {
    const playback=new ISLPlayback({show:()=>{},start:()=>{},pause:()=>{},advanceFrame:()=>true,remaining:()=>100});
    playback.enqueue(mixedPlan);playback.pause();
    assert.equal(scheduled,1);assert.equal(cleared,1);
  }finally{globalThis.setTimeout=savedSet;globalThis.clearTimeout=savedClear;}
});
test("ISL playback preserves text before and after signs and rejects other sign languages",()=>{
  const {playback,shown,tick}=playbackFixture();playback.enqueue(mixedPlan);tick();tick();
  assert.deepEqual(shown,["unknown first","known middle","unknown last"]);
  assert.throws(()=>expandISLPlan({...mixedPlan,language:"ASL"}),/Indian Sign Language/);
});
test("long ISL plans keep every step and encode repeated poses once",()=>{
  const {playback,shown}=playbackFixture(true);
  playback.enqueue({language:"ISL",sequences:[pose],steps:Array.from({length:150},(_,i)=>({kind:"pose",text:String(i),sequence_index:0}))});
  assert.equal(playback.queue.length,149);
  for(let i=0;i<150;i++)playback.step();
  assert.equal(shown.length,150);assert.equal(shown.at(-1),"149");assert.equal(playback.current,null);
});
test("turning off automatic captions preserves explicit text and document playback",()=>{
  const {playback,shown}=playbackFixture(true);playback.enqueue(mixedPlan);
  playback.enqueue({language:"ISL",sequences:[],steps:[{kind:"text",text:"automatic caption",from_captions:true}]},{append:true});
  playback.stopCaptions();playback.step();playback.step();playback.step();
  assert.deepEqual(shown,["unknown first","known middle","unknown last"]);
  assert.equal(playback.current,null);
});
test("reduced motion and pause stop text timers without skipping newly appended input",()=>{
  const {playback,shown,timers,tick}=playbackFixture();playback.enqueue(mixedPlan);
  playback.pause();assert.equal(timers.size,0);
  playback.enqueue({language:"ISL",sequences:[],steps:[{kind:"text",text:"later caption"}]},{append:true});
  assert.deepEqual(shown,["unknown first"]);playback.play();tick();
  playback.setReducedMotion(true);assert.equal(timers.size,0);playback.step();playback.step();
  assert.deepEqual(shown,["unknown first","known middle","unknown last","later caption"]);
});
test("ISL video sources must reference validated local vocabulary media",()=>{
  const valid={language:"ISL",sequences:[],steps:[{kind:"video",text:"Thank you",url:"/api/sign-media/"+"a".repeat(64)}]};
  assert.equal(expandISLPlan(valid)[0].kind,"video");
  assert.throws(()=>expandISLPlan({...valid,steps:[{...valid.steps[0],url:"https://unrelated.example/video"}]}));
});
test("the audio worklet flushes the final short packet with its capture timestamp",()=>{
  let Collector;const sent=[];
  const environment={sampleRate:16000,Float32Array,AudioWorkletProcessor:class{constructor(){this.port={postMessage:message=>sent.push(message)};}},registerProcessor:(_,value)=>{Collector=value;}};
  runInNewContext(readFileSync(new URL("../browser/pcm-worklet.js",import.meta.url),"utf8"),environment);
  const collector=new Collector();collector.process([[new Float32Array(320).fill(.25)]]);
  assert.equal(sent.length,0);collector.port.onmessage({data:{type:"flush"}});
  assert.equal(sent[0].samples.length,320);assert.equal(sent[0].startSample,0);assert.equal(sent[1].type,"flushed");
  collector.process([[new Float32Array(160).fill(.5)]]);collector.port.onmessage({data:{type:"flush"}});
  assert.equal(sent[2].startSample,320);assert.equal(sent[2].samples.length,160);
});
test("reviewed vocabulary never guesses an unknown phrase",()=>{
  const book=new ReviewedPhraseBook({language:"ase",reviewer:"Test fixture only",source:"Test",phrases:[{text:"A reviewed phrase",sequence:pose}]});
  assert.equal(book.lookup("  a   reviewed PHRASE "),pose);
  assert.equal(book.lookup("An unknown phrase"),null);
  assert.throws(()=>new ReviewedPhraseBook({language:"ase",source:"Test",phrases:[]}));
});
test("unsafe pose coordinates and unordered frames are rejected",()=>{
  assert.throws(()=>validateSequence({gloss:"x",frames:[{timeMs:0,face:[[Infinity,.4]]}]}));
  assert.throws(()=>validateSequence({gloss:"x",frames:[{timeMs:0,face:[[1.1,.4]]}]}));
  assert.throws(()=>validateSequence({gloss:"x",frames:[pose.frames[1],pose.frames[0]]}));
  assert.throws(()=>validateSequence({gloss:"x",frames:[{timeMs:0}]}));
});
test("WAV encoding writes actual PCM headers and clips samples",async()=>{
  const wav=encodeWav(new Float32Array([-2,0,2]),16000),data=new DataView(await wav.arrayBuffer());
  assert.equal(wav.type,"audio/wav");assert.equal(data.getUint32(24,true),16000);assert.equal(data.getUint32(40,true),6);
  assert.equal(data.getInt16(44,true),-32768);assert.equal(data.getInt16(46,true),0);assert.equal(data.getInt16(48,true),32767);
});
test("reduced motion keeps the pose static while frame stepping works",()=>{
  const fills=[],context={fillRect:(...args)=>fills.push(args)},canvas={getContext:()=>context,setAttribute:()=>{}};
  const originalCancel=globalThis.cancelAnimationFrame;globalThis.cancelAnimationFrame=()=>{};
  try{const box=new LightBox(canvas,{reducedMotion:true});box.load(pose);box.play();assert.equal(box.frameIndex,0);box.step();assert.equal(box.frameIndex,1);assert.ok(fills.length>2);}
  finally{globalThis.cancelAnimationFrame=originalCancel;}
});
test("missing shared audio releases the selected screen stream",async()=>{
  const navigatorDescriptor=Object.getOwnPropertyDescriptor(globalThis,"navigator"),secureDescriptor=Object.getOwnPropertyDescriptor(globalThis,"isSecureContext");
  let stopped=0,notified=0;const track={stop:()=>stopped++};
  Object.defineProperty(globalThis,"navigator",{configurable:true,value:{mediaDevices:{getDisplayMedia:async()=>({getAudioTracks:()=>[],getTracks:()=>[track]})}}});
  Object.defineProperty(globalThis,"isSecureContext",{configurable:true,value:true});
  try{const capture=new BrowserAudioCapture({onChunk:()=>{},onStop:()=>notified++});await assert.rejects(capture.start(),/No audio was shared/);assert.equal(stopped,1);assert.equal(notified,1);assert.equal(capture.stream,null);}
  finally{if(navigatorDescriptor)Object.defineProperty(globalThis,"navigator",navigatorDescriptor);else delete globalThis.navigator;if(secureDescriptor)Object.defineProperty(globalThis,"isSecureContext",secureDescriptor);else delete globalThis.isSecureContext;}
});
test("stopping during the source picker releases a stream that arrives late",async()=>{
  const navigatorDescriptor=Object.getOwnPropertyDescriptor(globalThis,"navigator"),secureDescriptor=Object.getOwnPropertyDescriptor(globalThis,"isSecureContext");
  let resolvePicker,stopped=0;const picked=new Promise(resolve=>{resolvePicker=resolve;});
  Object.defineProperty(globalThis,"navigator",{configurable:true,value:{mediaDevices:{getDisplayMedia:()=>picked}}});
  Object.defineProperty(globalThis,"isSecureContext",{configurable:true,value:true});
  try{const capture=new BrowserAudioCapture({onChunk:()=>{}});const starting=capture.start();await capture.stop();resolvePicker({getTracks:()=>[{stop:()=>stopped++}]});await starting;assert.equal(stopped,1);assert.equal(capture.stream,null);assert.equal(capture.pending,false);}
  finally{if(navigatorDescriptor)Object.defineProperty(globalThis,"navigator",navigatorDescriptor);else delete globalThis.navigator;if(secureDescriptor)Object.defineProperty(globalThis,"isSecureContext",secureDescriptor);else delete globalThis.isSecureContext;}
});
