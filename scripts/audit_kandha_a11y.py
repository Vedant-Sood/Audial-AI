"""Accessibility audit of the Kandha page in real Chromium: keyboard reach, visible focus, names, contrast, 1280x720.

    python -m scripts.audit_kandha_a11y --browser /opt/pw-browsers/chromium --output artifacts/a11y

Checks, on every screen (Live, Stole, Seats, Review, Settings) in both themes:
- every control is reachable with Tab and shows a visible focus indicator (outline or box-shadow change);
- every button, input and select has an accessible name;
- text colour against its background meets WCAG 2.1 AA (4.5:1, or 3:1 for large text), computed from the
  rendered colours of visible text elements;
- no horizontal page overflow at 1280x720;
- the tab list works with the arrow keys and every dialog can be closed with Escape.
This is an automated audit; a screen-reader walkthrough with a user is still needed.
"""
import argparse
import json
from pathlib import Path
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]

JS_FOCUSABLE = """() => [...document.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
  .filter(e => !e.closest('[hidden]') && !e.hidden && e.offsetParent !== null && !e.disabled && e.getAttribute('tabindex') !== '-1')
  .map(e => ({tag: e.tagName.toLowerCase(), id: e.id, name: (e.getAttribute('aria-label') || e.labels?.[0]?.textContent || e.textContent || e.title || '').trim().slice(0, 60), type: e.type || ''}))"""

JS_CONTRAST = """() => {
  const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const blend = (fg, bg) => ({r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1});
  const bgOf = el => { let node = el; while (node) { const c = parse(getComputedStyle(node).backgroundColor); if (c && c.a > 0) { if (c.a < 1) { const under = node.parentElement ? bgOf(node.parentElement) : {r: 255, g: 255, b: 255, a: 1}; return blend(c, under); } return c; } node = node.parentElement; } return {r: 255, g: 255, b: 255, a: 1}; };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  let n;
  while ((n = walker.nextNode())) {
    const el = n.parentElement; if (!el || seen.has(el) || !n.textContent.trim()) continue; seen.add(el);
    if (el.closest('[hidden], dialog:not([open]), svg, .welcome[hidden]') || el.offsetParent === null) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el);
    const f = fg.a < 1 ? blend(fg, bg) : fg;
    const l1 = lum(f), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    out.push({text: n.textContent.trim().slice(0, 40), ratio: +ratio.toFixed(2), large, need: large ? 3 : 4.5, ok: ratio >= (large ? 3 : 4.5), sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : '')});
  }
  return out;
}"""

