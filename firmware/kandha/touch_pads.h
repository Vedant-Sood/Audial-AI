// Kandha Stole firmware: four textile touch pads with tap, double-tap and long-press gestures.
// Timing matches docs/kandha/PROTOCOL.md: a touch shorter than 400 ms is a tap unless another
// touch starts within 300 ms of its end (double); a touch held 700 ms is a long press (reported
// once, on the 700 ms mark). A change counts once it has held for 40 ms (debounce), and the
// gesture times run from when the change was first seen, so the debounce does not stretch them.
// Every time is as precise as the TOUCH_POLL_MS polling. tests/test_kandha_firmware_host.py
// checks these rules on the host.
#pragma once
#include <Arduino.h>
#include "config.h"
#include "patterns.h"

class TouchPads {
 public:
  typedef void (*GestureHandler)(uint8_t pad, uint8_t gesture);

  void begin(GestureHandler handler) {
    handler_ = handler;
    const int pins[4] = {PIN_PAD_L, PIN_PAD_R, PIN_PAD_B, PIN_PAD_Q};
    for (int i = 0; i < 4; i++) { pins_[i] = pins[i]; }
    calibrate();
  }

  // Baselines are measured untouched; call again from the serial console after sewing the pads.
  void calibrate() {
    for (int i = 0; i < 4; i++) {
      uint32_t sum = 0;
      for (int k = 0; k < 20; k++) { sum += touchRead(pins_[i]); delay(5); }
      baseline_[i] = sum / 20;
      threshold_[i] = (uint32_t)(baseline_[i] * TOUCH_THRESHOLD_RATIO);
    }
    calibrated_ = true;
  }

  bool calibrated() const { return calibrated_; }
  uint32_t raw(int pad) const { return touchRead(pins_[pad]); }
  uint32_t baseline(int pad) const { return baseline_[pad]; }

  // Poll every TOUCH_POLL_MS.
  void poll(uint32_t now) {
    for (int i = 0; i < 4; i++) {
      uint32_t value = touchRead(pins_[i]);
#if TOUCH_RISES_WHEN_PRESSED
      bool pressed = value > threshold_[i];
#else
      bool pressed = value < (uint32_t)(baseline_[i] / TOUCH_THRESHOLD_RATIO);
#endif
      Pad& p = state_[i];
      if (pressed != p.rawPressed) { p.rawPressed = pressed; p.changedAt = now; }
      if (pressed != p.pressed && now - p.changedAt >= TOUCH_DEBOUNCE_MS) {
        p.pressed = pressed;
        if (pressed) {
          // A touch that starts within the gap after a tap is the second half of a double.
          p.second = p.tapPending && p.changedAt - p.lastTapAt <= GESTURE_DOUBLE_GAP_MS;
          p.pressedAt = p.changedAt; p.longSent = false;
        } else {
          uint32_t held = p.changedAt - p.pressedAt;
          if (!p.longSent && held < GESTURE_TAP_MAX_MS) {
            if (p.second) {
              p.tapPending = false; emit(i, KANDHA_GESTURE_DOUBLE);
            } else {
              p.tapPending = true; p.lastTapAt = p.changedAt;
            }
          }
          p.second = false;
        }
      }
      // rawPressed too: a touch already lifted (its release still debouncing) is not a long press.
      if (p.pressed && p.rawPressed && !p.longSent && now - p.pressedAt >= GESTURE_LONG_MS) {
        p.longSent = true; p.tapPending = false; emit(i, KANDHA_GESTURE_LONG);
      }
      // The tap is reported once no second touch can start in time, unless one already has
      // (debounced, or still being debounced).
      bool secondStarting = p.rawPressed && !p.pressed && p.changedAt - p.lastTapAt <= GESTURE_DOUBLE_GAP_MS;
      if (p.tapPending && !p.second && !secondStarting && now - p.lastTapAt > GESTURE_DOUBLE_GAP_MS) {
        p.tapPending = false; emit(i, KANDHA_GESTURE_TAP);
      }
    }
  }

 private:
  struct Pad { bool rawPressed = false, pressed = false, longSent = false, tapPending = false, second = false; uint32_t changedAt = 0, pressedAt = 0, lastTapAt = 0; };
  void emit(int pad, uint8_t gesture) { if (handler_) handler_(pad + 1, gesture); }

  GestureHandler handler_ = nullptr;
  int pins_[4];
  uint32_t baseline_[4] = {0, 0, 0, 0}, threshold_[4] = {0, 0, 0, 0};
  Pad state_[4];
  bool calibrated_ = false;
};
