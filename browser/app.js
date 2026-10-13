import { LightBox } from "./light-box.js";
import { BrowserAudioCapture, openFloatingPanel } from "./capture.js";
import { displayEmotion } from "./emotion.js";

const elements=new Map([...document.querySelectorAll("[id]")].map(element=>[element.id,element]));
const $=id=>elements.get(id), showError=text=>{$("error").textContent=text;};
const lights=new LightBox($("lights"),{reducedMotion:matchMedia("(prefers-reduced-motion: reduce)").matches,onLabel:label=>{$("sign-status").textContent=label;}});
$("reduced-motion").checked=lights.reducedMotion;
let active=false,starting=false,stopping=false,paused=false,sending=false,cursor=0,generation=0,sessionId=null;
let emotionColors = null, lastEmotion = null, defaultColors = null;

function applyEmotionColors() {
  if (emotionColors && lastEmotion) displayEmotion($("tone"), lastEmotion, emotionColors);
}

async function loadPalette() {
  const data = await request("/api/palette");
  emotionColors = data.colors; defaultColors = data.defaults;
  const container = $("emotion-colors"); container.replaceChildren();
  for (const [name, color] of Object.entries(emotionColors)) {
    const label = document.createElement("label"), input = document.createElement("input");
    input.type = "color"; input.value = color; input.setAttribute("aria-label", "Color for " + name);
    label.append(input, document.createTextNode(" " + name)); container.append(label);
    input.addEventListener("input", () => { emotionColors[name] = input.value; applyEmotionColors(); });
  }
  applyEmotionColors();
}

