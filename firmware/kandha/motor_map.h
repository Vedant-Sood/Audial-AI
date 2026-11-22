// Kandha Stole firmware: which GPIO drives which motor zone, and the "identify" wizard that
// finds out by buzzing one GPIO at a time and asking the wearer where they felt it.
//
// Why: the four motor transistors sit on GPIO 8, 9, 10 and 11, but the wiring may not follow
// L, R, B, F in that order. The ESP32 cannot sense where a motor is on the body, so a person
// answers: type L, R, B or F in the serial console, or tap the L, R or B pad (the Q pad means
// F, front, because the F pad is not wired yet). The answer is saved in flash (NVS) and
// survives power-off and reflashing; the pattern engine uses it from then on.
#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "config.h"

static const int MOTOR_GPIOS[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};   // the four motor pins (8-11)
static const char ZONE_LETTER[4] = {'L', 'R', 'B', 'F'};
static const char* const ZONE_WORD[4] = {"LEFT shoulder", "RIGHT shoulder", "BACK of the neck", "FRONT (collarbone)"};

static int zoneFromLetter(char c) {
  switch (toupper(c)) { case 'L': return 0; case 'R': return 1; case 'B': return 2; case 'F': return 3; default: return -1; }
}

// ---------------------------------------------------------------------------- the saved map
struct MotorMap {
  int pin[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};   // pin[zone], zone order L, R, B, F
  bool fromFlash = false;

  static bool isMotorPin(int gpio) {
    for (int i = 0; i < 4; i++) if (MOTOR_GPIOS[i] == gpio) return true;
    return false;
  }

  // Valid when every zone has one of the four motor pins and no pin is used twice.
  static bool valid(const int p[4]) {
    for (int i = 0; i < 4; i++) {
      if (!isMotorPin(p[i])) return false;
      for (int k = 0; k < i; k++) if (p[k] == p[i]) return false;
    }
    return true;
  }

  void load() {
    Preferences prefs;
    uint8_t saved[4] = {0, 0, 0, 0};
    fromFlash = false;
    if (prefs.begin("kandha", true)) {
      if (prefs.getBytesLength("motors") == 4) prefs.getBytes("motors", saved, 4);
      prefs.end();
    }
    int p[4] = {saved[0], saved[1], saved[2], saved[3]};
    if (valid(p)) { for (int i = 0; i < 4; i++) pin[i] = p[i]; fromFlash = true; }
    else resetToDefault();
  }

  bool save(const int p[4]) {
    if (!valid(p)) return false;
    uint8_t bytes[4];
    for (int i = 0; i < 4; i++) { pin[i] = p[i]; bytes[i] = (uint8_t)p[i]; }
    Preferences prefs;
    if (!prefs.begin("kandha", false)) return false;
    bool ok = prefs.putBytes("motors", bytes, 4) == 4;
    prefs.end();
    fromFlash = ok;
    return ok;
  }

  void forget() {
    Preferences prefs;
    if (prefs.begin("kandha", false)) { prefs.remove("motors"); prefs.end(); }
    resetToDefault();
  }

  void resetToDefault() {
    const int d[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};
    for (int i = 0; i < 4; i++) pin[i] = d[i];
    fromFlash = false;
  }

  void print() const {
    Serial.printf("Motor map (%s): L=GPIO %d  R=GPIO %d  B=GPIO %d  F=GPIO %d\n",
                  fromFlash ? "saved" : "default, not identified yet", pin[0], pin[1], pin[2], pin[3]);
  }
};

// ---------------------------------------------------------------------------- the wizard
// Non-blocking: tick() from loop(), answer() with each console line or pad tap. While it runs
// the caller must keep the pattern engine silent and ignore HAPTIC writes from the app.
class MotorWizard {
 public:
  // writeDuty(gpio, duty) drives one motor pin directly (0 = off, 255 = full).
  void begin(void (*writeDuty)(int, uint8_t)) { write_ = writeDuty; }

  bool active() const { return state_ != IDLE; }
  bool finished() { bool f = finished_; finished_ = false; return f; }   // true once, after a save
  const int* result() const { return result_; }

  void start() {
    for (int i = 0; i < 4; i++) { answer_[i] = -1; result_[i] = -1; }
    index_ = 0;
    state_ = ASKING;
    Serial.println();
    Serial.println("=== Find the motors ===");
    Serial.println("Wear the stole (or hold each motor). Each motor pin buzzes on its own, in turn.");
    Serial.println("Say where you feel it: type L, R, B or F and press Enter,");
    Serial.println("or tap the stole's L, R or B pad (tap Q for F, front).");
    Serial.println("L and R each have TWO motors, so you feel two buzzes at once there; B and F have one.");
    Serial.println("Other answers: again (buzz again), none (felt nothing), back (previous pin), cancel.");
    beginPin();
  }

  void cancel() {
    stopBuzz();
    state_ = IDLE;
    Serial.println("Motor finding cancelled. The motor map is unchanged.");
  }

  void tick(uint32_t now) {
    if (state_ != ASKING || buzzesLeft_ == 0) return;
    uint32_t t = now - cycleStart_;
    if (t < BUZZ_ON_MS) setBuzz(true);
    else if (t < BUZZ_ON_MS + BUZZ_OFF_MS) setBuzz(false);
    else {
      cycleStart_ = now;
      if (--buzzesLeft_ == 0) {
        setBuzz(false);
        Serial.printf("  (GPIO %d stopped buzzing. Answer L, R, B, F or none, or type again.)\n", MOTOR_GPIOS[index_]);
      }
    }
  }

