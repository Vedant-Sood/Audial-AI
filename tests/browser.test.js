import { test } from "node:test";
import assert from "node:assert/strict";
import { ReviewedPhraseBook, LightBox, validateSequence } from "../browser/light-box.js";
import { BrowserAudioCapture, encodeWav } from "../browser/capture.js";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { foreground, displayEmotion } from "../browser/emotion.js";

test("emotion indicators preserve a label and use readable foreground colors",()=>{
  const element={style:{},setAttribute(){}};
  displayEmotion(element,{tone:"happy"},{happy:"#000000",uncertain:"#ffffff"});
  assert.equal(element.textContent,"Happy");assert.equal(element.style.color,"#ffffff");
  displayEmotion(element,{tone:"unknown-model-label"},{happy:"#000000",uncertain:"#ffffff"});
  assert.equal(element.textContent,"Uncertain");assert.equal(element.style.color,"#000000");
  assert.throws(()=>foreground("url(remote)"));
});

const pose={gloss:"renderer fixture (not a sign)",frames:[{timeMs:0,face:[[.2,.2]]},{timeMs:100,face:[[.4,.4]]}]};
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
