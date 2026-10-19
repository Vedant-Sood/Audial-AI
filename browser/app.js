import { LightBox } from "./light-box.js";
import { BrowserAudioCapture, openFloatingPanel } from "./capture.js";
import { displayEmotion } from "./emotion.js";
import { ISLPlayback } from "./isl-playback.js";
import { TranscriptView } from "./transcript.js";
import { BrowserNotices } from "./notifications.js";

const elements=new Map([...document.querySelectorAll("[id]")].map(element=>[element.id,element]));
const $=id=>elements.get(id);
const notices = new BrowserNotices($("error"), $("notification-history"));
const showError = (text, severity = "error") => notices.publish(text, severity);
const transcript = new TranscriptView($("transcript"));
const lights=new LightBox($("lights"),{reducedMotion:matchMedia("(prefers-reduced-motion: reduce)").matches,onLabel:label=>{$("sign-status").textContent=label;}});
$("reduced-motion").checked=lights.reducedMotion;
let active=false,starting=false,stopping=false,paused=false,sending=false,cursor=0,generation=0,sessionId=null;
let extensionActive = false;
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
let signGeneration=0,signLookups=Promise.resolve();
let manualDisplay=false;
const video = $("sign-video");
function clearSignView() {
  lights.stop(); lights.clear(); lights.sequence = null;
  video.pause(); video.hidden = true; $("lights").hidden = false;
  $("sign-text").hidden = true; $("sign-source").replaceChildren();
}
const signPlayback = new ISLPlayback({
  reducedMotion: lights.reducedMotion,
  show: step => {
    clearSignView();
    $("sign-status").textContent = step.kind === "text" ? "Text · no loaded ISL sign" : "ISL · " + step.gloss;
    if (step.kind === "text") {
      $("lights").hidden = true; $("sign-text").hidden = false; $("sign-text").textContent = step.text;
    } else {
      const link = document.createElement("a"); link.textContent = "Source · " + step.license;
      // Metadata is display information, not executable content.
      const source = new URL(step.source);
      if (["https:", "http:"].includes(source.protocol)) {link.href = source.href; link.target = "_blank"; link.rel = "noopener noreferrer";}
      $("sign-source").append(link);
      if (step.kind === "pose") lights.load(step.sequence);
      else {$("lights").hidden = true; video.hidden = false; video.src = step.url; video.currentTime = 0;}
    }
  },
  start: (step, speed) => {
    if (step.kind === "pose") lights.play({speed});
    else if (step.kind === "video") {video.playbackRate = speed; video.play().catch(error => showError("ISL video: " + error.message));}
  },
  pause: () => {lights.pause(); video.pause();},
  remaining: step => step.kind === "pose"
    ? step.sequence.frames.at(-1).timeMs - step.sequence.frames[lights.frameIndex].timeMs + 300
    : step.kind === "text" ? Math.max(1200, Math.min(4500, step.text.length * 65)) : null,
  advanceFrame: step => {
    if (step.kind === "pose") {
      if (lights.frameIndex === step.sequence.frames.length - 1) return true;
      lights.step(); return false;
    }
    if (Number.isFinite(video.duration) && video.currentTime >= video.duration - .05) return true;
    video.currentTime += 1 / (step.fps || 15); return false;
  },
  idle: () => {clearSignView(); $("sign-status").textContent = "Indian Sign Language · waiting for the next input.";},
});
video.addEventListener("ended", () => {if (signPlayback.current?.kind === "video") signPlayback.next(!signPlayback.paused);});
video.addEventListener("error", () => {
  if (signPlayback.current?.kind !== "video") return;
  const original = signPlayback.current.text, wasPaused = signPlayback.paused;
  signPlayback.current = {kind: "text", text: original, from_captions: signPlayback.current.from_captions};
  signPlayback.show(signPlayback.current); if (!wasPaused) signPlayback.play();
  showError("This ISL clip could not play. Its original text remains visible.");
});
async function request(path,data){
  const response=await fetch(path,{method:data===undefined?"GET":"POST",headers:data===undefined?{}:{"Content-Type":"application/json"},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(8000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error??"The local request failed.");return result;
}
function setButtons(){
  $("share").disabled=active||starting||stopping||extensionActive;$("microphone").disabled=active||starting||stopping||extensionActive;$("stop").disabled=stopping||!(active||starting);$("pause-audio").disabled=!active||stopping;
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
    transcript.clear();$("capture-status").textContent="Listening to " + (capture.sourceLabel || "the audio you selected") + ". Loading local captions…";
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
  transcript.append(caption);
  if($("auto-sign").checked&&(!manualDisplay||active)){
    const current=signGeneration;
    signLookups=signLookups.then(()=>loadSigns(caption.text,true,current)).catch(error=>showError(error.message));
  }
}
function displayPlan(result, append = false) {
  $("unknown").textContent = result.steps.some(step => step.kind === "text")
    ? "Passages without a loaded sign are shown as text in the same order."
    : "Every passage matched the loaded ISL vocabulary.";
  if (result.vocabulary.warning) showError(result.vocabulary.warning);
  const unavailable = result.steps.find(step => step.reason);
  if (unavailable) showError(unavailable.reason);
  signPlayback.enqueue({...result, steps: result.steps.map(step => ({...step, from_captions: append}))}, {append});
}
async function loadSigns(text,append=false,current=signGeneration){
  if(!text.trim()||current!==signGeneration)return;
  const result=await request("/api/signs", {text});
  if(current!==signGeneration || (append && !$("auto-sign").checked))return;
  displayPlan(result, append);
}
let pollDelay = 300;
async function poll(){
  try{
    const current=generation,result=await request("/api/events?after="+cursor);
    if(current!==generation){setTimeout(poll,300);return;}
    cursor=result.cursor;
    pollDelay = 300;
    if(result.gap)showError("Some display updates were missed. Export the complete transcript to recover all completed captions.");
    for(const event of result.events){
      const data=event.data;
      if(event.kind==="caption")appendCaption(data);
      else if(event.kind==="partial")$("partial").textContent=data?"Live draft: "+data:"";
      else if(event.kind==="prosody"){
        $("level").textContent=`${data.dbfs.toFixed(1)} dBFS`;$("pitch").textContent=data.f0_hz===null?"Unvoiced":`${Math.round(data.f0_hz)} Hz`;
        if (Object.hasOwn(data, "emotion")) lastEmotion = data.emotion;
        if (!lastEmotion) $("tone").textContent = "Off";
        applyEmotionColors();
      }else if(event.kind==="emotion"){
        lastEmotion = data.estimate;
        if (lastEmotion) applyEmotionColors();
        else {$("tone").textContent = "Off"; $("tone").style.background = "transparent"; $("tone").style.color = "";}
      }else if(event.kind==="status"){
        $("capture-status").textContent=data;
        if(data==="Idle"&&active)await stop({flush:false});
      }else if(event.kind==="warning"||event.kind==="error")showError(data,event.kind);
      else if(event.kind==="isl_settings") {
        $("auto-sign").checked = data.auto_sign;
        if (!data.auto_sign) signPlayback.stopCaptions();
      }else if(event.kind==="isl_vocabulary") {
        signGeneration++; signPlayback.stop(); $("unknown").textContent = `ISL vocabulary updated: ${data.entries} loaded signs.`;
      }
    }
  }catch(error){
    showError("Local companion unavailable: "+error.message);
    pollDelay = Math.min(5000, pollDelay * 2);
    if (active || starting) await stop({flush:false});
  }
  setTimeout(poll,pollDelay);
}
let tabListSignature = "";
async function refreshBrowserTabs() {
  try {
    const [result, status] = await Promise.all([request("/api/tabs"), request("/api/status")]);
    $("model-status").textContent = `${status.asr_model} ${status.asr_installed?"ready offline":"setup incomplete"} · speech ${status.language||"auto"} · ISL: ${status.vocabulary.entries} loaded signs`;
    extensionActive = Boolean(result.capture);
    const profiles = result.profiles.filter(profile => profile.connected);
    const signature = JSON.stringify(profiles);
    if (signature !== tabListSignature) {
      tabListSignature = signature;
      const selected = $("browser-tabs").value;
      $("browser-tabs").replaceChildren();
      for (const profile of profiles) for (const tab of profile.tabs) {
        const option = document.createElement("option");
        option.value = JSON.stringify([profile.id, tab.id]); option.disabled = !tab.supported;
        option.textContent = `${profile.browser} · Window ${tab.window_id} · ${tab.title}${tab.audible ? " · audio" : ""}${tab.discarded ? " · suspended" : ""}`;
        option.title = tab.reason; $("browser-tabs").append(option);
      }
      if ([...$("browser-tabs").options].some(option => option.value === selected)) $("browser-tabs").value = selected;
    }
    $("tabs-status").textContent = result.capture ? "LIVE · " + result.capture.title + ". Use its browser extension to switch or stop capture."
      : profiles.length ? "Real tabs from connected extensions. Open a tab, then invoke Audial-AI in its toolbar to grant capture access."
      : "Connect the Audial-AI extension in Chrome or Edge to discover tabs. Manual Share tab audio remains available through the browser's source picker.";
    $("focus-browser-tab").disabled = !$("browser-tabs").value;
    setButtons();
  } catch (error) {$("tabs-status").textContent = "Browser discovery disconnected. Start the desktop companion and reconnect the extension.";}
  setTimeout(refreshBrowserTabs, 3000);
}
$("focus-browser-tab").addEventListener("click", async () => {
  try {
    const [profile, tab_id] = JSON.parse($("browser-tabs").value);
    const result = await request("/api/browser-command", {profile, tab_id});
    $("tabs-status").textContent = result.message;
  } catch (error) {showError(error.message);}
});
refreshBrowserTabs();
$("share").addEventListener("click",()=>start("shared"));$("microphone").addEventListener("click",()=>start("microphone"));
$("stop").addEventListener("click",()=>stop());
$("pause-audio").addEventListener("click",async()=>{try{await request("/api/pause",{paused:!paused,session_id:sessionId});paused=!paused;setButtons();}catch(error){showError(error.message);}});
$("float").disabled=!globalThis.documentPictureInPicture?.requestWindow;
$("float").addEventListener("click",async()=>{
  const wasPlaying=Boolean(signPlayback.current && !signPlayback.paused);signPlayback.pause();
  try{const pip=await openFloatingPanel($("panel"));if(wasPlaying)signPlayback.play();pip.addEventListener("pagehide",()=>{const resume=Boolean(signPlayback.current && !signPlayback.paused);signPlayback.pause();if(resume)signPlayback.play();},{once:true});}
  catch(error){showError(error.message);}
});
$("display-phrase").addEventListener("click",()=>{manualDisplay=true;$("caption").textContent=$("phrase").value;signGeneration++;loadSigns($("phrase").value).catch(error=>showError(error.message));});
$("play").addEventListener("click",()=>{try{signPlayback.play();}catch(error){showError(error.message);}});
$("pause").addEventListener("click",()=>signPlayback.pause());
$("step").addEventListener("click",()=>signPlayback.step());
$("reset").addEventListener("click",()=>signPlayback.restart());
$("reduced-motion").addEventListener("change",event=>{lights.setReducedMotion(event.target.checked);signPlayback.setReducedMotion(event.target.checked);});
$("speed").addEventListener("input",event=>{$("speed-label").textContent=event.target.value+"×";signPlayback.setSpeed(Number(event.target.value));});
$("auto-sign").addEventListener("change",async event => {
  try {await request("/api/isl/settings", {language: "ISL", auto_sign: event.target.checked});
    if (!event.target.checked) signPlayback.stopCaptions();}
  catch(error) {showError(error.message);}
});
$("document-file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  const current = ++signGeneration;
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error("Choose a document smaller than 2 MB.");
    const response = await fetch("/api/document?filename=" + encodeURIComponent(file.name), {method: "POST", body: file});
    const result = await response.json(); if (!response.ok) throw new Error(result.error);
    if (current !== signGeneration) return;
    manualDisplay = true; $("phrase").value = result.text; $("caption").textContent = result.text;
    displayPlan(result); $("capture-status").textContent = "Displaying local document text in ISL.";
  } catch(error) {showError(error.message);}
  finally {event.target.value = "";}
});
addEventListener("pagehide",()=>{const ownedSession=active?sessionId:null;active=false;starting=false;generation++;capture.stop().catch(()=>{});if(ownedSession)navigator.sendBeacon("/api/stop",JSON.stringify({session_id:ownedSession}));});
request("/api/status").then(status=>{cursor=status.cursor??0;$("auto-sign").checked=status.auto_sign;$("model-status").textContent=`${status.asr_model} ${status.asr_installed?"ready":"needs installation"} · speech ${status.language||"auto"} · ISL: ${status.vocabulary.entries} loaded signs`;poll();}).catch(error=>{showError(error.message);poll();});
const pageText=new URLSearchParams(location.hash.slice(1)).get("text");
if(pageText){
  manualDisplay=true;
  history.replaceState(null,"",location.pathname+location.search);
  $("phrase").value=pageText;$("caption").textContent=pageText;
  $("capture-status").textContent="Displaying selected page text.";
  loadSigns(pageText).catch(error=>showError(error.message));
}
