"""Kandha layout check: overlapping text or icons, missing-glyph boxes, and off-screen spill.

Opens the real Kandha page in Chromium (the companion serves it; the stole is the in-process
mock), drives each screen in two states (empty, and after the scripted seminar demo with one
Hindi caption) at each viewport size, saves a screenshot of each, and reports:

- overlap: two visible text boxes (or a text box and a small icon) intersecting, measured on the
  rendered text ranges, clipped by any scrolling or overflow-hidden ancestor;
- missing glyphs: a character that renders exactly like an unassigned code point, i.e. as the
  "tofu" box, in the font its element uses;
- spill: horizontal scrolling, and visible elements reaching past the right edge.

--fonts bundled restricts Chromium to the fonts Kandha ships (browser/kandha/fonts), the way a
minimal Linux install or a Qt WebEngine without Hindi fonts sees the page; --fonts system uses
whatever the machine has.

    python -m scripts.check_kandha_layout --output docs/kandha/validation/ui-before --fonts both
Exit status 1 when any issue is found (for CI); --report-only always exits 0.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SIZES = [(1280, 720), (1920, 1080), (390, 844), (360, 640)]
SCREENS = ["live", "stole", "seats", "review", "settings"]
HINDI_LINE = "नमस्ते, आज हम केस पर चर्चा करेंगे।"

ANALYZE = r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  const shown = (el) => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      if (e.hidden) return false;
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
      if (e.tagName === 'DIALOG' && !e.open) return false;
    }
    return true;
  };
  const clipOf = (el, self) => {     // intersect with every clipping box (the element too, for text) and the viewport
    let r = { left: 0, top: 0, right: vw, bottom: vh };
    for (let e = self ? el : el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
        const b = e.getBoundingClientRect();
        r = { left: Math.max(r.left, b.left), top: Math.max(r.top, b.top), right: Math.min(r.right, b.right), bottom: Math.min(r.bottom, b.bottom) };
      }
    }
    return r;
  };
  const cut = (a, c) => ({ left: Math.max(a.left, c.left), top: Math.max(a.top, c.top), right: Math.min(a.right, c.right), bottom: Math.min(a.bottom, c.bottom) });
  const area = (r) => Math.max(0, r.right - r.left) * Math.max(0, r.bottom - r.top);
  const modal = document.querySelector('dialog[open]');
  const scope = modal || document.body;
  const label = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 2).map((c) => '.' + c).join('');
    return el.tagName.toLowerCase() + id + cls;
  };
  // hidden behind something opaque (e.g. a card laid over the page) is not "visible", so it
  // cannot overlap anything; a transparent element on top does not hide what is under it
  const opaque = (node) => {
    for (let e = node; e && e !== document.documentElement; e = e.parentElement) {
      const bg = getComputedStyle(e).backgroundColor;
      const m = bg.match(/rgba?\(([^)]+)\)/);
      if (m) { const parts = m[1].split(',').map(Number); if (parts.length < 4 || parts[3] > 0.9) return true; }
    }
    return false;
  };
  const occluded = (el, r) => {
    const x = Math.min(vw - 1, Math.max(0, (r.left + r.right) / 2)), y = Math.min(vh - 1, Math.max(0, (r.top + r.bottom) / 2));
    const hit = document.elementFromPoint(x, y);
    if (!hit || hit === el || el.contains(hit) || hit.contains(el)) return false;
    const common = (() => { for (let e = hit; e; e = e.parentElement) if (e.contains(el)) return e; return null; })();
    for (let e = hit; e && e !== common; e = e.parentElement) {
      const bg = getComputedStyle(e).backgroundColor, m = bg.match(/rgba?\(([^)]+)\)/);
      if (m) { const parts = m[1].split(',').map(Number); if (parts.length < 4 || parts[3] > 0.9) return true; }
    }
    return false;
  };
  const boxes = [];
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) {
    const text = n.nodeValue.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const el = n.parentElement;
    if (!el || el.closest('script,style,title,option,template,noscript') || !shown(el)) continue;
    const clip = clipOf(el, true);     // an ellipsis-cut text stops at its own box
    const range = document.createRange(); range.selectNodeContents(n);
    for (const rect of range.getClientRects()) {
      const r = cut(rect, clip);
      if (r.right - r.left < 1 || r.bottom - r.top < 1) continue;
      if (occluded(el, r)) continue;
      boxes.push({ node: n, el, r, text: text.slice(0, 48), where: label(el), kind: 'text' });
    }
  }
  for (const el of scope.querySelectorAll('svg, img')) {
    if (el.tagName.toLowerCase() === 'svg' && el.parentElement && el.parentElement.closest('svg')) continue;
    const b = el.getBoundingClientRect();
    if (b.width > 48 || b.height > 48 || b.width < 2 || !shown(el)) continue;   // icons only, not diagrams
    const r = cut(b, clipOf(el));
    if (area(r) < 4 || occluded(el, r)) continue;
    boxes.push({ node: el, el, r, text: '[icon]', where: label(el), kind: 'icon' });
  }
  const overlaps = [];
  const seen = new Set();
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.node === b.node) continue;
    if (a.kind === 'icon' && b.el && a.el.contains(b.el)) continue;
    if (b.kind === 'icon' && a.el && b.el.contains(a.el)) continue;
    const x = cut(a.r, b.r);
    const w = x.right - x.left, h = x.bottom - x.top;
    if (w <= 2 || h <= 2) continue;
    const key = [a.where, a.text, b.where, b.text].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    overlaps.push({ a: `${a.where} "${a.text}"`, b: `${b.where} "${b.text}"`, px: Math.round(w * h) });
  }
  // missing glyphs: compare each non-ASCII character with an unassigned code point in the same font
  const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 64;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const draw = (ch, family) => { ctx.clearRect(0, 0, 64, 64); ctx.font = `400 40px ${family}`; ctx.fillStyle = '#000'; ctx.textBaseline = 'middle'; ctx.fillText(ch, 8, 32); return ctx.getImageData(0, 0, 64, 64).data.join(','); };
  const missing = {};
  const checked = new Set();
  for (const box of boxes) {
    if (box.kind !== 'text') continue;
    const family = getComputedStyle(box.el).fontFamily;
    const tofu = draw('͸', family);
    for (const ch of new Set(Array.from(box.node.nodeValue))) {
      if (ch.charCodeAt(0) < 128 || /\s/.test(ch) || /\p{M}/u.test(ch)) continue;
      const key = ch + '|' + family;
      if (checked.has(key)) continue;
      checked.add(key);
      if (draw(ch, family) === tofu) (missing[`U+${ch.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')} "${ch}"`] ||= []).push(box.where);
    }
  }
  const spill = [];
  const sw = document.scrollingElement.scrollWidth;
  if (sw > vw + 1) spill.push(`page scrolls sideways: ${sw}px wide in a ${vw}px window`);
  for (const box of boxes) {
    const b = box.el.getBoundingClientRect();
    if (b.right > vw + 1 && box.kind === 'text' && clipOf(box.el).right >= vw) spill.push(`${box.where} "${box.text}" ends at ${Math.round(b.right)}px`);
  }
  return { overlaps, missing, spill: Array.from(new Set(spill)).slice(0, 20), boxes: boxes.length };
}
"""


