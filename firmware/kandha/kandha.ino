/*
 * Kandha Stole firmware (protocol v1) for an ESP32-S3, Arduino-ESP32 core 3.x.
 * -----------------------------------------------------------------------------
 * Four motor zones (L, R, B, F) driven by MOSFET PWM, four textile touch pads, a LiPo gauge,
 * and one Bluetooth LE service (docs/kandha/PROTOCOL.md). The tap language comes from
 * patterns.h, generated from browser/sanket/kandha-patterns.json: the app, the on-screen
 * virtual stole and this firmware play the same steps.
 *
 * Status: written for the prototype and compiled in CI (.github/workflows/firmware.yml). It has
 * NOT been run on hardware yet; see firmware/kandha/README.md before flashing.
 */
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <esp_mac.h>

#include "config.h"
#include "patterns.h"
#include "pattern_engine.h"
#include "touch_pads.h"

// ---------------------------------------------------------------------------- state
static PatternEngine engine;
static TouchPads pads;
static KandhaConfig config;
static BLEServer* server = nullptr;
static BLECharacteristic* inputChar = nullptr;
static BLECharacteristic* statusChar = nullptr;
static BLECharacteristic* configChar = nullptr;
static bool connected = false;
static uint8_t batteryPercent = 100;
static bool charging = false;
static uint32_t lastStatusAt = 0, lastBatteryAt = 0, lastTouchAt = 0;
static bool statusDirty = true;
static uint8_t publishedFlags = 0;   // the STATUS flags last published; any change is notified

// ---------------------------------------------------------------------------- link mailbox
// The BLE callbacks run on the Bluetooth stack's task and loop() on its own task. The callbacks
// only post what arrived here; loop() takes it out in order and applies it, so the pattern
// engine, the config and the link state are only ever changed by loop() and a disconnect can
// never interleave with a tick and leave a motor running.
static portMUX_TYPE linkLock = portMUX_INITIALIZER_UNLOCKED;

struct LinkMailbox {
  enum { LINK_HAPTIC = 1, LINK_PATTERNS, LINK_CONFIG };
  enum { FLAG_STOP = 1, FLAG_NEW_SEQ = 2 };   // left by a write that was folded into this one
  // Connects and disconnects are counted, not queued, so a busy loop() can never miss one.
  struct Links { uint32_t connects = 0, disconnects = 0; };
  // Each write carries the counts at its arrival, so loop() acts on the link in the right order.
  struct Event { uint8_t kind, flags; uint16_t length; Links links; uint8_t data[2 + 5 * KANDHA_MAX_PATTERN_STEPS]; };
  static const int QUEUE_LENGTH = 16;

  // Whether a write has the length its characteristic needs; loop() rejects any other.
  static bool wellFormed(const Event& e) {
    switch (e.kind) {
      case LINK_HAPTIC: return e.length == 5;
      case LINK_CONFIG: return e.length == 7;
      case LINK_PATTERNS: return e.length >= 2 && e.data[1] >= 1 && e.data[1] <= KANDHA_MAX_PATTERN_STEPS && e.length == 2 + 5 * e.data[1];
    }
    return false;
  }

  // From the BLE task.
  void noteConnect() { portENTER_CRITICAL(&linkLock); links.connects++; portEXIT_CRITICAL(&linkLock); }
  void noteDisconnect() { portENTER_CRITICAL(&linkLock); links.disconnects++; portEXIT_CRITICAL(&linkLock); }

  void post(uint8_t kind, const uint8_t* data, size_t n) {
    portENTER_CRITICAL(&linkLock);
    Event& e = at(count++);
    e.kind = kind;
    e.flags = 0;
    e.links = links;
    e.length = n > 0xFFFF ? 0xFFFF : (uint16_t)n;   // the real length, so loop() can reject a bad write
    if (n) memcpy(e.data, data, n < sizeof(e.data) ? n : sizeof(e.data));
    if (count > QUEUE_LENGTH) makeRoom();
    portEXIT_CRITICAL(&linkLock);
  }

