/*
 * Sanket Band link: Bluetooth (ESP32 band, see firmware/) and phone vibration.
 * Protocol (one GATT service):
 *   CUE    write  1 byte : 1 softer, 2 rose, 3 hesitation, 4 silence, 5 speaker change, 9 test
 *   COLOUR write  3 bytes: R, G, B of the current speaker (0,0,0 = off)
 *   BUTTON notify 1 byte : 1 = queue button pressed
 */
(function (root) {
  'use strict';

  const SERVICE = 'a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0001';
  const CUE = 'a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0002';
  const COLOUR = 'a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0003';
  const BUTTON = 'a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0004';

  const CODES = { drop: 1, rise: 2, hesitation: 3, silence: 4, speaker: 5, test: 9 };

  // The same patterns the band firmware plays, in milliseconds (on, off, on, ...)
  const PATTERNS = {
    drop: [700],
    rise: [90, 80, 90, 80, 90],
    hesitation: [40, 40, 40, 40, 40, 40, 40, 40, 40],
    silence: [150, 300, 150],
    speaker: [30],
    test: [200, 100, 200],
  };

  class Band {
    constructor(handlers) {
      this.h = handlers || {};
      this.device = null;
      this.cueChar = null;
      this.colourChar = null;
      this.queue = Promise.resolve();
      this.phoneVibrate = false;
    }

    static bluetoothSupported() { return !!(root.navigator && navigator.bluetooth); }
    static vibrationSupported() { return !!(root.navigator && navigator.vibrate); }

    get connected() { return !!(this.device && this.device.gatt && this.device.gatt.connected); }

    async connect() {
      if (!Band.bluetoothSupported()) throw new Error('This browser can’t use Bluetooth. Use Chrome on a computer or Android phone.');
      const device = await navigator.bluetooth.requestDevice({ filters: [{ services: [SERVICE] }, { namePrefix: 'Sanket' }], optionalServices: [SERVICE] });
      device.addEventListener('gattserverdisconnected', () => { this.cueChar = this.colourChar = null; this._status(); });
      const server = await device.gatt.connect();
      const svc = await server.getPrimaryService(SERVICE);
      this.cueChar = await svc.getCharacteristic(CUE);
      this.colourChar = await svc.getCharacteristic(COLOUR);
      try {
        const btn = await svc.getCharacteristic(BUTTON);
        await btn.startNotifications();
        btn.addEventListener('characteristicvaluechanged', (e) => {
          if (e.target.value.getUint8(0) === 1 && this.h.onButton) this.h.onButton();
        });
      } catch (e) { /* band without a button */ }
      this.device = device;
      this._status();
      return device.name || 'Sanket Band';
    }

    disconnect() { if (this.device && this.device.gatt.connected) this.device.gatt.disconnect(); this.device = null; this._status(); }

    // Writes are queued: GATT allows one operation at a time.
    _write(ch, bytes) {
      if (!ch) return;
      this.queue = this.queue.then(() => ch.writeValueWithoutResponse
        ? ch.writeValueWithoutResponse(new Uint8Array(bytes))
        : ch.writeValue(new Uint8Array(bytes))).catch(() => {});
    }

    cue(kind) {
      if (this.connected) this._write(this.cueChar, [CODES[kind] || 0]);
      if (this.phoneVibrate && Band.vibrationSupported() && PATTERNS[kind]) { try { navigator.vibrate(PATTERNS[kind]); } catch (e) { /* ignore */ } }
    }

    colour(hex) {
      if (!this.connected) return;
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
      this._write(this.colourChar, m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0]);
    }

    _status() { if (this.h.onStatus) this.h.onStatus(this.connected, this.device && this.device.name); }
  }

  Band.PATTERNS = PATTERNS;
  Band.SERVICE = SERVICE;
  root.SanketBand = Band;
})(typeof self !== 'undefined' ? self : this);
