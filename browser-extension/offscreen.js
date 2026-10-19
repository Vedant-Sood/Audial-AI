// The generated extension includes the shared worklet and WAV helpers from browser/.
import { encodeWav } from "./capture.js";

let stream = null, context = null, input = null, node = null, mute = null;
let generation = 0, session = null, ending = false, flushComplete = null;
const deliveries = new Set();
async function background(type, data = {}) {
  const response = await chrome.runtime.sendMessage({target: "background", type, ...data});
  if (!response?.ok) throw new Error(response?.error || "The local audio bridge disconnected.");
  return response.result;
}
function base64(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}
async function start(message) {
  if (stream) throw new Error("A tab is already being captured.");
  const current = ++generation;
  session = message.session; ending = false;
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: false, audio: {mandatory: {
      chromeMediaSource: "tab", chromeMediaSourceId: message.streamId,
    }}});
    context = new AudioContext();
    await context.audioWorklet.addModule("pcm-worklet.js");
    input = context.createMediaStreamSource(stream);
    // tabCapture mutes the original tab; route its audio back to the listener.
    input.connect(context.destination);
    node = new AudioWorkletNode(context, "accessibilityai-pcm");
    mute = context.createGain(); mute.gain.value = 0;
    input.connect(node).connect(mute).connect(context.destination);
    node.port.onmessage = event => {
      if (current !== generation) return;
      if (event.data.type === "flushed") {flushComplete?.(); return;}
      if (deliveries.size >= 2) {
        background("capture-error", {error: "The desktop cannot keep up with tab audio. Capture stopped to prevent an unbounded audio queue."}).catch(() => {});
        return;
      }
      const {samples, sampleRate, startSample} = event.data;
      const operation = (async () => {
        const wav = new Uint8Array(await encodeWav(samples, sampleRate).arrayBuffer());
        return background("audio", {session_id: session.session_id, pcm: base64(wav.subarray(44)),
          sample_rate: sampleRate, start_seconds: startSample / sampleRate});
      })().catch(error => { background("capture-error", {error: error.message}).catch(() => {}); });
      deliveries.add(operation); operation.finally(() => deliveries.delete(operation));
    };
    for (const track of stream.getTracks()) track.addEventListener("ended", () => {
      if (!ending) background("capture-ended").catch(() => {});
    }, {once: true});
    await context.resume();
    location.hash = "capturing";
  } catch (error) {await stop(false); throw error;}
}
async function stop(flush = true) {
  ending = true;
  if (flush && node && context?.state !== "closed") {
    input?.disconnect();
    await Promise.allSettled([...deliveries]);
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 2000);
      flushComplete = () => {clearTimeout(timer); flushComplete = null; resolve();};
      node.port.postMessage({type: "flush"});
    });
    await Promise.allSettled([...deliveries]);
  }
  ++generation;
  if (node) {node.port.onmessage = null; node.disconnect();}
  input?.disconnect(); mute?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  if (context && context.state !== "closed") await context.close();
  stream = context = input = node = mute = session = null;
  location.hash = "";
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message.target !== "offscreen" || sender.id !== chrome.runtime.id) return;
  const operation = message.type === "start" ? start(message) : message.type === "stop" ? stop(message.flush) : Promise.reject(new Error("Unknown capture action"));
  operation.then(() => reply({ok: true}), error => reply({ok: false, error: error.message}));
  return true;
});
