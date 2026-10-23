// Kandha Stole firmware: the pattern engine. Plays the shared step lists on the motor zones.
// Mirrors app/kandha/patterns.py PatternPlayer (same steps and timing, same replacement rule,
// same intensity arithmetic; a step with on_ms 0 only rests) with two hardware additions: a
// MOTOR_MIN_DUTY floor, and a MOTOR_KICK_MS full-duty kick when a motor starts from rest so coin
// ERM motors spin up quickly enough for a crisp 120 ms tap.
// Not thread-safe: only loop() calls it (kandha.ino hands BLE writes over through a mailbox).
// tests/test_kandha_firmware_host.py runs it on the host against PatternPlayer.
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
    clock(now);
    if (seq == lastSeq_ && seqSeen_) return false;   // duplicate delivery
    lastSeq_ = seq; seqSeen_ = true;
    if (pattern == 0 || zones == 0) { halt(); return true; }
    const KandhaStep* steps = nullptr; uint8_t count = 0;
    for (int i = 0; i < KANDHA_PATTERN_COUNT; i++) {
      if (KANDHA_PATTERNS[i].id == pattern) { steps = KANDHA_PATTERNS[i].steps; count = KANDHA_PATTERNS[i].count; break; }
    }
    if (!steps && pattern > KANDHA_BUILTIN_PATTERN_MAX) {
      CustomPattern& c = custom_[pattern - KANDHA_BUILTIN_PATTERN_MAX - 1];
      if (c.used) { steps = c.steps; count = c.count; }
    }
    if (!steps || count == 0) { halt(); return false; }
    if (count > KANDHA_MAX_PATTERN_STEPS) count = KANDHA_MAX_PATTERN_STEPS;
    if (cfg.mirror) {
      uint8_t swapped = zones & ~(KANDHA_ZONE_L | KANDHA_ZONE_R);
      if (zones & KANDHA_ZONE_L) swapped |= KANDHA_ZONE_R;
      if (zones & KANDHA_ZONE_R) swapped |= KANDHA_ZONE_L;
      zones = swapped;
    }
    // A copy, so a PATTERNS upload of the id that is playing cannot change it halfway.
    for (uint8_t i = 0; i < count; i++) steps_[i] = steps[i];
    count_ = count; zones_ = zones;
    intensity_ = cfg.mute ? 0 : intensity;
    repeat_ = repeat == 0 ? 1 : repeat;
    for (int i = 0; i < 4; i++) scale_[i] = cfg.scale[i];
    step_ = 0; rep_ = 0; active_ = true;
    // No stop first: the motors go straight from the old pattern to the new one. A motor that is
    // already spinning gets no new kick; one still in its kick keeps it.
    enterStep(now);
    if (active_) apply(now);
    return true;
  }

  // Forget the last seq, so the next command plays whatever its seq. Called on every new
  // connection: the app numbers its commands from 1 again after a restart.
  void resetSeq() { seqSeen_ = false; }

  void stop(uint32_t now) {
    clock(now);
    halt();
  }

  bool playing() const { return active_; }

  // Call every millisecond or so. Phases are timed from when they were due, not from the tick
  // that noticed them, so a late tick does not push the rest of the pattern back.
  void tick(uint32_t now) {
    clock(now);
    while (active_) {
      const KandhaStep& s = steps_[step_];
      uint32_t length = phaseOn_ ? s.on_ms : s.off_ms;
      if (now - phaseStart_ < length) break;
      uint32_t end = phaseStart_ + length;
      if (phaseOn_ && s.off_ms > 0) { phaseOn_ = false; phaseStart_ = end; }
      else nextStep(end);
    }
    if (active_) apply(now);   // also ends the spin-up kick after MOTOR_KICK_MS
  }

 private:
  struct CustomPattern { bool used = false; uint8_t count = 0; KandhaStep steps[KANDHA_MAX_PATTERN_STEPS]; };

  // Notes the time of this call. A motor switched off earlier in the same millisecond, by a
  // command handled just before this one, has not stopped spinning: it is not at rest.
  void clock(uint32_t now) {
    if (now == now_) return;
    now_ = now;
    for (int i = 0; i < 4; i++) offThisMs_[i] = false;
  }

  void halt() {
    active_ = false;
    for (int i = 0; i < 4; i++) setLevel(i, 0);
  }

  void nextStep(uint32_t at) {
    if (++step_ >= count_) {
      step_ = 0;
      if (++rep_ >= repeat_) { halt(); return; }
    }
    enterStep(at);
  }

  // Starts step_ at `at`. Like PatternPlayer, a step with on_ms 0 only rests, and a step with
  // neither on nor off time is skipped, so it never blips a motor or delays the next step.
  void enterStep(uint32_t at) {
    while (steps_[step_].on_ms == 0 && steps_[step_].off_ms == 0) {
      if (++step_ >= count_) {
        step_ = 0;
        if (++rep_ >= repeat_) { halt(); return; }
      }
    }
    phaseStart_ = at;
    phaseOn_ = steps_[step_].on_ms > 0;
    // A motor at rest gets the kick, timed from when it starts. A motor still in its kick keeps
    // it: a step or command that takes over within MOTOR_KICK_MS does not cut it short.
    if (phaseOn_) for (int i = 0; i < 4; i++) if (level_[i] == 0 && !offThisMs_[i]) { kick_[i] = true; kickFrom_[i] = at; }
  }

  void apply(uint32_t now) {
    const KandhaStep& s = steps_[step_];
    for (int i = 0; i < 4; i++) {
      if (kick_[i] && now - kickFrom_[i] >= MOTOR_KICK_MS) kick_[i] = false;
      uint32_t duty = 0;
      if (phaseOn_ && (zones_ & (1 << i))) {
        duty = ((uint32_t)s.level * intensity_ * scale_[i]) / (255UL * 255UL);
        if (duty > 0 && duty < MOTOR_MIN_DUTY) duty = MOTOR_MIN_DUTY;
        if (duty > 0 && kick_[i]) duty = 255;   // spin-up kick
      }
      setLevel(i, (uint8_t)duty);
    }
  }

  void setLevel(int zone, uint8_t duty) {
    if (level_[zone] == duty) return;
    if (duty == 0) offThisMs_[zone] = true;
    level_[zone] = duty;
    ledcWrite(pins_[zone], duty);
  }

  int pins_[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};
  uint8_t level_[4] = {0, 0, 0, 0};
  bool kick_[4] = {false, false, false, false};
  uint32_t kickFrom_[4] = {0, 0, 0, 0};   // when each zone's kick started
  bool offThisMs_[4] = {false, false, false, false};
  uint32_t now_ = 0;
  uint8_t scale_[4] = {255, 255, 255, 255};
  KandhaStep steps_[KANDHA_MAX_PATTERN_STEPS];
  uint8_t count_ = 0, zones_ = 0, intensity_ = 0, repeat_ = 1, step_ = 0, rep_ = 0;
  bool phaseOn_ = true, active_ = false, seqSeen_ = false;
  uint8_t lastSeq_ = 0;
  uint32_t phaseStart_ = 0;
  CustomPattern custom_[255 - KANDHA_BUILTIN_PATTERN_MAX];
};
