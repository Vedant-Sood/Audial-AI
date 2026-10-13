class PCMCollector extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer=new Float32Array(Math.round(sampleRate*2)); this.offset=0; this.sequence=0;
    this.port.onmessage=event=>{if(event.data?.type==="flush"){this.send();this.port.postMessage({type:"flushed"});}};
  }
  send() {
    if(!this.offset)return;
    const samples=this.buffer.slice(0,this.offset);
    this.port.postMessage({samples,sampleRate,startSample:this.sequence},[samples.buffer]);
    this.sequence+=this.offset;this.offset=0;
  }
  process(inputs) {
    const channels=inputs[0]; if (!channels?.length || !channels[0].length) return true;
    for(let frame=0;frame<channels[0].length;frame++) {
      let value=0; for(const channel of channels) value+=channel[frame]??0;
      this.buffer[this.offset++]=value/channels.length;
      if(this.offset===this.buffer.length)this.send();
    }
    return true;
  }
}
registerProcessor("accessibilityai-pcm",PCMCollector);
