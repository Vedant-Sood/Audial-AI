// A bounded display window; full captions remain in the server's exportable session.
export class TranscriptView {
  constructor(list, {limit = 500, decorate = null} = {}) {
    this.list = list; this.limit = limit; this.pending = []; this.frame = 0; this.decorate = decorate;
    this.host = list.ownerDocument.defaultView;
  }
  clear() {
    this.host.cancelAnimationFrame(this.frame); this.frame = 0;
    this.pending.length = 0; this.list.replaceChildren();
  }
  append(caption) {
    this.pending.push(caption);
    if (this.pending.length > this.limit) this.pending.splice(0, this.pending.length - this.limit);
    if (!this.frame) this.frame = this.host.requestAnimationFrame(() => this.render());
  }
  render() {
    this.frame = 0;
    const list = this.list, doc = list.ownerDocument;
    const follow = list.scrollTop + list.clientHeight >= list.scrollHeight - 40;
    const fragment = doc.createDocumentFragment();
    for (const caption of this.pending.splice(0)) {
      const item = doc.createElement("li"), header = doc.createElement("span"), text = doc.createElement("p");
      header.className = "hint";
      header.textContent = `${caption.speaker} · ${caption.start.toFixed(2)}–${caption.end.toFixed(2)}s${caption.overlap ? " · overlapping voices" : ""}`;
      text.textContent = caption.text; item.append(header, text);
      // e.g. the Sanket voice view adds the voice colour and a tone note
      try { this.decorate?.(item, caption); } catch { /* decoration never hides a caption */ }
      fragment.append(item);
    }
    list.append(fragment);
    while (list.childElementCount > this.limit) list.firstElementChild.remove();
    if (follow) list.scrollTop = list.scrollHeight;
  }
}
