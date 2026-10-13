// Labels accompany all colors. Arbitrary model labels never become CSS values.
export function foreground(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error("Use a #RRGGBB color.");
  const linear = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
  const l = linear.reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
  return (l + .05) / .05 >= 1.05 / (l + .05) ? "#000000" : "#ffffff";
}

export function displayEmotion(element, estimate, colors) {
  const label = Object.hasOwn(colors, estimate?.tone) ? estimate.tone : "uncertain";
  const color = colors[label];
  element.textContent = label[0].toUpperCase() + label.slice(1);
  element.style.backgroundColor = color;
  element.style.color = foreground(color);
  element.setAttribute("aria-label", "Voice emotion estimate: " + label);
}
