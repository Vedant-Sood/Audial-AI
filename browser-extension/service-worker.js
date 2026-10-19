import { NativeBridgeClient } from "./bridge-client.js";
import { reconcileTabs } from "./tabs.js";

let profile, tabs = [], capture = null, busy = false, lastError = "", companionUrl = null;
let refreshTimer = 0, polling = false, offscreenCreation = null;
const native = new NativeBridgeClient(chrome.runtime, {onDisconnect: reason => {
  lastError = reason;
  if (capture) stopCapture(false).catch(() => {});
}});
const profileReady = chrome.storage.local.get("audialProfile").then(async stored => {
  profile = stored.audialProfile || crypto.randomUUID();
  if (!stored.audialProfile) await chrome.storage.local.set({audialProfile: profile});
});
async function call(type, values = {}) {
  await profileReady;
  const result = await native.call({type, profile, ...values});
  lastError = "";
  if (result.companion_url) companionUrl = result.companion_url;
  return result;
}
async function refreshTabs() {
  tabs = reconcileTabs(await chrome.tabs.query({}));
  await call("tabs", {tabs, browser: navigator.userAgent.includes("Edg/") ? "Microsoft Edge" : "Chrome / Chromium"});
  return tabs;
}
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refreshTabs().catch(error => {lastError = error.message;}), 150);
}
for (const event of [chrome.tabs.onCreated, chrome.tabs.onRemoved, chrome.tabs.onUpdated,
  chrome.tabs.onAttached, chrome.tabs.onDetached, chrome.tabs.onReplaced]) event.addListener(scheduleRefresh);
chrome.tabs.onRemoved.addListener(id => {if (capture?.tab_id === id) stopCapture(false).catch(() => {});});
chrome.tabCapture.onStatusChanged.addListener(info => {
  if (capture?.tab_id === info.tabId && ["stopped", "error"].includes(info.status)) stopCapture(false).catch(() => {});
});
async function ensureOffscreen() {
  if ((await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"]})).length) return;
  if (!offscreenCreation) offscreenCreation = chrome.offscreen.createDocument({
    url: "offscreen.html", reasons: ["USER_MEDIA"], justification: "Send explicitly selected tab audio to the local Audial-AI app."
  }).finally(() => {offscreenCreation = null;});
  await offscreenCreation;
}
async function setCapture(value) {
  capture = value;
  await chrome.storage.session.set({audialCapture: value});
  await chrome.action.setBadgeText({text: value ? "LIVE" : ""});
  await chrome.action.setBadgeBackgroundColor({color: "#b83c32"});
}
async function startCapture(tabId) {
  if (busy) throw new Error("A source switch is already in progress.");
  busy = true;
  let replacing = false;
  try {
    // Chrome enforces activeTab here. A webpage or remote command cannot grant it.
    const streamId = await chrome.tabCapture.getMediaStreamId({targetTabId: tabId});
    replacing = true;
    if (capture) await stopCapture();
    await refreshTabs();
    await ensureOffscreen();
    const owned = await call("start", {tab_id: tabId});
    await setCapture(owned);
    const response = await chrome.runtime.sendMessage({target: "offscreen", type: "start", streamId, session: owned});
    if (!response?.ok) throw new Error(response?.error || "The browser did not start tab audio.");
    return owned;
  } catch (error) {
    if (replacing) await stopCapture(false).catch(() => {});
    throw new Error(error.message + " Open the desired tab and click Audial-AI in its toolbar to grant capture access. Microphone capture is never substituted.");
  } finally { busy = false; }
}
let stopping = null;
function stopCapture(flush = true) {
  if (stopping) return stopping;
  stopping = (async () => {
    const owned = capture;
    const contexts = await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"]});
    if (contexts.length) {
      await chrome.runtime.sendMessage({target: "offscreen", type: "stop", flush}).catch(() => {});
      await chrome.offscreen.closeDocument().catch(() => {});
    }
    await setCapture(null);
    if (owned) {
      await call("stop", {session_id: owned.session_id});
      for (let attempt = 0; attempt < 50; attempt++) {
        if (!(await call("poll")).engine_running) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
  })().finally(() => {stopping = null;});
  return stopping;
}
async function dispatch(message) {
  switch (message.type) {
    case "state":
      try { await refreshTabs(); } catch (error) {lastError = error.message;}
      return {tabs, capture, busy, error: lastError, companionUrl};
    case "capture-current": return startCapture(message.tabId);
    case "stop": return stopCapture();
    case "focus-tab":
      await chrome.tabs.update(message.tabId, {active: true});
      await chrome.windows.update((await chrome.tabs.get(message.tabId)).windowId, {focused: true});
      return {focused: true};
    case "audio":
      if (!capture || message.session_id !== capture.session_id) throw new Error("Capture has stopped.");
      return call("audio", {session_id: capture.session_id, pcm: message.pcm,
        sample_rate: message.sample_rate, start_seconds: message.start_seconds});
    case "capture-ended": return stopCapture(false);
    case "capture-error":
      lastError = message.error;
      return stopCapture(false);
    default: throw new Error("Unsupported extension action.");
  }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message.target !== "background" || sender.id !== chrome.runtime.id) return;
  dispatch(message).then(result => reply({ok: true, result}), error => {
    lastError = error.message; reply({ok: false, error: error.message});
  });
  return true;
});
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const result = await call("poll");
    for (const command of result.commands || []) {
      if (command.type === "focus-tab") await dispatch({type: "focus-tab", tabId: command.tab_id});
    }
    if (capture && (!result.capture || result.capture.session_id !== capture.session_id)) {
      lastError = "The desktop session ended. Capture has stopped; start it again from this tab's toolbar.";
      await stopCapture(false);
    }
  } catch (error) {
    lastError = error.message;
    if (capture) await stopCapture(false).catch(() => {});
  } finally {polling = false;}
}
async function initialize() {
  await profileReady;
  const contexts = await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"]});
  const saved = await chrome.storage.session.get("audialCapture");
  if (contexts.length && saved.audialCapture) capture = saved.audialCapture;
  else await setCapture(null);
  await poll();
  scheduleRefresh();
}
initialize().catch(error => {lastError = error.message;});
setInterval(poll, 3000);