def minimal_fontconfig(directory):
    """A fontconfig that sees only Kandha's bundled fonts."""
    conf = Path(directory) / "fonts.conf"
    cache = Path(directory) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    conf.write_text(f"""<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig><dir>{ROOT / 'browser' / 'kandha' / 'fonts'}</dir><cachedir>{cache}</cachedir></fontconfig>
""", encoding="utf-8")
    return str(conf)


def run(output, fontsets, browser_path, states):
    os.environ.setdefault("ACCESSIBILITY_AI_HOME", tempfile.mkdtemp(prefix="kandha-layout-"))
    from playwright.sync_api import sync_playwright
    from app.kandha.bridge import MockBackend, MockStole
    from app.services.browser import BrowserService
    from app.utils.config import Settings

    service = BrowserService(settings=Settings(device="cpu"), kandha_backend=MockBackend([MockStole()]))
    service.start()
    report = {}
    try:
        with sync_playwright() as pw, tempfile.TemporaryDirectory() as fontdir:
            for fontset in fontsets:
                env = dict(os.environ)
                if fontset == "bundled":
                    env["FONTCONFIG_FILE"] = minimal_fontconfig(fontdir)
                launch = {"headless": True, "args": ["--no-sandbox"], "env": env}
                if browser_path:
                    launch["executable_path"] = browser_path
                browser = pw.chromium.launch(**launch)
                for width, height in SIZES:
                    size = f"{width}x{height}"
                    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                    page.goto(service.url + "/kandha/")
                    page.wait_for_function("window.Kandha && window.Kandha.ready().ready", timeout=30000)
                    for state in states:
                        if state == "demo":
                            page.evaluate("window.Kandha.playDemo('seminar')")
                            page.wait_for_timeout(9000)
                            page.evaluate(f"window.Kandha.handleFinal({json.dumps(HINDI_LINE)}, {{ lang: 'hi' }})")
                            page.wait_for_timeout(500)
                        shots = SCREENS if state == "demo" else ["live", "seats"]
                        for screen in shots:
                            page.evaluate(f"window.Kandha.showScreen('{screen}')")
                            page.wait_for_timeout(300)
                            name = f"{state}-{screen}"
                            report[f"{fontset}/{size}/{name}"] = page.evaluate(ANALYZE)
                            if output:
                                target = Path(output) / fontset / size / f"{name}.jpg"
                                target.parent.mkdir(parents=True, exist_ok=True)
                                page.screenshot(path=str(target), type="jpeg", quality=70)
                        if state == "demo":
                            page.evaluate("window.Kandha.showScreen('live')")
                            page.evaluate("document.querySelector('#missBtn') && document.querySelector('#missBtn').click()")
                            page.wait_for_timeout(300)
                            report[f"{fontset}/{size}/demo-live-missdialog"] = page.evaluate(ANALYZE)
                            if output:
                                page.screenshot(path=str(Path(output) / fontset / size / "demo-live-missdialog.jpg"), type="jpeg", quality=70)
                            page.keyboard.press("Escape")
                            page.evaluate("document.querySelector('#audioBtn') && document.querySelector('#audioBtn').click()")
                            page.wait_for_timeout(600)
                            report[f"{fontset}/{size}/demo-live-audiodialog"] = page.evaluate(ANALYZE)
                            if output:
                                page.screenshot(path=str(Path(output) / fontset / size / "demo-live-audiodialog.jpg"), type="jpeg", quality=70)
                            page.keyboard.press("Escape")
                    page.close()
                browser.close()
    finally:
        service.stop()
    return report


def summarise(report):
    issues = 0
    lines = []
    for key, result in report.items():
        parts = []
        if result["overlaps"]:
            parts.append(f"{len(result['overlaps'])} overlaps")
        if result["missing"]:
            parts.append(f"{len(result['missing'])} missing glyphs")
        if result["spill"]:
            parts.append(f"{len(result['spill'])} spill")
        if parts:
            issues += 1
            lines.append(f"{key}: " + ", ".join(parts))
    return issues, lines


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", help="folder for screenshots and report.json")
    parser.add_argument("--fonts", choices=["system", "bundled", "both"], default="both")
    parser.add_argument("--browser", default=os.environ.get("KANDHA_CHROMIUM") or None, help="Chromium executable")
    parser.add_argument("--states", default="empty,demo")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    fontsets = ["system", "bundled"] if args.fonts == "both" else [args.fonts]
    report = run(args.output, fontsets, args.browser, args.states.split(","))
    issues, lines = summarise(report)
    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        (Path(args.output) / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines) or "no layout issues")
    print(f"{len(report)} views checked, {issues} with issues")
    sys.exit(0 if args.report_only or issues == 0 else 1)


if __name__ == "__main__":
    main()
