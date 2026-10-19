import test from "node:test";
import assert from "node:assert/strict";
import {describeTab, reconcileTabs} from "../browser-extension/tabs.js";
import {NativeBridgeClient} from "../browser-extension/bridge-client.js";

function fixture(options = {}) {
  const ports = [];
  const runtime = {connectNative(name) {
    assert.equal(name, "org.audialai.bridge");
    const listeners = {message: [], disconnect: []};
    const port = {sent: [], listeners, postMessage(value) {this.sent.push(value);},
      onMessage: {addListener(fn) {listeners.message.push(fn);}},
      onDisconnect: {addListener(fn) {listeners.disconnect.push(fn);}}};
    ports.push(port); return port;
  }};
  return {runtime, ports, client: new NativeBridgeClient(runtime, options)};
}
function reply(port, result) {
  for (const listener of port.listeners.message) listener(result);
}
function disconnect(port) {
  for (const listener of port.listeners.disconnect) listener();
}

test("real tab IDs reconcile across windows without stale duplicate entries", () => {
  const tabs = reconcileTabs([{id: 4, windowId: 1, title: "Old"},
    {id: 8, windowId: 2, url: "https://example.com/", title: "Second", audible: true},
    {id: 4, windowId: 1, url: "https://example.org/", title: "Reloaded"}, {title: "No ID"}]);
  assert.equal(tabs.length, 2);
  assert.equal(tabs[0].id, 8);
  assert.equal(tabs[1].title, "Reloaded");
  assert.equal(reconcileTabs(tabs.filter(tab => tab.id !== 8)).length, 1);
});
test("restricted and suspended pages explain their real capture prerequisite", () => {
  for (const url of ["chrome://settings/", "edge://extensions/", "file:///private.html",
    "https://chromewebstore.google.com/detail/x", "https://microsoftedge.microsoft.com/addons/detail/x"]) {
    assert.equal(describeTab({id: 1, url}).supported, false);
  }
  const suspended = describeTab({id: 2, url: "https://example.com", discarded: true});
  assert.equal(suspended.discarded, true);
  assert.match(suspended.reason, /suspended/);
  assert.equal(describeTab({id: 3, url: "http://127.0.0.1:8123/first"}).supported, true);
});
test("native messages correlate responses and propagate recoverable desktop errors", async () => {
  const {client, ports} = fixture();
  const first = client.call({type: "tabs"}), second = client.call({type: "start"});
  reply(ports[0], {id: 2, ok: false, error: "Finish model setup"});
  reply(ports[0], {id: 1, ok: true, result: {updated: true}});
  assert.deepEqual(await first, {updated: true});
  await assert.rejects(second, /Finish model setup/);
  assert.equal(client.pending.size, 0);
});
test("desktop disconnect rejects pending work and a new port ignores stale responses", async () => {
  const {client, ports} = fixture();
  const pending = client.call({type: "poll"});
  disconnect(ports[0]);
  await assert.rejects(pending, /disconnected/);
  const next = client.call({type: "poll"});
  reply(ports[0], {id: 2, ok: true, result: {stale: true}});
  disconnect(ports[0]);
  assert.equal(client.pending.size, 1);
  reply(ports[1], {id: 2, ok: true, result: {reconnected: true}});
  assert.deepEqual(await next, {reconnected: true});
  assert.equal(client.pending.size, 0);
});
test("backpressure bounds native requests and timeout releases all slots", async () => {
  const {client} = fixture({timeout: 15});
  const requests = Array.from({length: 8}, () => client.call({type: "audio"}));
  const settled = Promise.allSettled(requests);
  await assert.rejects(client.call({type: "audio"}), /backpressure/);
  assert.equal(client.pending.size, 8);
  assert.ok((await settled).every(result => result.status === "rejected"));
  assert.equal(client.pending.size, 0);
});
