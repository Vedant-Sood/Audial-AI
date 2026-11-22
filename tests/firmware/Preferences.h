// Host stand-in for the ESP32 NVS Preferences API: an in-memory key store that outlives objects.
#pragma once
#include <cstring>
#include <map>
#include <string>
#include <vector>
inline std::map<std::string, std::vector<uint8_t>> fakeFlash;
class Preferences {
 public:
  bool begin(const char* ns, bool) { ns_ = ns; return true; }
  void end() {}
  size_t getBytesLength(const char* k) { auto it = fakeFlash.find(ns_ + "/" + k); return it == fakeFlash.end() ? 0 : it->second.size(); }
  size_t getBytes(const char* k, void* buf, size_t n) { auto& v = fakeFlash[ns_ + "/" + k]; std::memcpy(buf, v.data(), n); return n; }
  size_t putBytes(const char* k, const void* buf, size_t n) { auto p = (const uint8_t*)buf; fakeFlash[ns_ + "/" + k] = std::vector<uint8_t>(p, p + n); return n; }
  bool remove(const char* k) { return fakeFlash.erase(ns_ + "/" + k) > 0; }
 private:
  std::string ns_;
};
