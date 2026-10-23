// Host stand-in for esp_mac.h: a fixed Bluetooth address.
#pragma once
#include <stdint.h>
typedef enum { ESP_MAC_WIFI_STA, ESP_MAC_WIFI_SOFTAP, ESP_MAC_BT, ESP_MAC_ETH } esp_mac_type_t;
inline int esp_read_mac(uint8_t* mac, esp_mac_type_t) {
  const uint8_t fixed[6] = {0x24, 0x6F, 0x28, 0x00, 0xAB, 0xCD};
  for (int i = 0; i < 6; i++) mac[i] = fixed[i];
  return 0;
}
