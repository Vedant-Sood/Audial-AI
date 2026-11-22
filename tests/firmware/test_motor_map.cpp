// Host test of firmware/kandha/motor_map.h: the identify wizard and the saved motor map.
// Built and run by tests/test_firmware_motor_map.py with the stand-ins in this folder.
#include "Arduino.h"
#include "../../firmware/kandha/motor_map.h"

static std::map<int, int> duty;          // last duty written per GPIO
static std::vector<int> buzzedOrder;     // GPIOs in the order they first buzzed (duty 255)
static void writeDuty(int gpio, uint8_t d) {
  if (d == 255 && (buzzedOrder.empty() || buzzedOrder.back() != gpio)) buzzedOrder.push_back(gpio);
  duty[gpio] = d;
}
static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

static int onlyBuzzing() {   // the single GPIO at full duty, or -1
  int found = -1;
  for (auto& [g, d] : duty) if (d) { if (found != -1) return -2; found = g; }
  return found;
}

static void run(MotorWizard& w, uint32_t ms) { for (uint32_t i = 0; i < ms; i++) { fakeMillis++; w.tick(fakeMillis); } }

int main() {
  // 1. No saved map: defaults L=8 R=9 B=10 F=11.
  fakeFlash.clear();
  MotorMap map; map.load();
  CHECK(!map.fromFlash && map.pin[0] == 8 && map.pin[1] == 9 && map.pin[2] == 10 && map.pin[3] == 11);

  // 2. Wiring is really GPIO 8 = R, 9 = F, 10 = L, 11 = B. Each pin buzzes alone, in turn.
  MotorWizard w; w.begin(writeDuty);
  w.start(); run(w, 100);
  CHECK(w.active() && onlyBuzzing() == 8);
  w.answer("r"); run(w, 100); CHECK(onlyBuzzing() == 9);
  w.answer("F"); run(w, 100); CHECK(onlyBuzzing() == 10);
  w.answer(" l "); run(w, 100); CHECK(onlyBuzzing() == 11);
  w.answer("B");
  CHECK(onlyBuzzing() == -1);              // all quiet while asking to save
  CHECK(!w.finished());                     // not saved until confirmed
  w.answer("save");
  CHECK(!w.active() && w.finished());
  const int* r = w.result();
  CHECK(r[0] == 10 && r[1] == 8 && r[2] == 11 && r[3] == 9);   // L, R, B, F
  CHECK(map.save(r));
  MotorMap reloaded; reloaded.load();        // as after power-off
  CHECK(reloaded.fromFlash && reloaded.pin[0] == 10 && reloaded.pin[1] == 8 && reloaded.pin[2] == 11 && reloaded.pin[3] == 9);
  CHECK((buzzedOrder == std::vector<int>{8, 9, 10, 11}));

  // 3. The same zone twice is refused; redo starts over.
  w.start(); w.answer("L"); w.answer("L"); w.answer("B"); w.answer("F");
  w.answer("save"); CHECK(w.active() && !w.finished());
  w.answer("redo"); run(w, 50); CHECK(w.active() && onlyBuzzing() == 8);

  // 4. "again" rebuzzes; "back" returns to the previous pin; one dead motor is deduced but flagged.
  w.answer("R"); w.answer("back"); run(w, 50); CHECK(onlyBuzzing() == 8);
  w.answer("again"); run(w, 50); CHECK(onlyBuzzing() == 8);
  w.answer("R"); w.answer("L"); w.answer("none"); w.answer("F");
  CHECK(Serial.out.find("must be B") != std::string::npos);
  w.answer("save"); CHECK(w.finished());
  CHECK(w.result()[2] == 10);

  // 5. Buzzing stops on its own after the ask times out; cancel leaves the map unchanged.
  w.start(); run(w, 20000); CHECK(onlyBuzzing() == -1 && w.active());
  w.answer("cancel"); CHECK(!w.active() && !w.finished());
  MotorMap after; after.load(); CHECK(after.pin[0] == 10);

  // 6. A bad map is never accepted; forget goes back to the defaults.
  int bad[4] = {8, 8, 10, 11}; CHECK(!MotorMap::valid(bad));
  int notMotor[4] = {8, 9, 10, 12}; CHECK(!MotorMap::valid(notMotor));
  after.forget(); MotorMap fresh; fresh.load(); CHECK(!fresh.fromFlash && fresh.pin[0] == 8);

  std::printf(failures ? "%d FAILED\n" : "motor map OK\n", failures);
  return failures ? 1 : 0;
}
