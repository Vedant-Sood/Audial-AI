// Host stand-in for the parts of Arduino-ESP32 core 3.x that firmware/kandha uses, so
// tests/test_kandha_firmware_host.py can compile and run the real firmware sources with g++.
// The clock, the PWM pins and the touch pads are simulated; nothing touches real hardware.
#pragma once
#include <ctype.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <atomic>
#include <mutex>
#include <string>
#include <thread>

// ---------------------------------------------------------------------------- clock
// millis() reads a simulated clock; delay() moves it on (and lets another thread run).
inline std::atomic<uint32_t> host_now{0};
inline uint32_t millis() { return host_now.load(); }
inline void delay(uint32_t ms) {
  host_now += ms;
  std::this_thread::yield();
}

// ---------------------------------------------------------------------------- PWM (LEDC)
// Every ledcWrite is reported to host_on_pwm (time, pin, duty) when a harness sets it.
inline void (*host_on_pwm)(uint32_t t, int pin, uint32_t duty) = nullptr;
inline uint32_t host_duty[64] = {0};
inline bool ledcAttach(uint8_t pin, uint32_t, uint8_t) { host_duty[pin] = 0; return true; }
inline bool ledcWrite(uint8_t pin, uint32_t duty) {
  host_duty[pin] = duty;
  if (host_on_pwm) host_on_pwm(millis(), pin, duty);
  return true;
}

// ---------------------------------------------------------------------------- touch, GPIO, ADC
typedef uint32_t touch_value_t;   // uint32_t on the ESP32-S3
inline touch_value_t (*host_touch)(uint8_t pin, uint32_t now) = nullptr;
inline touch_value_t touchRead(uint8_t pin) { return host_touch ? host_touch(pin, millis()) : 1000; }

#define LOW 0x0
#define HIGH 0x1
#define INPUT 0x01
#define OUTPUT 0x03
#define INPUT_PULLUP 0x05
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int digitalRead(uint8_t) { return HIGH; }   // the charger's CHRG line is idle (not charging)
inline void analogReadResolution(uint8_t) {}
inline uint32_t host_battery_mv = 2050;              // at the divider: 4.1 V at the cell
inline uint32_t analogReadMilliVolts(uint8_t) { return host_battery_mv; }

#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))

// ---------------------------------------------------------------------------- FreeRTOS critical sections
// On the ESP32 a portMUX is a spinlock shared between cores; here it is a mutex, which
// ThreadSanitizer understands.
struct portMUX_TYPE { std::mutex m; };
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(mux) ((mux)->m.lock())
#define portEXIT_CRITICAL(mux) ((mux)->m.unlock())

// ---------------------------------------------------------------------------- String
class String {
 public:
  String() {}
  String(const char* s) : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  const char* c_str() const { return s_.c_str(); }
  unsigned length() const { return (unsigned)s_.size(); }
  char operator[](unsigned i) const { return i < s_.size() ? s_[i] : 0; }
  int indexOf(char c, unsigned from = 0) const { size_t p = s_.find(c, from); return p == std::string::npos ? -1 : (int)p; }
  String substring(unsigned from) const { return from >= s_.size() ? String() : String(s_.substr(from)); }
  String substring(unsigned from, unsigned to) const { return from >= s_.size() || to <= from ? String() : String(s_.substr(from, to - from)); }
  void trim() {
    size_t a = s_.find_first_not_of(" \t\r\n"), b = s_.find_last_not_of(" \t\r\n");
    s_ = a == std::string::npos ? "" : s_.substr(a, b - a + 1);
  }
  void toLowerCase() { for (auto& c : s_) c = (char)tolower((unsigned char)c); }
  void toUpperCase() { for (auto& c : s_) c = (char)toupper((unsigned char)c); }
  bool equalsIgnoreCase(const String& o) const { return strcasecmp(s_.c_str(), o.s_.c_str()) == 0; }
  long toInt() const { return atol(s_.c_str()); }
  bool operator==(const char* o) const { return s_ == o; }
  bool operator==(const String& o) const { return s_ == o.s_; }
  String& operator+=(char c) { s_ += c; return *this; }
  String& operator+=(const char* o) { s_ += o; return *this; }
  friend String operator+(const String& a, const char* b) { return String(a.s_ + b); }
  friend String operator+(const String& a, const String& b) { return String(a.s_ + b.s_); }

 private:
  std::string s_;
};

// ---------------------------------------------------------------------------- Serial
// Console output goes to host_serial_out (one "SERIAL ..." line per line printed); input is
// whatever a harness puts in host_serial_in.
inline FILE* host_serial_out = nullptr;
inline std::string host_serial_in;
inline std::mutex host_serial_lock;

class HostSerial {
 public:
  void begin(unsigned long) {}
  int available() { std::lock_guard<std::mutex> g(host_serial_lock); return (int)host_serial_in.size(); }
  int read() {
    std::lock_guard<std::mutex> g(host_serial_lock);
    if (host_serial_in.empty()) return -1;
    int c = (unsigned char)host_serial_in[0];
    host_serial_in.erase(0, 1);
    return c;
  }
  __attribute__((format(printf, 2, 3))) size_t printf(const char* fmt, ...) {
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    emit(buf);
    return n < 0 ? 0 : (size_t)n;
  }
  size_t println(const char* s = "") { std::string line = std::string(s) + "\n"; emit(line.c_str()); return line.size(); }
  size_t println(const String& s) { return println(s.c_str()); }

 private:
  void emit(const char* text) {
    if (!host_serial_out) return;
    std::lock_guard<std::mutex> g(host_serial_lock);
    for (const char* p = text; *p; p++) {
      if (at_line_start_) fputs("SERIAL ", host_serial_out);
      fputc(*p, host_serial_out);
      at_line_start_ = *p == '\n';
    }
  }
  bool at_line_start_ = true;
};
inline HostSerial Serial;
