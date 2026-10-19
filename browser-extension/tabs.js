// Tab metadata comes exclusively from the extension's supported chrome.tabs API.
export function describeTab(tab) {
  const url = tab.url || tab.pendingUrl || "";
  const supported = /^https?:\/\//i.test(url) &&
    !/^https?:\/\/(chrome\.google\.com\/webstore|chromewebstore\.google\.com|microsoftedge\.microsoft\.com\/addons)/i.test(url);
  return {id: tab.id, window_id: tab.windowId, title: tab.title || "Untitled tab",
    supported, audible: Boolean(tab.audible), discarded: Boolean(tab.discarded),
    reason: supported ? tab.discarded ? "Open this suspended tab, then invoke Audial-AI from its toolbar." : "Capture requires invoking Audial-AI in this tab's toolbar."
      : "Browser settings, extension stores and other restricted pages cannot be captured. Choose a regular web tab."};
}

export function reconcileTabs(tabs) {
  return [...new Map(tabs.filter(tab => Number.isInteger(tab.id)).map(tab => [tab.id, describeTab(tab)])).values()]
    .sort((a, b) => Number(b.audible) - Number(a.audible) || a.window_id - b.window_id || a.id - b.id);
}
