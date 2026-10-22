// Kandha Stole firmware: board configuration and pin map (docs/kandha/DESIGN.md section 5.3).
// Target: ESP32-S3 (generic DevKit or SuperMini), Arduino-ESP32 core 3.x.
#pragma once
#include <stdint.h>

#define KANDHA_FW_MAJOR 0
#define KANDHA_FW_MINOR 9

// Touch pads (ESP32-S3 touch-capable GPIOs 1-14)
#define PIN_PAD_L 1
#define PIN_PAD_R 2
#define PIN_PAD_B 3
#define PIN_PAD_Q 4

// Motor zones: gates of logic-level N-MOSFETs (decision 0003), LEDC PWM
#define PIN_MOTOR_L 5
#define PIN_MOTOR_R 6
#define PIN_MOTOR_B 7
#define PIN_MOTOR_F 8

#define PIN_BATTERY_SENSE 9      // ADC through a 100 k / 100 k divider
#define PIN_CHARGING_SENSE 10    // TP4056 CHRG, active low, 10 k pull-up
#define PIN_STATUS_LED 48        // on-board LED on many S3 boards; set to -1 to disable

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
