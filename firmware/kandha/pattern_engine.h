// Kandha Stole firmware: the pattern engine. Plays the shared step lists on the motor zones.
// Mirrors app/kandha/patterns.py PatternPlayer (same steps, same replacement rule, same
// intensity arithmetic) with one hardware addition: a short full-duty kick when a step starts
// from rest so coin ERM motors spin up quickly enough for a crisp 120 ms tap.
#pragma once
#include <Arduino.h>
#include "config.h"
#include "patterns.h"

struct KandhaConfig {
  uint8_t scale[4] = {255, 255, 255, 255};   // L, R, B, F
  uint8_t mute = 0;
  uint8_t mirror = 0;
  uint8_t testMode = 0;
};

class PatternEngine {
 public:
  void begin() {
    const int pins[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};
    for (int i = 0; i < 4; i++) {
      pins_[i] = pins[i];
      ledcAttach(pins_[i], PWM_FREQUENCY_HZ, PWM_RESOLUTION_BITS);
      ledcWrite(pins_[i], 0);
      level_[i] = 0;
    }
  }

  // Up to 224 custom patterns (ids 32-255) uploaded over PATTERNS live in RAM.
  bool storeCustom(uint8_t id, const uint8_t* data, size_t n) {
    if (id <= KANDHA_BUILTIN_PATTERN_MAX || n < 1 || n > KANDHA_MAX_PATTERN_STEPS) return false;
    CustomPattern& c = custom_[id - KANDHA_BUILTIN_PATTERN_MAX - 1];
    c.count = n;
    for (size_t i = 0; i < n; i++) {
      c.steps[i].on_ms = data[i * 5] | (data[i * 5 + 1] << 8);
      c.steps[i].off_ms = data[i * 5 + 2] | (data[i * 5 + 3] << 8);
      c.steps[i].level = data[i * 5 + 4];
    }
    c.used = true;
    return true;
  }

  // A HAPTIC command: [seq][zones][pattern][intensity][repeat]. A new command replaces the old.
  bool play(uint8_t seq, uint8_t zones, uint8_t pattern, uint8_t intensity, uint8_t repeat, const KandhaConfig& cfg, uint32_t now) {
    if (seq == lastSeq_ && seqSeen_) return false;   // duplicate delivery
    lastSeq_ = seq; seqSeen_ = true;
    stop();
    if (pattern == 0 || zones == 0) return true;
    const KandhaStep* steps = nullptr; uint8_t count = 0;
    for (int i = 0; i < KANDHA_PATTERN_COUNT; i++) {
      if (KANDHA_PATTERNS[i].id == pattern) { steps = KANDHA_PATTERNS[i].steps; count = KANDHA_PATTERNS[i].count; break; }
    }
    if (!steps && pattern > KANDHA_BUILTIN_PATTERN_MAX) {
      CustomPattern& c = custom_[pattern - KANDHA_BUILTIN_PATTERN_MAX - 1];
      if (c.used) { steps = c.steps; count = c.count; }
    }
    if (!steps || count == 0) return false;
    if (cfg.mirror) {
      uint8_t swapped = zones & ~(KANDHA_ZONE_L | KANDHA_ZONE_R);
      if (zones & KANDHA_ZONE_L) swapped |= KANDHA_ZONE_R;
      if (zones & KANDHA_ZONE_R) swapped |= KANDHA_ZONE_L;
      zones = swapped;
    }
    steps_ = steps; count_ = count; zones_ = zones;
    intensity_ = cfg.mute ? 0 : intensity;
    repeat_ = repeat == 0 ? 1 : repeat;
    for (int i = 0; i < 4; i++) scale_[i] = cfg.scale[i];
    step_ = 0; rep_ = 0; phaseOn_ = true; phaseStart_ = now; active_ = true;
    apply(now);
    return true;
  }

  void stop() {
    active_ = false;
    for (int i = 0; i < 4; i++) setLevel(i, 0);
  }

  bool playing() const { return active_; }

  // Call every millisecond or so.
  void tick(uint32_t now) {
    if (!active_) return;
    const KandhaStep& s = steps_[step_];
    uint32_t elapsed = now - phaseStart_;
    if (phaseOn_) {
      if (elapsed >= s.on_ms) {
        if (s.off_ms > 0) { phaseOn_ = false; phaseStart_ = now; apply(now); }
        else { advance(now); }
      } else {
        apply(now);   // the overdrive kick ends after MOTOR_KICK_MS
      }
    } else if (elapsed >= s.off_ms) {
      advance(now);
    }
  }

 private:
  struct CustomPattern { bool used = false; uint8_t count = 0; KandhaStep steps[KANDHA_MAX_PATTERN_STEPS]; };

  void advance(uint32_t now) {
    step_++;
    if (step_ >= count_) {
      step_ = 0; rep_++;
      if (rep_ >= repeat_) { stop(); return; }
    }
    phaseOn_ = true; phaseStart_ = now;
    apply(now);
  }

  void apply(uint32_t now) {
    const KandhaStep& s = steps_[step_];
    for (int i = 0; i < 4; i++) {
      uint8_t bit = 1 << i;
      if (!(zones_ & bit) || !phaseOn_) { setLevel(i, 0); continue; }
      uint32_t duty = ((uint32_t)s.level * intensity_ * scale_[i]) / (255UL * 255UL);
      if (duty > 0 && duty < MOTOR_MIN_DUTY) duty = MOTOR_MIN_DUTY;
      if (duty > 0 && now - phaseStart_ < MOTOR_KICK_MS && level_[i] == 0) duty = 255;   // spin-up kick
      setLevel(i, (uint8_t)duty);
    }
  }

  void setLevel(int zone, uint8_t duty) {
    if (level_[zone] == duty) return;
    level_[zone] = duty;
    ledcWrite(pins_[zone], duty);
  }

  int pins_[4];
  uint8_t level_[4];
  uint8_t scale_[4] = {255, 255, 255, 255};
  const KandhaStep* steps_ = nullptr;
  uint8_t count_ = 0, zones_ = 0, intensity_ = 0, repeat_ = 1, step_ = 0, rep_ = 0;
  bool phaseOn_ = true, active_ = false, seqSeen_ = false;
  uint8_t lastSeq_ = 0;
  uint32_t phaseStart_ = 0;
  CustomPattern custom_[255 - KANDHA_BUILTIN_PATTERN_MAX];
};
