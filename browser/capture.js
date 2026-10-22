export function encodeWav(samples, sampleRate) {
  if(!Number.isInteger(sampleRate)||sampleRate<8000||sampleRate>192000) throw new Error("Unsupported sample rate.");
  const result=new ArrayBuffer(44+samples.length*2),view=new DataView(result);
  const text=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));};
  text(0,"RIFF"); view.setUint32(4,36+samples.length*2,true); text(8,"WAVE"); text(12,"fmt "); view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true); view.setUint32(24,sampleRate,true); view.setUint32(28,sampleRate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true); text(36,"data"); view.setUint32(40,samples.length*2,true);
  for(let i=0;i<samples.length;i++){const s=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,s<0?s*32768:s*32767,true);}
  return new Blob([result],{type:"audio/wav"});
}

export class BrowserAudioCapture {
  constructor({onChunk,onSamples=null,microphone=()=>({}),onStop=()=>{},onError=()=>{},workletUrl=new URL("./pcm-worklet.js",import.meta.url).href}) {
    this.onChunk=onChunk; this.onSamples=onSamples; this.microphone=microphone; this.onStop=onStop; this.onError=onError; this.workletUrl=workletUrl; this.generation=0;this.deliveries=new Set();
  }
  async start(source="shared") {
    if(source!=="shared"&&source!=="microphone") throw new Error("Choose shared or microphone audio.");
    if(!globalThis.isSecureContext || !navigator.mediaDevices) throw new Error("Open on localhost or HTTPS to capture audio.");
    if(this.stream||this.pending) throw new Error("Audio capture is already active.");
    this.pending=true;this.ending=false; const generation=++this.generation;
    try {
      const stream=source==="microphone"?
        await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false,...this.microphone()},video:false}):
        await navigator.mediaDevices.getDisplayMedia({video:true,audio:true,systemAudio:"include",surfaceSwitching:"include"});
      if(generation!==this.generation) {stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      this.sourceLabel = stream.getVideoTracks?.()[0]?.label || stream.getAudioTracks()[0]?.label || (source === "microphone" ? "microphone" : "shared audio");
      if(!this.stream.getAudioTracks().length) throw new Error("No audio was shared. Choose a browser tab and enable Share tab audio, or use the microphone.");
      this.context=new AudioContext(); await this.context.audioWorklet.addModule(this.workletUrl);
      if(generation!==this.generation) return;
      this.input=this.context.createMediaStreamSource(new MediaStream(this.stream.getAudioTracks()));
      this.node=new AudioWorkletNode(this.context,"accessibilityai-pcm",{processorOptions:{tap:Boolean(this.onSamples)}});
      this.mute=this.context.createGain(); this.mute.gain.value=0;
      this.input.connect(this.node).connect(this.mute).connect(this.context.destination);
      this.node.port.onmessage=event=>{
        if(generation!==this.generation)return;
        if(event.data.type==="flushed"){this.flushComplete?.();return;}
        if(event.data.type==="tap"){try{this.onSamples?.(event.data.samples,event.data.sampleRate);}catch(error){this.onError(error);}return;}
        const delivery=Promise.resolve(this.onChunk({...event.data,wav:encodeWav(event.data.samples,event.data.sampleRate)})).catch(this.onError);
        this.deliveries.add(delivery);delivery.finally(()=>this.deliveries.delete(delivery));
      };
      for(const track of this.stream.getTracks())track.addEventListener("ended",()=>{
        if(generation===this.generation&&!this.ending){this.ending=true;this.flush().catch(this.onError).finally(()=>{if(generation===this.generation)this.stop();});}
      },{once:true});
      await this.context.resume();
    } catch(error) { if(generation===this.generation)await this.stop(); throw error; }
    finally { if(generation===this.generation)this.pending=false; }
  }
  async flush() {
    if(!this.node||!this.context||this.context.state==="closed")return;
    this.input?.disconnect();
    await Promise.allSettled([...this.deliveries]);
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{this.flushComplete=null;reject(new Error("The last audio packet could not be flushed."));},2000);
      this.flushComplete=()=>{clearTimeout(timeout);this.flushComplete=null;resolve();};
      this.node.port.postMessage({type:"flush"});
    });
    await Promise.allSettled([...this.deliveries]);
  }
  async stop() {
    ++this.generation; this.pending=false;
    const stream=this.stream, context=this.context;
    this.stream=null; this.context=null;
    this.flushComplete?.();this.flushComplete=null;
    if(this.node){this.node.port.onmessage=null;this.node.disconnect();}
    this.input?.disconnect(); this.mute?.disconnect();
    stream?.getTracks().forEach(track=>track.stop());
    if(context&&context.state!=="closed")await context.close();
    this.onStop();
  }
}

export async function openFloatingPanel(panel,{width=520,height=560}={}) {
  if(!globalThis.documentPictureInPicture?.requestWindow) throw new Error("This browser does not support a floating panel. Keep this page beside your meeting or use a supporting desktop Chromium browser.");
  const originDocument=panel.ownerDocument, anchor=originDocument.createComment("floating-panel-home"), parent=panel.parentNode;
  if(!parent)throw new Error("The panel must be attached to the page.");
  const pip=await documentPictureInPicture.requestWindow({width,height});
  parent.insertBefore(anchor,panel);
  for(const stylesheet of originDocument.querySelectorAll('link[rel="stylesheet"],style')){
    const copy=stylesheet.cloneNode(true);if(stylesheet.tagName==="LINK")copy.href=stylesheet.href;pip.document.head.append(copy);
  }
  pip.document.title="AccessibilityAI captions and signs";
  pip.document.body.classList.add("floating-view");
  pip.document.body.append(panel);
  pip.addEventListener("pagehide",()=>{if(anchor.parentNode){anchor.parentNode.insertBefore(panel,anchor);anchor.remove();}},{once:true});
  return pip;
}
