// Minimal host stand-ins for the Arduino APIs motor_map.h uses, so its logic runs under pytest.
#pragma once
#include <cctype>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <map>
#include <string>
#include <vector>

class String {
 public:
  String(const char* s = "") : s_(s) {}
  String(const std::string& s) : s_(s) {}
  void trim() {
    size_t a = s_.find_first_not_of(" \t\r\n"), b = s_.find_last_not_of(" \t\r\n");
    s_ = a == std::string::npos ? "" : s_.substr(a, b - a + 1);
  }
  void toLowerCase() { for (auto& c : s_) c = (char)std::tolower((unsigned char)c); }
  unsigned length() const { return (unsigned)s_.size(); }
  char operator[](unsigned i) const { return s_[i]; }
  bool operator==(const char* o) const { return s_ == o; }
  const char* c_str() const { return s_.c_str(); }
 private:
  std::string s_;
};

struct FakeSerial {
  std::string out;
  void println(const char* s = "") { out += s; out += "\n"; }
  void printf(const char* fmt, ...) {
    char buf[512]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap); out += buf;
  }
};
inline FakeSerial Serial;
inline uint32_t fakeMillis = 0;
inline uint32_t millis() { return fakeMillis; }
inline void delay(uint32_t ms) { fakeMillis += ms; }
