const $ = id => document.getElementById(id);
let state = null, current = null, pending = false;
async function background(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({target: "background", type, ...extra});
  if (!response?.ok) throw new Error(response?.error || "The extension could not complete this action.");
  return response.result;
}
function status(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("failure", error);
}
function buttons() {
  $("capture-current").disabled = pending || !current || !/^https?:\/\//.test(current.url || "");
  $("stop-capture").disabled = pending || !state?.capture;
  $("focus-tab").disabled = pending || !$("tabs").value;
}
async function refresh() {
  try {
    [current] = await chrome.tabs.query({active: true, currentWindow: true});
    $("current-title").textContent = current?.title || "No active tab";
    state = await background("state");
    $("connection").textContent = state.error ? "Desktop disconnected" : "Connected to the local desktop";
    $("active-capture").textContent = state.capture ? "LIVE · " + state.capture.title : "No tab is being captured.";
    const selected = $("tabs").value;
    $("tabs").replaceChildren();
    for (const tab of state.tabs) {
      const option = document.createElement("option");
      option.value = String(tab.id);
      option.textContent = "Window " + tab.window_id + " · " + tab.title + (tab.audible ? " · audio" : "") + (tab.discarded ? " · suspended" : "");
      option.title = tab.reason;
      $("tabs").append(option);
    }
    if ([...$("tabs").options].some(option => option.value === selected)) $("tabs").value = selected;
    else if (current) $("tabs").value = String(current.id);
    if (state.error) status(state.error + " Start Audial-AI and open its browser companion. The Windows installer registers this bridge.", true);
    buttons();
  } catch (error) {status(error.message, true);}
}
$("capture-current").addEventListener("click", async () => {
  pending = true; buttons(); status("Preparing the tab you invoked from the toolbar…");
  try {await background("capture-current", {tabId: current.id}); status("Capturing this tab only. Close the popup; capture continues with the LIVE badge.");}
  catch (error) {status(error.message, true);}
  finally {pending = false; await refresh();}
});
$("stop-capture").addEventListener("click", async () => {
  pending = true; buttons(); status("Finishing the last audio packet and releasing the captured tab…");
  try {await background("stop"); status("Capture stopped. All tracks and audio resources have been released.");}
  catch (error) {status(error.message, true);}
  finally {pending = false; await refresh();}
});
$("focus-tab").addEventListener("click", async () => {
  try {
    await background("focus-tab", {tabId: Number($("tabs").value)});
    window.close();
  } catch (error) {status(error.message, true);}
});
$("refresh").addEventListener("click", refresh);
$("translate").addEventListener("click", async () => {
  pending = true; buttons();
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.id) throw new Error("Choose a page first.");
    const [injected] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => {
      const selected = globalThis.getSelection()?.toString().trim();
      return selected || document.querySelector("main")?.innerText || document.body?.innerText || "";
    }});
    const text = injected?.result?.trim();
    if (!text) throw new Error("Select some readable text, then try again.");
    if (Array.from(text).length > 20000) throw new Error("Select an extract up to 20,000 characters.");
    const port = Number($("port").value);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Use a valid local companion port.");
    const url = state?.companionUrl || "http://127.0.0.1:" + port;
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1") throw new Error("Use the local companion.");
    await chrome.tabs.create({url: url + "/#text=" + encodeURIComponent(text)});
    window.close();
  } catch (error) {status(error.message + " Restricted pages can be copied into the desktop text input instead.", true);}
  finally {pending = false; buttons();}
});
$("open-companion").addEventListener("click", async () => {
  if (state?.companionUrl) await chrome.tabs.create({url: state.companionUrl});
  else status("Start Audial-AI and choose Open browser companion to connect.", true);
});
refresh();