  // From loop(): the next write, or false and the link counts once there is none. Both come
  // from one critical section, so every later write carries these counts or newer ones.
  bool take(Event& out, Links& now) {
    portENTER_CRITICAL(&linkLock);
    bool got = count > 0;
    if (got) { out = events[head]; head = (head + 1) % SLOTS; count--; }
    else now = links;
    portEXIT_CRITICAL(&linkLock);
    return got;
  }

  // How many writes were left out since the last call: with nothing lost (malformed, or
  // folded into a later write), and lost.
  void takeBacklog(uint32_t& harmlessOut, uint32_t& lostOut) {
    portENTER_CRITICAL(&linkLock);
    harmlessOut = harmless; lostOut = lost;
    harmless = lost = 0;
    portEXIT_CRITICAL(&linkLock);
  }

 private:
  static const int SLOTS = QUEUE_LENGTH + 1;   // room for the write that overflows the queue
  Event& at(int k) { return events[(head + k) % SLOTS]; }

  // loop() is QUEUE_LENGTH writes behind, so one write has to go. First the oldest that would
  // change nothing: a malformed write (loop() would reject it), a HAPTIC with another behind it
  // (a new command replaces the old), or a CONFIG with another CONFIG behind it and no HAPTIC
  // between (the later one holds every setting; a mute in the earlier one still stops the
  // motors). Only then the oldest HAPTIC, and last the oldest PATTERNS upload, so the link
  // state and the settings the app wrote are never lost.
  void makeRoom() {
    for (int k = 0; k < count; k++) {
      Event& e = at(k);
      if (!wellFormed(e)) { remove(k, true); return; }
      if (e.kind == LINK_PATTERNS) continue;
      for (int j = k + 1; j < count; j++) {
        Event& later = at(j);
        if (e.kind == LINK_CONFIG && later.kind == LINK_HAPTIC) break;   // that command needs this CONFIG
        if (later.kind != e.kind || !wellFormed(later)) continue;
        if (e.kind == LINK_HAPTIC) {
          // After e the duplicate filter would hold e's seq: tell loop() when that is not later's.
          if ((e.flags & FLAG_NEW_SEQ) || later.data[0] != e.data[0]) later.flags |= FLAG_NEW_SEQ;
        } else if ((e.flags & FLAG_STOP) || e.data[4]) {
          later.flags |= FLAG_STOP;
        }
        remove(k, true);
        return;
      }
    }
    for (int k = 0; k < count; k++) if (at(k).kind == LINK_HAPTIC) { remove(k, false); return; }
    for (int k = 0; k < count; k++) if (at(k).kind == LINK_PATTERNS) { remove(k, false); return; }
    remove(0, false);
  }

  // Removes the k-th oldest write; the others keep their order.
  void remove(int k, bool nothingLost) {
    for (; k > 0; k--) at(k) = at(k - 1);
    head = (head + 1) % SLOTS;
    count--;
    if (nothingLost) harmless++; else lost++;
  }

  Event events[SLOTS];
  int head = 0, count = 0;
  Links links;
  uint32_t harmless = 0, lost = 0;
};
static LinkMailbox mailbox;

// ---------------------------------------------------------------------------- battery
// A simple 3.7 V LiPo open-circuit curve; the TP4056 cuts off at 4.2 V, protection at ~3.0 V.
static uint8_t batteryFromMillivolts(uint32_t mv) {
  static const uint16_t volts[] = {3000, 3300, 3500, 3600, 3700, 3800, 3900, 4000, 4100, 4200};
  static const uint8_t pct[] = {0, 5, 15, 30, 45, 60, 75, 85, 95, 100};
  if (mv <= volts[0]) return 0;
  for (int i = 1; i < 10; i++) {
    if (mv <= volts[i]) return pct[i - 1] + (uint8_t)(((mv - volts[i - 1]) * (pct[i] - pct[i - 1])) / (volts[i] - volts[i - 1]));
  }
  return 100;
}

static void sampleBattery() {
  uint32_t mv = analogReadMilliVolts(PIN_BATTERY_SENSE) * 2;   // 100 k / 100 k divider
  uint8_t pct = batteryFromMillivolts(mv);
  bool chg = digitalRead(PIN_CHARGING_SENSE) == LOW;
  if (pct != batteryPercent || chg != charging) statusDirty = true;
  batteryPercent = pct;
  charging = chg;
}