$("save-emotion-colors").addEventListener("click", async () => {
  try { await request("/api/palette", {colors: emotionColors}); $("palette-status").textContent = "Emotion colors saved."; }
  catch(error) { showError(error.message); }
});
$("reset-emotion-colors").addEventListener("click", async () => {
  try { await request("/api/palette", {colors: defaultColors}); await loadPalette(); $("palette-status").textContent = "Default emotion colors saved."; }
  catch(error) { showError(error.message); }
});
loadPalette().catch(error => showError(error.message));
let signQueue=[],signTimer=null,signGeneration=0,signLookups=Promise.resolve();
let manualDisplay=false;
async function request(path,data){
  const response=await fetch(path,{method:data===undefined?"GET":"POST",headers:data===undefined?{}:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error??"The local request failed.");return result;
}
function setButtons(){
  $("share").disabled=active||starting||stopping;$("microphone").disabled=active||starting||stopping;$("stop").disabled=stopping||!(active||starting);$("pause-audio").disabled=!active||stopping;
  $("pause-audio").textContent=paused?"Resume audio":"Pause audio";
}
const capture=new BrowserAudioCapture({onChunk:async chunk=>{
  if(!active)return;
  if(sending){showError("An audio packet was skipped because the connection is slow. Caption timestamps preserve the gap.");return;}
  const current=generation;sending=true;
  try{
    const response=await fetch("/api/audio",{method:"POST",headers:{"Content-Type":"audio/wav","X-Audio-Start-Seconds":String(chunk.startSample/chunk.sampleRate),"X-Session-ID":sessionId},body:chunk.wav,signal:AbortSignal.timeout(15000)});
    if(!response.ok){const result=await response.json();throw new Error(result.error??"Audio upload failed.");}
  }catch(error){if(current===generation){showError(error.message);await stop({flush:false});}}finally{if(current===generation)sending=false;}
},onStop:()=>{
  if(active&&!stopping)stop().catch(error=>showError(error.message));
},onError:error=>showError(error.message)});
async function start(source){
  if(active||starting)return;
  showError("");starting=true;const attempt=++generation;setButtons();
  try{
    const status=await request("/api/status");
    if(attempt!==generation)return;
    if(!status.asr_installed)throw new Error(`Install ${status.asr_model} on the desktop Models page or run setup before starting captions.`);
    if(status.running)throw new Error("Stop the current audio session in the desktop app before starting here.");
    await capture.start(source);
    if(attempt!==generation)return;
    const result=await request("/api/start",{mode:"combined"});
    if(attempt!==generation){await request("/api/stop",{session_id:result.session_id});return;}
    active=true;starting=false;paused=false;sending=false;manualDisplay=false;sessionId=result.session_id;cursor=result.cursor;
    $("transcript").replaceChildren();$("capture-status").textContent="Listening to the audio you selected. Loading local captions…";
    setButtons();
  }catch(error){if(attempt===generation){starting=false;await capture.stop();setButtons();showError(error.message);}}
}
async function stop({flush=true}={}){
  if(stopping)return;
  stopping=true;$("stop").disabled=true;$("capture-status").textContent="Finishing the last audio packet…";
  if(active&&flush)await capture.flush().catch(error=>showError(error.message));
  const ownedSession=active?sessionId:null;active=false;starting=false;paused=false;sending=false;generation++;setButtons();await capture.stop();
  if(ownedSession)await request("/api/stop",{session_id:ownedSession}).catch(error=>showError(error.message));
  stopping=false;setButtons();
  $("capture-status").textContent="Audio stopped. Finishing queued captions…";
}
function appendCaption(caption){
  if(!manualDisplay||active)$("caption").textContent=caption.text;
  const item=document.createElement("li"),header=document.createElement("span"),text=document.createElement("p");
  header.className="hint";header.textContent=`${caption.speaker} · ${caption.start.toFixed(2)}–${caption.end.toFixed(2)}s${caption.overlap?" · overlapping voices":""}`;
  text.textContent=caption.text;item.append(header,text);$("transcript").append(item);if(!manualDisplay)item.scrollIntoView({block:"nearest"});
  if($("auto-sign").checked&&(!manualDisplay||active)){
    const current=signGeneration;
    signLookups=signLookups.then(()=>loadSigns(caption.text,true,current)).catch(error=>showError(error.message));
  }
}
function scheduleNext(){
  clearTimeout(signTimer);signTimer=null;
  if(lights.sequence&&!lights.reducedMotion){
    const frames=lights.sequence.frames;
    const remaining=frames.at(-1).timeMs-frames[lights.frameIndex].timeMs+300;
    signTimer=setTimeout(()=>playNext(),remaining/Number($("speed").value));
  }
}
function playNext(automatic=true){
  clearTimeout(signTimer);signTimer=null;
  if(!signQueue.length){lights.stop();lights.clear();lights.sequence=null;$("sign-status").textContent="Waiting for the next known ISL phrase.";lights.canvas.setAttribute("aria-label","Sign light display; no sequence active");return;}
  const sequence=signQueue.shift();lights.load(sequence);
  if(automatic){lights.play({speed:Number($("speed").value)});scheduleNext();}
}
async function loadSigns(text,append=false,current=signGeneration){
  if(!text.trim()||current!==signGeneration)return;
  const result=await request("/api/signs?text="+encodeURIComponent(text));
  if(current!==signGeneration)return;
  $("unknown").textContent=result.missing.length?"Words without a loaded sign: "+result.missing.join(", "):"All phrases found in the loaded vocabulary.";
  if(!append){clearTimeout(signTimer);signTimer=null;signQueue=[];lights.stop();lights.clear();lights.sequence=null;}
  const room=30-signQueue.length;signQueue.push(...result.sequences.slice(0,room));
  if(result.sequences.length>room)showError("The sign queue is full. All spoken words remain in the captions.");
  if(!lights.sequence)playNext();
  if(!result.sequences.length&&!append)$("sign-status").textContent="No known ISL sign for this text. The caption remains visible.";
}
async function poll(){
  try{
    const current=generation,result=await request("/api/events?after="+cursor);
    if(current!==generation){setTimeout(poll,300);return;}
    cursor=result.cursor;
    if(result.gap)showError("Some display updates were missed. Export the complete transcript to recover all completed captions.");
    for(const event of result.events){
      const data=event.data;
      if(event.kind==="caption")appendCaption(data);
      else if(event.kind==="partial")$("partial").textContent=data?"Live draft: "+data:"";
      else if(event.kind==="prosody"){
        $("level").textContent=`${data.dbfs.toFixed(1)} dBFS`;$("pitch").textContent=data.f0_hz===null?"Unvoiced":`${Math.round(data.f0_hz)} Hz`;
        lastEmotion = data.emotion ?? null;
        $("tone").textContent = lastEmotion ? lastEmotion.tone : "Off";
        applyEmotionColors();
      }else if(event.kind==="status"){
        $("capture-status").textContent=data;
        if(data==="Idle"&&active)await stop({flush:false});
      }else if(event.kind==="warning"||event.kind==="error")showError(data);
    }
  }catch(error){showError("Local companion unavailable: "+error.message);}
  setTimeout(poll,300);
}
$("share").addEventListener("click",()=>start("shared"));$("microphone").addEventListener("click",()=>start("microphone"));
$("stop").addEventListener("click",()=>stop());
$("pause-audio").addEventListener("click",async()=>{try{await request("/api/pause",{paused:!paused,session_id:sessionId});paused=!paused;setButtons();}catch(error){showError(error.message);}});
$("float").disabled=!globalThis.documentPictureInPicture?.requestWindow;
$("float").addEventListener("click",async()=>{
  const wasPlaying=Boolean(lights.running);lights.pause();
  try{const pip=await openFloatingPanel($("panel"));if(wasPlaying)lights.play({speed:Number($("speed").value)});pip.addEventListener("pagehide",()=>{const resume=Boolean(lights.running);lights.pause();if(resume)lights.play({speed:Number($("speed").value)});},{once:true});}
  catch(error){showError(error.message);}
});
$("display-phrase").addEventListener("click",()=>{manualDisplay=true;$("caption").textContent=$("phrase").value;signGeneration++;loadSigns($("phrase").value).catch(error=>showError(error.message));});
$("play").addEventListener("click",()=>{try{lights.play({speed:Number($("speed").value)});scheduleNext();}catch(error){showError(error.message);}});
$("pause").addEventListener("click",()=>{lights.pause();clearTimeout(signTimer);signTimer=null;});
$("step").addEventListener("click",()=>{clearTimeout(signTimer);signTimer=null;if(lights.sequence&&lights.frameIndex===lights.sequence.frames.length-1)playNext(false);else lights.step();});
$("reset").addEventListener("click",()=>{clearTimeout(signTimer);signTimer=null;if(lights.sequence)lights.load(lights.sequence);});
$("reduced-motion").addEventListener("change",event=>{lights.setReducedMotion(event.target.checked);clearTimeout(signTimer);signTimer=null;});
$("speed").addEventListener("input",event=>{$("speed-label").textContent=event.target.value+"×";lights.pause();clearTimeout(signTimer);signTimer=null;});
addEventListener("pagehide",()=>{const ownedSession=active?sessionId:null;active=false;starting=false;generation++;capture.stop().catch(()=>{});if(ownedSession)navigator.sendBeacon("/api/stop",JSON.stringify({session_id:ownedSession}));});
request("/api/status").then(status=>{cursor=status.cursor??0;$("model-status").textContent=`${status.asr_model} ${status.asr_installed?"ready":"needs installation"} · speech ${status.language||"auto"} · ISL vocabulary`;poll();}).catch(error=>{showError(error.message);poll();});
const pageText=new URLSearchParams(location.hash.slice(1)).get("text");
if(pageText){
  manualDisplay=true;
  history.replaceState(null,"",location.pathname+location.search);
  $("phrase").value=pageText.slice(0,2000);$("caption").textContent=pageText.slice(0,2000);
  $("capture-status").textContent="Displaying selected page text.";
  loadSigns(pageText.slice(0,2000)).catch(error=>showError(error.message));
}
