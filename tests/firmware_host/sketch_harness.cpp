// Runs the real firmware/kandha/kandha.ino on the host against the Arduino and BLE stand-ins in
// this folder. The harness plays the Bluetooth stack (it calls the BLE callbacks the way the
// stack's own task does) and the Arduino core (it calls setup() and loop()).
// tests/test_kandha_firmware_host.py writes a script to stdin and reads stdout:
//   PWM <ms> <pin> <duty>              every ledcWrite (unless "quiet")
//   NOTIFY <ms> <input|status> <hex>   every notification sent to the app
//   STATE <ms> <playing> <connected> <duty L> <duty R> <duty B> <duty F>
//   SERIAL <text>                      the serial console
//   RACE <cycles> stuck=<n>            see "race"
//   INTERLEAVE held=<n> stuck=<n> of <trials>   see "interleave"
//
// Commands:
//   setup                     setup() with the clock at 0
//   connect | disconnect      the server callbacks, as the Bluetooth task calls them
//   write <haptic|patterns|config> <hex bytes>   a write from the app, as the Bluetooth task delivers it
//   loop <n>                  n passes of loop() (each ends with delay(1))
//   until <ms>                loop() until the clock reaches <ms>
//   state | quiet | echo <text>
//   race <cycles>             loop() on its own thread while this thread connects, writes
//                             HAPTIC and CONFIG and disconnects, as the two tasks do on the
//                             ESP32; counts the times loop() sees the motors energised with no
//                             pattern playing for several passes in a row.
//   interleave <writes>       for each of loop()'s first <writes> motor writes that switch a
//                             motor on: holds loop() (on its own thread) inside that write, as
//                             if the Bluetooth task preempted it there, disconnects or mutes
//                             from this thread, lets loop() go on, and checks that every motor
//                             ends up off. Deterministic, unlike "race".
#include <Arduino.h>

#include <condition_variable>
#include <iostream>
#include <sstream>
#include <vector>

#include "kandha.ino"

static bool quiet = false;

static void onPwm(uint32_t t, int pin, uint32_t duty) {
  if (!quiet) printf("PWM %u %d %u\n", t, pin, duty);
}

static void onNotify(BLECharacteristic* c) {
  if (quiet) return;
  const char* name = c->uuid == KANDHA_CHAR_INPUT_UUID ? "input" : c->uuid == KANDHA_CHAR_STATUS_UUID ? "status" : "other";
  printf("NOTIFY %u %s ", millis(), name);
  for (uint8_t b : c->value) printf("%02x", b);
  printf("\n");
}

static BLECharacteristic* characteristic(const std::string& name) {
  const char* uuid = name == "haptic" ? KANDHA_CHAR_HAPTIC_UUID : name == "patterns" ? KANDHA_CHAR_PATTERNS_UUID : KANDHA_CHAR_CONFIG_UUID;
  for (BLECharacteristic* c : host_characteristics) if (c->uuid == uuid) return c;
  return nullptr;
}

// What the Bluetooth stack does with a write: store the value, then call onWrite on its own task.
static void deliverWrite(const std::string& name, std::vector<uint8_t> bytes) {
  BLECharacteristic* c = characteristic(name);
  c->setValue(bytes.data(), bytes.size());
  if (c->callbacks) c->callbacks->onWrite(c, nullptr);
}

static std::vector<uint8_t> parseHex(const std::string& hex) {
  std::vector<uint8_t> out;
  for (size_t i = 0; i + 1 < hex.size(); i += 2) out.push_back((uint8_t)strtoul(hex.substr(i, 2).c_str(), nullptr, 16));
  return out;
}

static bool motorsOn() {
  const int pins[4] = {PIN_MOTOR_L, PIN_MOTOR_R, PIN_MOTOR_B, PIN_MOTOR_F};
  for (int pin : pins) if (host_duty[pin]) return true;
  return false;
}

static void race(int cycles) {
  quiet = true;
  std::atomic<bool> done{false};
  std::atomic<int> stuck{0};
  std::thread looper([&] {
    int run = 0;
    while (!done) {
      loop();
      // Read on the loop task itself, after a whole pass: energised motors with nothing playing
      // for three passes in a row is the stuck state a race leaves behind.
      run = (!engine.playing() && motorsOn()) ? run + 1 : 0;
      if (run == 3) stuck++;
    }
  });
  const uint8_t patterns[3] = {1, 3, 9};   // seat_tap, drop, low_battery
  uint32_t spin = 12345;
  for (int i = 0; i < cycles; i++) {
    host_server->callbacks->onConnect(host_server, nullptr);
    deliverWrite("haptic", {(uint8_t)i, 0x0F, patterns[i % 3], 230, 1});
    spin = spin * 1103515245u + 12345u;
    for (volatile uint32_t k = 0; k < (spin >> 20) % 2000; k++) {}
    if (i % 5 == 4) {
      deliverWrite("config", {255, 255, 255, 255, 1, 0, 0});   // mute
      deliverWrite("config", {255, 255, 255, 255, 0, 0, 0});
    }
    host_server->callbacks->onDisconnect(host_server, nullptr);
  }
  done = true;
  looper.join();
  for (int i = 0; i < 20; i++) loop();
  quiet = false;
  printf("RACE %d stuck=%d\n", cycles, stuck.load() + ((!engine.playing() && motorsOn()) ? 1 : 0));
}