static uint8_t statusFlags() {
  uint8_t flags = 0;
  if (config.mute) flags |= 1;
  if (config.mirror) flags |= 2;
  if (config.testMode) flags |= 4;
  if (batteryPercent <= KANDHA_LOW_BATTERY_PERCENT && !charging) flags |= 8;
  if (engine.playing()) flags |= 16;
  if (pads.calibrated()) flags |= 32;
  return flags;
}

static void publishStatus(bool notify) {
  publishedFlags = statusFlags();
  uint8_t payload[5] = {batteryPercent, (uint8_t)(charging ? 1 : 0), KANDHA_FW_MAJOR, KANDHA_FW_MINOR, publishedFlags};
  if (statusChar) {
    statusChar->setValue(payload, 5);
    if (notify && connected) statusChar->notify();
  }
  statusDirty = false;
  lastStatusAt = millis();
}

static void publishConfig() {
  uint8_t payload[7] = {config.scale[0], config.scale[1], config.scale[2], config.scale[3], config.mute, config.mirror, config.testMode};
  if (configChar) configChar->setValue(payload, 7);
}

// ---------------------------------------------------------------------------- inputs
static void sendInput(uint8_t pad, uint8_t gesture) {
  uint8_t payload[2] = {pad, gesture};
  if (inputChar && connected) {
    inputChar->setValue(payload, 2);
    inputChar->notify();
  }
  Serial.printf("INPUT pad=%u gesture=%u\n", pad, gesture);
}

static void onGesture(uint8_t pad, uint8_t gesture) { sendInput(pad, gesture); }

// ---------------------------------------------------------------------------- BLE callbacks
// These run on the Bluetooth stack's task: they only post to the mailbox (see serviceLink).
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { mailbox.noteConnect(); }
  void onDisconnect(BLEServer* s) override {
    mailbox.noteDisconnect();
    s->startAdvertising();
  }
};

class HapticCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override { mailbox.post(LinkMailbox::LINK_HAPTIC, c->getData(), c->getLength()); }
};

class PatternsCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override { mailbox.post(LinkMailbox::LINK_PATTERNS, c->getData(), c->getLength()); }
};

class ConfigCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override { mailbox.post(LinkMailbox::LINK_CONFIG, c->getData(), c->getLength()); }
};

static LinkMailbox::Links appliedLinks;   // the connects and disconnects loop() has acted on

// A disconnect stops every motor. A new connection starts with a fresh duplicate filter: the
// app numbers its commands from 1 again after a restart.
static void applyLinks(const LinkMailbox::Links& links, uint32_t now) {
  bool connects = links.connects != appliedLinks.connects, disconnects = links.disconnects != appliedLinks.disconnects;
  appliedLinks = links;
  connected = links.connects != links.disconnects;
  if (disconnects) engine.stop(now);
  if (connects) { engine.resetSeq(); statusDirty = true; }
  if (connects && !connected) Serial.println("BLE connected");
  if (disconnects) Serial.println("BLE disconnected; advertising again");
  if (connects && connected) Serial.println("BLE connected");
}