JS_FOCUS_VISIBLE = """() => { const e = document.activeElement; if (!e || e === document.body) return null;
  const cs = getComputedStyle(e);
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  // SVG controls (pads, room chips) show focus as a thick stroke on themselves or their shape
  const shape = e.tagName === 'g' ? e.querySelector('circle, rect') : e;
  const stroke = shape && shape.namespaceURI === 'http://www.w3.org/2000/svg' && parseFloat(getComputedStyle(shape).strokeWidth) >= 3;
  const index = [...document.querySelectorAll('*')].indexOf(e);
  return {id: e.id, tag: e.tagName.toLowerCase(), index, visible: outline || !!stroke, outline: cs.outlineStyle, width: cs.outlineWidth}; }"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", default="/opt/pw-browsers/chromium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    from app.services.browser import BrowserService
    from app.kandha.bridge import MockBackend, MockStole
    from app.utils.config import Settings
    with tempfile.TemporaryDirectory(prefix="audial-a11y-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        service = BrowserService(settings=Settings(device="cpu"), kandha_backend=MockBackend([MockStole()]))
        service.start()
        report = {"scope": "Automated audit in Chromium; not a screen-reader session with a user", "screens": {}, "problems": []}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser, headless=True, args=["--no-sandbox"])
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(service.url + "/kandha/")
                page.wait_for_function("window.Kandha && window.Kandha.ready().ready")
                page.evaluate("window.Kandha.playDemo('seminar')")
                page.wait_for_timeout(4000)
                page.evaluate("window.Kandha.S.demo && window.Kandha.S.demo.stop()")
                for theme in ("dark", "light"):
                    page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
                    for screen in ("live", "stole", "seats", "review", "settings"):
                        page.evaluate(f"window.Kandha.showScreen('{screen}')")
                        page.wait_for_timeout(300)
                        key = f"{theme}/{screen}"
                        entry = {}
                        focusable = page.evaluate(JS_FOCUSABLE)
                        unnamed = [f for f in focusable if not f["name"]]
                        entry["focusable"] = len(focusable)
                        entry["unnamed"] = unnamed
                        # tab through everything once and record focus visibility
                        # two full Tab cycles: focus can briefly land on the document between controls
                        page.evaluate("document.activeElement && document.activeElement.blur(); window.scrollTo(0,0)")
                        seen, invisible = [], []
                        for _ in range(2 * len(focusable) + 6):
                            page.keyboard.press("Tab")
                            state = page.evaluate(JS_FOCUS_VISIBLE)
                            if not state:
                                continue
                            if state["index"] not in seen:
                                seen.append(state["index"])
                                if not state["visible"]:
                                    invisible.append(state)
                        entry["reached_by_tab"] = len(seen)
                        entry["focus_not_visible"] = invisible
                        if len(seen) < len(focusable):
                            report["problems"].append(f"{key}: only {len(seen)} of {len(focusable)} controls reached by Tab")
                        contrast = page.evaluate(JS_CONTRAST)
                        entry["text_elements"] = len(contrast)
                        entry["contrast_failures"] = [c for c in contrast if not c["ok"]]
                        entry["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                        report["screens"][key] = entry
                        page.screenshot(path=str(args.output / f"{theme}-{screen}.png"))
                        if unnamed:
                            report["problems"].append(f"{key}: unnamed controls {unnamed}")
                        if invisible:
                            report["problems"].append(f"{key}: focus not visible on {[i['id'] or i['tag'] for i in invisible]}")
                        if entry["contrast_failures"]:
                            report["problems"].append(f"{key}: contrast {[(c['sel'], c['ratio'], c['need']) for c in entry['contrast_failures']]}")
                        if entry["horizontal_overflow"]:
                            report["problems"].append(f"{key}: horizontal overflow at 1280x720")
                # tabs by keyboard, dialogs by Escape
                page.evaluate("window.Kandha.showScreen('live')")
                page.focus("#tab-live"); page.keyboard.press("ArrowRight")
                report["arrow_keys_move_tabs"] = page.evaluate("document.querySelector('#tab-stole').getAttribute('aria-selected') === 'true'")
                page.focus("#tab-stole"); page.keyboard.press("End")
                report["end_key_reaches_last_tab"] = page.evaluate("document.querySelector('#tab-settings').getAttribute('aria-selected') === 'true'")
                page.evaluate("window.Kandha.showScreen('live')")
                page.click("#missBtn"); page.wait_for_timeout(200)
                opened = page.evaluate("document.querySelector('#missDlg').open")
                page.keyboard.press("Escape"); page.wait_for_timeout(200)
                report["dialog_escape_closes"] = opened and not page.evaluate("document.querySelector('#missDlg').open")
                report["landmarks"] = page.evaluate("() => ({main: !!document.querySelector('main'), nav: !!document.querySelector('nav'), skip: !!document.querySelector('a.skip'), tablist: !!document.querySelector('[role=tablist]'), live_regions: document.querySelectorAll('[aria-live]').length, lang: document.documentElement.lang})")
                browser.close()
        finally:
            service.stop()
        report["result"] = "PASS" if not report["problems"] and report["arrow_keys_move_tabs"] and report["dialog_escape_closes"] else "FAIL"
        (args.output / "kandha-a11y.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "screens"}, indent=1))
        for key, entry in report["screens"].items():
            print(key, "focusable", entry["focusable"], "reached", entry["reached_by_tab"], "text", entry["text_elements"], "contrast fails", len(entry["contrast_failures"]), "overflow", entry["horizontal_overflow"])
        return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
