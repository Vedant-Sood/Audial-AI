// Host stand-in for the Arduino-ESP32 3.x BLE classes kandha.ino uses (BLEDevice.h, BLEServer.h,
// BLEUtils.h, BLE2902.h). Signatures follow core 3.1.1. A harness plays the Bluetooth stack:
// it calls the server and characteristic callbacks the way the stack's own task would.
#pragma once
#include <Arduino.h>

#include <vector>

typedef int esp_err_t;
typedef uint8_t esp_ble_auth_req_t;
typedef uint8_t esp_ble_io_cap_t;
struct esp_ble_gatts_cb_param_t;
#define ESP_OK 0
#define ESP_LE_AUTH_REQ_SC_BOND 0x0D
#define ESP_IO_CAP_NONE 3
#define ESP_BLE_ENC_KEY_MASK (1 << 0)
#define ESP_BLE_ID_KEY_MASK (1 << 1)

class BLEUUID {
 public:
  BLEUUID(const char* s) : str(s) {}
  std::string str;
};

class BLECharacteristic;
class BLECharacteristicCallbacks {
 public:
  virtual ~BLECharacteristicCallbacks() {}
  virtual void onWrite(BLECharacteristic* c, esp_ble_gatts_cb_param_t*) { onWrite(c); }
  virtual void onWrite(BLECharacteristic*) {}
};

class BLEDescriptor {
 public:
  virtual ~BLEDescriptor() {}
};
class BLE2902 : public BLEDescriptor {};

// Every notify() is reported to host_on_notify when a harness sets it.
inline void (*host_on_notify)(BLECharacteristic* c) = nullptr;

class BLECharacteristic {
 public:
  static const uint32_t PROPERTY_READ = 1 << 0;
  static const uint32_t PROPERTY_WRITE = 1 << 1;
  static const uint32_t PROPERTY_NOTIFY = 1 << 2;
  static const uint32_t PROPERTY_BROADCAST = 1 << 3;
  static const uint32_t PROPERTY_INDICATE = 1 << 4;
  static const uint32_t PROPERTY_WRITE_NR = 1 << 5;

  BLECharacteristic(const char* uuid, uint32_t properties) : uuid(uuid), properties(properties) {}
  virtual ~BLECharacteristic() {}
  void addDescriptor(BLEDescriptor*) {}
  uint8_t* getData() { return value.data(); }
  size_t getLength() { return value.size(); }
  void notify(bool = true) { if (host_on_notify) host_on_notify(this); }
  void setCallbacks(BLECharacteristicCallbacks* c) { callbacks = c; }
  // Like the core, setValue holds a lock and getData does not.
  void setValue(uint8_t* data, size_t size) { std::lock_guard<std::mutex> g(lock); value.assign(data, data + size); }

  std::string uuid;
  uint32_t properties;
  std::vector<uint8_t> value;
  BLECharacteristicCallbacks* callbacks = nullptr;
  std::mutex lock;
};

inline std::vector<BLECharacteristic*> host_characteristics;

class BLEService {
 public:
  BLECharacteristic* createCharacteristic(const char* uuid, uint32_t properties) {
    BLECharacteristic* c = new BLECharacteristic(uuid, properties);
    host_characteristics.push_back(c);
    return c;
  }
  void start() {}
};

class BLEServer;
class BLEServerCallbacks {
 public:
  virtual ~BLEServerCallbacks() {}
  virtual void onConnect(BLEServer* s) { (void)s; }
  virtual void onConnect(BLEServer* s, esp_ble_gatts_cb_param_t*) { onConnect(s); }
  virtual void onDisconnect(BLEServer* s) { (void)s; }
  virtual void onDisconnect(BLEServer* s, esp_ble_gatts_cb_param_t*) { onDisconnect(s); }
};

class BLEServer {
 public:
  BLEService* createService(BLEUUID, uint32_t = 15, uint8_t = 0) { return new BLEService(); }
  BLEService* createService(const char* uuid) { return createService(BLEUUID(uuid)); }
  void setCallbacks(BLEServerCallbacks* c) { callbacks = c; }
  void startAdvertising() { advertising_starts++; }

  BLEServerCallbacks* callbacks = nullptr;
  std::atomic<int> advertising_starts{0};
};

class BLEAdvertising {
 public:
  void addServiceUUID(BLEUUID) {}
  void addServiceUUID(const char*) {}
  void setScanResponse(bool) {}
  void setMinPreferred(uint16_t) {}
  void setMaxPreferred(uint16_t) {}
};

class BLESecurity {
 public:
  void setAuthenticationMode(esp_ble_auth_req_t) {}
  void setCapability(esp_ble_io_cap_t) {}
  void setInitEncryptionKey(uint8_t) {}
};

inline BLEServer* host_server = nullptr;
inline BLEAdvertising host_advertising;

class BLEDevice {
 public:
  static void init(String) {}
  static esp_err_t setMTU(uint16_t) { return ESP_OK; }
  static BLEServer* createServer() { host_server = new BLEServer(); return host_server; }
  static BLEAdvertising* getAdvertising() { return &host_advertising; }
  static void startAdvertising() {}
};