// Applies what the BLE callbacks posted, in the order it arrived. Runs on loop()'s task only.
static void serviceLink(uint32_t now) {
  LinkMailbox::Event e;
  LinkMailbox::Links links;
  while (mailbox.take(e, links)) {
    applyLinks(e.links, now);
    const uint8_t* data = e.data;
    size_t n = e.length;
    bool ok = LinkMailbox::wellFormed(e);
    switch (e.kind) {
      case LinkMailbox::LINK_HAPTIC: {
        if (!ok) { Serial.printf("HAPTIC: bad length %u\n", (unsigned)n); break; }
        if (e.flags & LinkMailbox::FLAG_NEW_SEQ) engine.resetSeq();   // see LinkMailbox::makeRoom
        ok = engine.play(data[0], data[1], data[2], data[3], data[4], config, now);
        Serial.printf("HAPTIC seq=%u zones=%u pattern=%u intensity=%u repeat=%u -> %s\n", data[0], data[1], data[2], data[3], data[4], ok ? "play" : "ignored");
        if (config.testMode) sendInput(0, data[0]);   // bench echo
        break;
      }
      case LinkMailbox::LINK_PATTERNS: {
        if (!ok) { Serial.println("PATTERNS: malformed"); break; }
        ok = engine.storeCustom(data[0], data + 2, data[1]);
        Serial.printf("PATTERNS id=%u steps=%u -> %s\n", data[0], data[1], ok ? "stored" : "rejected");
        break;
      }
      case LinkMailbox::LINK_CONFIG:
        if (!ok) { Serial.println("CONFIG: bad length"); break; }
        if (e.flags & LinkMailbox::FLAG_STOP) engine.stop(now);   // a mute folded into this CONFIG
        for (int i = 0; i < 4; i++) config.scale[i] = data[i];
        config.mute = data[4] ? 1 : 0;
        config.mirror = data[5] ? 1 : 0;
        config.testMode = data[6] ? 1 : 0;
        if (config.mute) engine.stop(now);
        // No publishConfig(): the characteristic already holds the bytes the app wrote, and
        // rewriting it here could race the stack storing the app's next write.
        statusDirty = true;
        Serial.printf("CONFIG scales=%u,%u,%u,%u mute=%u mirror=%u test=%u\n", data[0], data[1], data[2], data[3], data[4], data[5], data[6]);
        break;
    }
  }
  applyLinks(links, now);
  uint32_t harmless, lost;
  mailbox.takeBacklog(harmless, lost);
  if (harmless || lost) Serial.printf("BLE: loop() fell behind: %lu writes left out with nothing lost, %lu lost\n", (unsigned long)harmless, (unsigned long)lost);
}

static String deviceName() {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_BT);
  char suffix[5];
  snprintf(suffix, sizeof(suffix), "%02X%02X", mac[4], mac[5]);
  return String(KANDHA_NAME_PREFIX) + suffix;
}

static void setupBle() {
  String name = deviceName();
  BLEDevice::init(name.c_str());
  BLEDevice::setMTU(BLE_MTU);
  // LE Secure Connections, "Just Works" bonding: no display on the stole. The app does not rely on it.
  BLESecurity* security = new BLESecurity();
  security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
  security->setCapability(ESP_IO_CAP_NONE);
  security->setInitEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);

  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService* service = server->createService(BLEUUID(KANDHA_SERVICE_UUID));

  BLECharacteristic* haptic = service->createCharacteristic(KANDHA_CHAR_HAPTIC_UUID, BLECharacteristic::PROPERTY_WRITE_NR);
  haptic->setCallbacks(new HapticCallbacks());
  BLECharacteristic* patterns = service->createCharacteristic(KANDHA_CHAR_PATTERNS_UUID, BLECharacteristic::PROPERTY_WRITE);
  patterns->setCallbacks(new PatternsCallbacks());
  inputChar = service->createCharacteristic(KANDHA_CHAR_INPUT_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  inputChar->addDescriptor(new BLE2902());
  statusChar = service->createCharacteristic(KANDHA_CHAR_STATUS_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  statusChar->addDescriptor(new BLE2902());
  configChar = service->createCharacteristic(KANDHA_CHAR_CONFIG_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE);
  configChar->setCallbacks(new ConfigCallbacks());
  publishConfig();
  publishStatus(false);
  service->start();

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(BLEUUID(KANDHA_SERVICE_UUID));
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);   // 7.5 ms connection interval hint, for low tap latency
  advertising->setMaxPreferred(0x18);   // 30 ms
  BLEDevice::startAdvertising();
  Serial.printf("Advertising as %s\n", name.c_str());
}

// ---------------------------------------------------------------------------- serial console
static int zoneMaskFromText(const String& text) {
  int mask = 0;
  for (unsigned i = 0; i < text.length(); i++) {
    switch (toupper(text[i])) {
      case 'L': mask |= KANDHA_ZONE_L; break;
      case 'R': mask |= KANDHA_ZONE_R; break;
      case 'B': mask |= KANDHA_ZONE_B; break;
      case 'F': mask |= KANDHA_ZONE_F; break;
      default: break;
    }
  }
  return mask;
}