// "interleave": loop() stops inside its holdAt-th ledcWrite that switches a motor on.
static std::mutex holdLock;
static std::condition_variable holdChanged;
static std::thread::id looperId;
static bool looperGo = false, held = false, released = false;
static int holdAt = 0;

static void onPwmHold(uint32_t, int, uint32_t duty) {
  std::unique_lock<std::mutex> g(holdLock);
  if (duty == 0 || std::this_thread::get_id() != looperId || holdAt == 0 || --holdAt > 0) return;
  held = true;
  holdChanged.notify_all();
  holdChanged.wait(g, [] { return released; });
}

// One trial: true when a motor is left running.
static bool interleaveOnce(int write, bool mute, int& heldCount) {
  host_server->callbacks->onConnect(host_server, nullptr);
  deliverWrite("haptic", {(uint8_t)write, 0x0F, 9, 170, 1});   // low_battery on every zone
  std::atomic<bool> done{false};
  std::atomic<int> passes{0};
  std::thread looper([&] {
    {
      std::unique_lock<std::mutex> g(holdLock);
      holdChanged.wait(g, [] { return looperGo; });
    }
    while (!done) { loop(); passes++; }
  });
  bool wasHeld;
  {
    std::unique_lock<std::mutex> g(holdLock);
    looperId = looper.get_id();
    holdAt = write; held = false; released = false; looperGo = true;
    holdChanged.notify_all();
    wasHeld = holdChanged.wait_for(g, std::chrono::seconds(5), [] { return held; });
  }
  // The Bluetooth task, while loop() is inside the write.
  if (mute) deliverWrite("config", {255, 255, 255, 255, 1, 0, 0});
  else host_server->callbacks->onDisconnect(host_server, nullptr);
  int from = passes;
  {
    std::unique_lock<std::mutex> g(holdLock);
    released = true; holdAt = 0;
    holdChanged.notify_all();
  }
  while (passes < from + 30) std::this_thread::yield();
  done = true;
  looper.join();
  {
    std::unique_lock<std::mutex> g(holdLock);
    looperGo = false; looperId = std::thread::id();
  }
  bool stuck = motorsOn();
  if (wasHeld) heldCount++;
  // Back to a clean start: unmuted, disconnected, every motor off.
  if (mute) {
    deliverWrite("config", {255, 255, 255, 255, 0, 0, 0});
    host_server->callbacks->onDisconnect(host_server, nullptr);
  }
  for (int i = 0; i < 3; i++) loop();
  return stuck;
}

static void interleave(int writes) {
  quiet = true;
  host_on_pwm = onPwmHold;
  int heldCount = 0, stuck = 0, trials = 0;
  for (int mute = 0; mute < 2; mute++) {
    for (int w = 1; w <= writes; w++, trials++) stuck += interleaveOnce(w, mute, heldCount) ? 1 : 0;
  }
  host_on_pwm = onPwm;
  quiet = false;
  printf("INTERLEAVE held=%d stuck=%d of %d\n", heldCount, stuck, trials);
}

int main() {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  host_on_pwm = onPwm;
  host_on_notify = onNotify;
  host_serial_out = stdout;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    if (!(in >> cmd)) continue;
    if (cmd == "setup") {
      host_now = 0;
      setup();
    } else if (cmd == "connect") {
      host_server->callbacks->onConnect(host_server, nullptr);
    } else if (cmd == "disconnect") {
      host_server->callbacks->onDisconnect(host_server, nullptr);
    } else if (cmd == "write") {
      std::string name, hex;
      in >> name >> hex;
      deliverWrite(name, parseHex(hex));
    } else if (cmd == "loop") {
      int n = 1;
      in >> n;
      for (int i = 0; i < n; i++) loop();
    } else if (cmd == "until") {
      unsigned t;
      in >> t;
      while (millis() < t) loop();
    } else if (cmd == "state") {
      printf("STATE %u %d %d %u %u %u %u\n", millis(), engine.playing() ? 1 : 0, connected ? 1 : 0,
             host_duty[PIN_MOTOR_L], host_duty[PIN_MOTOR_R], host_duty[PIN_MOTOR_B], host_duty[PIN_MOTOR_F]);
    } else if (cmd == "quiet") {
      quiet = true;
    } else if (cmd == "echo") {
      printf("ECHO %s\n", line.c_str() + 5);
    } else if (cmd == "race") {
      int cycles = 100;
      in >> cycles;
      race(cycles);
    } else if (cmd == "interleave") {
      int writes = 8;
      in >> writes;
      interleave(writes);
    } else {
      fprintf(stderr, "unknown command: %s\n", line.c_str());
      return 2;
    }
  }
  return 0;
}
