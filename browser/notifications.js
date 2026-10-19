// Persistent failures and transient warnings share a bounded, accessible history.
export class BrowserNotices {
  constructor(region, history) {
    this.region = region; this.history = history; this.items = []; this.timer = 0;
    this.failures = new Map(); this.warning = null;
    region.hidden = true;
  }
  clear() {
    clearTimeout(this.timer); this.failures.clear(); this.warning = null; this.renderRegion();
  }
  publish(message, severity = "error") {
    if (!message) {this.clear(); return;}
    message = String(message);
    const now = Date.now();
    const previous = this.items.findLast(item => item.message === message && item.severity === severity && now - item.time < 20000);
    if (previous) {previous.count++; this.renderHistory(); return;}
    const item = {message, severity, time: now, count: 1};
    this.items.push(item);
    if (this.items.length > 100) this.items.shift();
    if (severity === "error") {
      this.failures.set(message, item);
      if (this.failures.size > 100) this.failures.delete(this.failures.keys().next().value);
    } else {
      this.warning = item;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => {this.warning = null; this.renderRegion();}, 7000);
    }
    this.renderRegion(); this.renderHistory();
  }
  renderRegion() {
    const doc = this.region.ownerDocument, fragment = doc.createDocumentFragment();
    const visible = [...this.failures.values()].slice(-3);
    if (this.warning) visible.push(this.warning);
    for (const item of visible) {
      const row = doc.createElement("div"), text = doc.createElement("span"), dismiss = doc.createElement("button");
      row.className = "notice-row"; row.dataset.severity = item.severity;
      text.textContent = item.message; dismiss.textContent = "Dismiss";
      dismiss.setAttribute("aria-label", "Dismiss " + item.severity);
      dismiss.addEventListener("click", () => {
        if (item.severity === "error") this.failures.delete(item.message);
        else this.warning = null;
        this.renderRegion();
      });
      row.append(text, dismiss); fragment.append(row);
    }
    if (this.failures.size > 3) {
      const earlier = doc.createElement("button");
      earlier.textContent = `${this.failures.size - 3} earlier failures · view history`;
      earlier.addEventListener("click", () => {const details = this.history?.closest("details"); if (details) details.open = true; this.history?.scrollIntoView({block:"nearest"});});
      fragment.append(earlier);
    }
    this.region.replaceChildren(fragment);
    this.region.dataset.severity = this.failures.size ? "error" : "warning";
    this.region.setAttribute("role", this.failures.size ? "alert" : "status");
    this.region.hidden = visible.length === 0;
  }
  renderHistory() {
    if (!this.history) return;
    const doc = this.history.ownerDocument, fragment = doc.createDocumentFragment();
    for (const item of [...this.items].reverse()) {
      const row = doc.createElement("li"); row.textContent = `${new Date(item.time).toLocaleTimeString()} · ${item.severity} · ${item.message}${item.count > 1 ? " (" + item.count + " occurrences)" : ""}`;
      fragment.append(row);
    }
    this.history.replaceChildren(fragment);
  }
}