  // One console line or one pad tap ("L", "R", "B", "F"). Returns true when consumed.
  bool answer(String text) {
    text.trim();
    String word = text; word.toLowerCase();
    if (!active()) return false;
    if (word == "cancel" || word == "quit" || word == "exit") { cancel(); return true; }
    if (state_ == CONFIRMING) {
      if (word == "save" || word == "yes" || word == "y") { save(); return true; }
      if (word == "redo") { start(); return true; }
      Serial.println("Type save to keep this map, redo to start again, or cancel.");
      return true;
    }
    if (word == "again") { beginPin(); return true; }
    if (word == "back") {
      if (index_ > 0) { stopBuzz(); index_--; answer_[index_] = -1; }
      beginPin();
      return true;
    }
    if (word == "none" || word == "nothing" || word == "n") {
      answer_[index_] = -2;
      Serial.printf("  GPIO %d: felt nothing. Check that motor's transistor, diode and wires.\n", MOTOR_GPIOS[index_]);
      next();
      return true;
    }
    int zone = word.length() == 1 ? zoneFromLetter(word[0]) : -1;
    if (zone < 0) {
      Serial.println("  Answer L, R, B or F (or again, none, back, cancel).");
      return true;
    }
    for (int i = 0; i < index_; i++) {
      if (answer_[i] == zone) Serial.printf("  Note: GPIO %d was also %c. Each zone should have one pin.\n", MOTOR_GPIOS[i], ZONE_LETTER[zone]);
    }
    answer_[index_] = zone;
    Serial.printf("  GPIO %d -> %c (%s)\n", MOTOR_GPIOS[index_], ZONE_LETTER[zone], ZONE_WORD[zone]);
    next();
    return true;
  }

 private:
  enum State { IDLE, ASKING, CONFIRMING };
  static constexpr uint32_t BUZZ_ON_MS = 350, BUZZ_OFF_MS = 650;
  static constexpr uint8_t BUZZES_PER_ASK = 12;   // about 12 s, then it waits quietly

  void beginPin() {
    stopBuzz();
    buzzesLeft_ = BUZZES_PER_ASK;
    cycleStart_ = millis();
    Serial.printf("\n[%d/4] GPIO %d is buzzing now. Where do you feel it? (L/R/B/F, none, again)\n", index_ + 1, MOTOR_GPIOS[index_]);
  }

  void next() {
    stopBuzz();
    index_++;
    if (index_ < 4) { delay(300); beginPin(); return; }
    summarise();
  }

  void summarise() {
    int count[4] = {0, 0, 0, 0};
    int unanswered = 0;
    for (int i = 0; i < 4; i++) {
      if (answer_[i] >= 0) count[answer_[i]]++; else unanswered++;
    }
    // Exactly one pin felt nothing (or was skipped) and exactly one zone is still free: the free
    // zone can only be on that pin. Say so, but it still has to be confirmed before saving.
    int freeZone = -1, freeCount = 0;
    for (int z = 0; z < 4; z++) if (count[z] == 0) { freeZone = z; freeCount++; }
    bool duplicates = false;
    for (int z = 0; z < 4; z++) if (count[z] > 1) duplicates = true;
    if (!duplicates && unanswered == 1 && freeCount == 1) {
      for (int i = 0; i < 4; i++) if (answer_[i] < 0) {
        answer_[i] = freeZone;
        Serial.printf("GPIO %d gave no answer; it must be %c, the only zone left. Its motor may not be working: check its wiring.\n",
                      MOTOR_GPIOS[i], ZONE_LETTER[freeZone]);
      }
      count[freeZone] = 1; unanswered = 0;
    }
    Serial.println();
    Serial.println("=== Result ===");
    for (int z = 0; z < 4; z++) {
      int gpio = -1;
      for (int i = 0; i < 4; i++) if (answer_[i] == z) gpio = MOTOR_GPIOS[i];
      result_[z] = gpio;
      if (gpio >= 0) Serial.printf("  %c (%s) = GPIO %d%s\n", ZONE_LETTER[z], ZONE_WORD[z], gpio, count[z] > 1 ? "  <- more than one pin answered this" : "");
      else Serial.printf("  %c (%s) = not found\n", ZONE_LETTER[z], ZONE_WORD[z]);
    }
    if (duplicates || unanswered > 0 || !MotorMap::valid(result_)) {
      Serial.println("This is not a complete map (a zone is missing or was given twice).");
      Serial.println("Type redo to try again, or cancel to keep the old map.");
      state_ = CONFIRMING;   // only redo / cancel make sense; save is refused below
      incomplete_ = true;
      return;
    }
    incomplete_ = false;
    state_ = CONFIRMING;
    Serial.println("Type save to keep this map (then each zone taps once to check), or redo.");
  }

  void save() {
    if (incomplete_) { Serial.println("Cannot save an incomplete map. Type redo or cancel."); return; }
    state_ = IDLE;
    finished_ = true;   // the sketch saves result() to flash and plays the check
  }

  void setBuzz(bool on) {
    if (on == buzzing_) return;
    buzzing_ = on;
    write_(MOTOR_GPIOS[index_], on ? 255 : 0);
  }

  void stopBuzz() {
    for (int i = 0; i < 4; i++) write_(MOTOR_GPIOS[i], 0);
    buzzing_ = false;
  }

  void (*write_)(int, uint8_t) = nullptr;
  State state_ = IDLE;
  int index_ = 0;
  int answer_[4] = {-1, -1, -1, -1};   // per GPIO (in MOTOR_GPIOS order): zone 0-3, -1 unanswered, -2 felt nothing
  int result_[4] = {-1, -1, -1, -1};   // per zone: GPIO
  uint8_t buzzesLeft_ = 0;
  uint32_t cycleStart_ = 0;
  bool buzzing_ = false, finished_ = false, incomplete_ = false;
};