static int patternIdFromText(const String& text) {
  for (int i = 0; i < KANDHA_PATTERN_COUNT; i++) if (text.equalsIgnoreCase(KANDHA_PATTERNS[i].key)) return KANDHA_PATTERNS[i].id;
  return text.toInt();
}

static void printHelp() {
  Serial.println("Kandha Stole console. Commands:");
  Serial.println("  help                          this list");
  Serial.println("  status                        battery, connection, config, flags");
  Serial.println("  patterns                      the built-in tap language");
  Serial.println("  play <pattern> [zones] [intensity] [repeat]   e.g. play seat_tap L 230 1, play rise F");
  Serial.println("  stop                          stop the motors");
  Serial.println("  test                          two taps on every zone in turn");
  Serial.println("  pads                          raw touch values and baselines");
  Serial.println("  cal                           recalibrate the touch pads (hands off)");
  Serial.println("  pad <L|R|B|Q> <tap|double|long>   send an INPUT as if a pad were pressed");
  Serial.println("  mirror 0|1 · mute 0|1 · scale <L|R|B|F> <0-255> · testmode 0|1");
}

static uint8_t consoleSeq = 200;

static void handleCommand(String line) {
  line.trim();
  if (!line.length()) return;
  String parts[5]; int count = 0;
  int start = 0;
  while (count < 5) {
    int space = line.indexOf(' ', start);
    if (space < 0) { parts[count++] = line.substring(start); break; }
    parts[count++] = line.substring(start, space);
    start = space + 1;
    while (start < (int)line.length() && line[start] == ' ') start++;
  }
  String cmd = parts[0]; cmd.toLowerCase();
  if (cmd == "help") printHelp();
  else if (cmd == "status") {
    Serial.printf("battery=%u%% charging=%u connected=%u playing=%u flags=0x%02x fw=%u.%u table=%s\n", batteryPercent, charging, connected, engine.playing(), statusFlags(), KANDHA_FW_MAJOR, KANDHA_FW_MINOR, KANDHA_TABLE_DIGEST);
    Serial.printf("config scales=%u,%u,%u,%u mute=%u mirror=%u test=%u\n", config.scale[0], config.scale[1], config.scale[2], config.scale[3], config.mute, config.mirror, config.testMode);
  } else if (cmd == "patterns") {
    for (int i = 0; i < KANDHA_PATTERN_COUNT; i++) {
      const KandhaPattern& p = KANDHA_PATTERNS[i];
      uint32_t ms = 0; for (int k = 0; k < p.count; k++) ms += p.steps[k].on_ms + p.steps[k].off_ms;
      Serial.printf("  %2u %-15s zones=%u intensity=%u steps=%u %lu ms\n", p.id, p.key, p.zones, p.intensity, p.count, (unsigned long)(ms * p.repeat));
    }
  } else if (cmd == "play") {
    int id = patternIdFromText(parts[1]);
    int mask = count > 2 ? zoneMaskFromText(parts[2]) : 0;
    uint8_t intensity = count > 3 ? (uint8_t)parts[3].toInt() : 0, repeat = count > 4 ? (uint8_t)parts[4].toInt() : 1;
    for (int i = 0; i < KANDHA_PATTERN_COUNT; i++) if (KANDHA_PATTERNS[i].id == id) { if (!mask) mask = KANDHA_PATTERNS[i].zones ? KANDHA_PATTERNS[i].zones : KANDHA_ZONE_F; if (!intensity) intensity = KANDHA_PATTERNS[i].intensity; }
    if (!intensity) intensity = 200;
    bool ok = engine.play(consoleSeq++, (uint8_t)mask, (uint8_t)id, intensity, repeat, config, millis());
    Serial.printf("play id=%d zones=%d intensity=%u -> %s\n", id, mask, intensity, ok ? "ok" : "unknown pattern");
  } else if (cmd == "stop") { engine.stop(millis()); Serial.println("stopped"); }
  else if (cmd == "test") {
    const uint8_t zones[4] = {KANDHA_ZONE_L, KANDHA_ZONE_R, KANDHA_ZONE_B, KANDHA_ZONE_F};
    for (int i = 0; i < 4; i++) {
      engine.play(consoleSeq++, zones[i], 11, 230, 1, config, millis());
      uint32_t until = millis() + 600;
      while (millis() < until) { serviceLink(millis()); engine.tick(millis()); delay(1); }   // the link keeps working
    }
    Serial.println("test done");
  } else if (cmd == "pads") {
    for (int i = 0; i < 4; i++) Serial.printf("  pad %c raw=%lu baseline=%lu\n", "LRBQ"[i], (unsigned long)pads.raw(i), (unsigned long)pads.baseline(i));
  } else if (cmd == "cal") { pads.calibrate(); Serial.println("pads calibrated"); statusDirty = true; }
  else if (cmd == "pad") {
    String which = parts[1]; which.toUpperCase();
    uint8_t pad = which == "L" ? KANDHA_PAD_L : which == "R" ? KANDHA_PAD_R : which == "B" ? KANDHA_PAD_B : which == "Q" ? KANDHA_PAD_Q : 0;
    String g = parts[2]; g.toLowerCase();
    uint8_t gesture = g == "double" ? KANDHA_GESTURE_DOUBLE : g == "long" ? KANDHA_GESTURE_LONG : KANDHA_GESTURE_TAP;
    if (pad) sendInput(pad, gesture); else Serial.println("pad L|R|B|Q tap|double|long");
  } else if (cmd == "mirror") { config.mirror = parts[1].toInt() ? 1 : 0; publishConfig(); statusDirty = true; Serial.printf("mirror=%u\n", config.mirror); }
  else if (cmd == "mute") { config.mute = parts[1].toInt() ? 1 : 0; if (config.mute) engine.stop(millis()); publishConfig(); statusDirty = true; Serial.printf("mute=%u\n", config.mute); }
  else if (cmd == "testmode") { config.testMode = parts[1].toInt() ? 1 : 0; publishConfig(); statusDirty = true; Serial.printf("testmode=%u\n", config.testMode); }
  else if (cmd == "scale") {
    int mask = zoneMaskFromText(parts[1]); int value = parts[2].toInt();
    for (int i = 0; i < 4; i++) if (mask & (1 << i)) config.scale[i] = (uint8_t)constrain(value, 0, 255);
    publishConfig(); Serial.printf("scales=%u,%u,%u,%u\n", config.scale[0], config.scale[1], config.scale[2], config.scale[3]);
  } else Serial.println("unknown command; type help");
}

