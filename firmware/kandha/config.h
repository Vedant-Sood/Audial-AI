// Kandha Stole firmware: board configuration and pin map (docs/kandha/DESIGN.md section 5.3).
// Target: the bench stole's Waveshare ESP32-S3-Zero (ESP32-S3FH4R2: 4 MB flash, 2 MB PSRAM),
// Arduino-ESP32 core 3.x. Other ESP32-S3 boards work if these pins are changed to match.
#pragma once
#include <stdint.h>

#define KANDHA_FW_MAJOR 0
#define KANDHA_FW_MINOR 10

// Touch pads (ESP32-S3 touch-capable GPIOs 1-14). GPIO 3 is a strapping pin only when the
// JTAG-select eFuse is burnt, which it is not by default, so a fabric pad there is safe.
#define PIN_PAD_L 1
#define PIN_PAD_R 2
#define PIN_PAD_B 3
#define PIN_PAD_Q 4

// Motor zones, LEDC PWM. Each drives a 2N2222A NPN through 330 ohm to the base, 10 k base to
// GND, emitter to GND, collector to the motor's minus lead; a 1N5819 across each motor
// (decision 0013, amending 0003). L and R each switch two motors in parallel.
#define PIN_MOTOR_L 8
#define PIN_MOTOR_R 9
#define PIN_MOTOR_B 10
#define PIN_MOTOR_F 11

#define PIN_BATTERY_SENSE 5      // ADC1 (works while BLE is on) through a 100 k / 100 k divider
#define PIN_CHARGING_SENSE 6     // TP4056 CHRG, active low, 10 k pull-up

// Status light: the S3-Zero's onboard WS2812 RGB LED on GPIO 21, driven with rgbLedWrite().
// For a board with a plain LED set STATUS_LED_RGB to 0; set PIN_STATUS_LED to -1 to disable.
#define PIN_STATUS_LED 21
#define STATUS_LED_RGB 1
#define STATUS_LED_BRIGHTNESS 24  // 0-255 per channel; the WS2812 is very bright at full

// Reserved for v2 and not used by this firmware yet (decision 0014, docs/kandha/V2_DESIGN.md 2.2):
//   GPIO 7  PAD_F (touch T7)
//   GPIO 12 I2S BCLK (shared by both microphone buses), GPIO 13 I2S WS (shared)
//   GPIO 14 I2S0 DIN (mics 1+2), GPIO 15 I2S1 DIN (mics 3+4)
//   GPIO 44 MPU-6050 SDA, GPIO 43 MPU-6050 SCL (UART0 pins; Serial runs over USB CDC)
//   GPIO 16 spare

#define PWM_FREQUENCY_HZ 20000
#define PWM_RESOLUTION_BITS 8
#define MOTOR_KICK_MS 15         // overdrive at full duty when a step starts from rest (ERM spin-up)
#define MOTOR_MIN_DUTY 60        // below this an ERM does not start; levels are mapped above it

// Touch: on the ESP32-S3 the reading RISES when a pad is touched (it falls on the original ESP32)
#define TOUCH_RISES_WHEN_PRESSED 1
#define TOUCH_THRESHOLD_RATIO 1.25f
#define TOUCH_POLL_MS 20
#define TOUCH_DEBOUNCE_MS 40
#define GESTURE_TAP_MAX_MS 400
#define GESTURE_DOUBLE_GAP_MS 300
#define GESTURE_LONG_MS 700

#define STATUS_PERIOD_MS 30000
#define BATTERY_SAMPLE_MS 5000
#define BLE_MTU 185
