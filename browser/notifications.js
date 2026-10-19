export class BrowserNotices {
  constructor(region, history) {
    this.region = region; this.history = history; this.items = []; this.timer = 0;
    region.hidden = true;
  }
  clear() {clearTimeout(this.timer); this.region.hidden = true;}
  publish(message, severity = "error") {
    if (!message) {this.clear(); return;}
    const now = Date.now(), previous = this.items.at(-1);
    if (previous?.message === message && previous.severity === severity && now - previous.time < 20000) {
      previous.count++; this.renderHistory(); return;
    }
    this.items.push({message: String(message), severity, time: now, count: 1});
    if (this.items.length > 100) this.items.shift();
    const doc = this.region.ownerDocument, text = doc.createElement("span"), dismiss = doc.createElement("button");
    text.textContent = message; dismiss.textContent = "Dismiss";
    dismiss.setAttribute("aria-label", "Dismiss " + severity); dismiss.addEventListener("click", () => this.clear());
    this.region.replaceChildren(text, dismiss); this.region.dataset.severity = severity;
    this.region.setAttribute("role", severity === "error" ? "alert" : "status");
    this.region.hidden = false; clearTimeout(this.timer);
    if (severity !== "error") this.timer = setTimeout(() => {this.region.hidden = true;}, 7000);
    this.renderHistory();
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