static String consoleLine;

static void pollConsole() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') { handleCommand(consoleLine); consoleLine = ""; }
    else if (consoleLine.length() < 120) consoleLine += c;
  }
}

// ---------------------------------------------------------------------------- Arduino
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("Kandha Stole firmware %u.%u, pattern table %s\n", KANDHA_FW_MAJOR, KANDHA_FW_MINOR, KANDHA_TABLE_DIGEST);
  pinMode(PIN_CHARGING_SENSE, INPUT_PULLUP);
  if (PIN_STATUS_LED >= 0) { pinMode(PIN_STATUS_LED, OUTPUT); digitalWrite(PIN_STATUS_LED, LOW); }
  analogReadResolution(12);
  engine.begin();
  pads.begin(onGesture);
  sampleBattery();
  setupBle();
  printHelp();
}

void loop() {
  uint32_t now = millis();
  serviceLink(now);
  engine.tick(now);
  if (now - lastTouchAt >= TOUCH_POLL_MS) { lastTouchAt = now; pads.poll(now); }
  if (now - lastBatteryAt >= BATTERY_SAMPLE_MS) { lastBatteryAt = now; sampleBattery(); }
  // STATUS is notified on change: also when a pattern ends on its own and bit4 clears.
  if (statusFlags() != publishedFlags) statusDirty = true;
  if (statusDirty || now - lastStatusAt >= STATUS_PERIOD_MS) publishStatus(true);
  if (PIN_STATUS_LED >= 0) digitalWrite(PIN_STATUS_LED, connected ? (engine.playing() ? HIGH : ((now / 1000) % 2 == 0 ? HIGH : LOW)) : ((now / 250) % 4 == 0 ? HIGH : LOW));
  pollConsole();
  delay(1);
}
