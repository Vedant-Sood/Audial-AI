// Runs the real firmware/kandha/pattern_engine.h and touch_pads.h on the host with a simulated
// millisecond clock. tests/test_kandha_firmware_host.py writes a script to stdin, one command per
// line, and reads what the firmware did from stdout:
//   PWM <ms> <pin> <duty>         every ledcWrite
//   TICK <ms>                     every loop() pass that ticks the engine (after "trace")
//   RET <ms> <seq> <0|1>          what PatternEngine::play returned
//   GESTURE <ms> <pad> <gesture>  every gesture TouchPads reported
//   STATE <ms> <playing>
//
// Commands:
//   reset                                  fresh engine and config, clock at 0, ticks every 1 ms
//   ticks <ms> [<ms> ...]                  loop() intervals to cycle through (default 1)
//   cfg <sL> <sR> <sB> <sF> <mute> <mirror>
//   store <id> <n> (<on> <off> <level>) x n
//   play <ms> <seq> <zones> <pattern> <intensity> <repeat>   as loop() would apply a HAPTIC write
//   resetseq | stop <ms> | run <ms> | state | trace | echo <text>
//   pads_reset                             fresh TouchPads, calibrated untouched, clock at 0
//   press <pad 1-4> <from ms> <to ms>      the pad reads as touched in [from, to)
//   poll <from ms> <to ms> <every ms>      TouchPads::poll on that grid
#include <Arduino.h>

#include <iostream>
#include <sstream>
#include <vector>

#include "config.h"
#include "patterns.h"
#include "pattern_engine.h"
#include "touch_pads.h"

static PatternEngine engine;
static KandhaConfig config;
static TouchPads pads;
static std::vector<uint32_t> intervals{1};
static size_t intervalAt = 0;
static uint32_t nextTick = 0;
static bool trace = false;

struct Press { int pin; uint32_t from, to; };
static std::vector<Press> presses;

static void onPwm(uint32_t t, int pin, uint32_t duty) { printf("PWM %u %d %u\n", t, pin, duty); }
static void onGesture(uint8_t pad, uint8_t gesture) { printf("GESTURE %u %u %u\n", millis(), pad, gesture); }

static touch_value_t touchValue(uint8_t pin, uint32_t now) {
  for (const Press& p : presses) if (p.pin == pin && now >= p.from && now < p.to) return 1500;
  return 1000;
}

static void tickAt(uint32_t t) {
  host_now = t;
  engine.tick(t);
  if (trace) printf("TICK %u\n", t);
  nextTick = t + intervals[intervalAt];
  intervalAt = (intervalAt + 1) % intervals.size();
}

// loop() passes before `t`; the clock is left at `t`.
static void advanceTo(uint32_t t) {
  while (nextTick < t) tickAt(nextTick);
  host_now = t;
}

int main() {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  host_on_pwm = onPwm;
  host_touch = touchValue;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    if (!(in >> cmd)) continue;
    if (cmd == "reset") {
      host_now = 0; nextTick = 0; intervals = {1}; intervalAt = 0; trace = false;
      engine = PatternEngine(); config = KandhaConfig();
      engine.begin();
    } else if (cmd == "ticks") {
      intervals.clear();
      uint32_t ms;
      while (in >> ms) intervals.push_back(ms);
      if (intervals.empty()) intervals.push_back(1);
      intervalAt = 0;
    } else if (cmd == "cfg") {
      unsigned v[6];
      for (unsigned& x : v) in >> x;
      for (int i = 0; i < 4; i++) config.scale[i] = (uint8_t)v[i];
      config.mute = (uint8_t)v[4]; config.mirror = (uint8_t)v[5];
    } else if (cmd == "store") {
      unsigned id, n;
      in >> id >> n;
      std::vector<uint8_t> data;
      for (unsigned i = 0; i < n; i++) {
        unsigned on, off, level;
        in >> on >> off >> level;
        uint8_t step[5] = {(uint8_t)(on & 0xFF), (uint8_t)(on >> 8), (uint8_t)(off & 0xFF), (uint8_t)(off >> 8), (uint8_t)level};
        data.insert(data.end(), step, step + 5);
      }
      printf("STORE %u %d\n", id, engine.storeCustom((uint8_t)id, data.data(), n) ? 1 : 0);
    } else if (cmd == "play") {
      unsigned t, seq, zones, pattern, intensity, repeat;
      in >> t >> seq >> zones >> pattern >> intensity >> repeat;
      advanceTo(t);
      bool ok = engine.play((uint8_t)seq, (uint8_t)zones, (uint8_t)pattern, (uint8_t)intensity, (uint8_t)repeat, config, t);
      printf("RET %u %u %d\n", t, seq, ok ? 1 : 0);
      tickAt(t);
    } else if (cmd == "resetseq") {
      engine.resetSeq();
    } else if (cmd == "stop") {
      unsigned t;
      in >> t;
      advanceTo(t);
      engine.stop(t);
    } else if (cmd == "run") {
      unsigned t;
      in >> t;
      advanceTo(t + 1);
      host_now = t;
    } else if (cmd == "trace") {
      trace = true;
    } else if (cmd == "state") {
      printf("STATE %u %d\n", millis(), engine.playing() ? 1 : 0);
    } else if (cmd == "echo") {
      printf("ECHO %s\n", line.c_str() + 5);
    } else if (cmd == "pads_reset") {
      presses.clear();
      host_now = 0;
      pads = TouchPads();
      pads.begin(onGesture);
    } else if (cmd == "press") {
      unsigned pad, from, to;
      in >> pad >> from >> to;
      const int pins[4] = {PIN_PAD_L, PIN_PAD_R, PIN_PAD_B, PIN_PAD_Q};
      presses.push_back({pins[pad - 1], from, to});
    } else if (cmd == "poll") {
      unsigned from, to, every;
      in >> from >> to >> every;
      for (uint32_t t = from; t <= to; t += every) { host_now = t; pads.poll(t); }
    } else {
      fprintf(stderr, "unknown command: %s\n", line.c_str());
      return 2;
    }
  }
  return 0;
}
