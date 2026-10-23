"""StoleBridge: the Bluetooth link to a Kandha Stole, with a mock backend for tests and demos.

`StoleLink` is the asyncio core (scan, pair, remember, connect, reconnect with backoff, writes,
notifications, the paired-address allowlist). `StoleBridge` runs it on its own thread and offers
blocking calls to the rest of the app. `MockBackend` and `MockStole` stand in for `bleak` and a
real stole: they apply the same bytes to a PatternPlayer, so tests and the end-to-end check can
read back exactly what the motors would have done and when.

Captions never depend on anything here: every call is bounded and every failure becomes an
event, not an exception, for the caller.
"""
import asyncio
import concurrent.futures
import json
from pathlib import Path
import threading
import time

from app.kandha.patterns import PatternPlayer, table as shared_table
from app.kandha.protocol import (FLAG_LOW_BATTERY, HapticCommand, PadInput, StoleConfig, StoleStatus, decode_pattern_upload,
                                 name_prefix, uuids)
from app.utils.paths import atomic_json, data_root

BACKOFF_S = (1, 2, 4, 8, 16, 30)
SCAN_TIMEOUT_S = 6.0
CONNECT_TIMEOUT_S = 12.0


def backoff(attempt):
    """Seconds to wait before reconnect attempt `attempt` (0-based): 1, 2, 4, 8, 16, 30, 30 ..."""
    return BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]


# ---------------------------------------------------------------------------- real backend
class BleakBackend:
    """Thin wrapper over bleak so the link can be tested with a mock."""

    name = "bleak"

    async def scan(self, timeout, service_uuid, prefix):
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for device, adv in found.values():
            local = adv.local_name or device.name or ""
            services = [u.lower() for u in (adv.service_uuids or [])]
            if service_uuid.lower() in services or local.startswith(prefix):
                out.append({"address": device.address, "name": local or device.address, "rssi": adv.rssi})
        return sorted(out, key=lambda d: -(d["rssi"] or -999))

    def client(self, address, disconnected_callback):
        from bleak import BleakClient
        return BleakClient(address, disconnected_callback=disconnected_callback, timeout=CONNECT_TIMEOUT_S)


# ---------------------------------------------------------------------------- mock backend
class MockStole:
    """A pretend Kandha Stole: GATT characteristics backed by the Python PatternPlayer (the firmware's formula
    and timing; the firmware's 60/255 motor floor and 15 ms spin-up kick are not modelled)."""

    def __init__(self, address="AA:BB:CC:DD:EE:01", name=None, battery=87, charging=False, firmware=(1, 0), table=None,
                 clock=time.monotonic, advertises_service=True):
        self.table = table or shared_table()
        self.address = address
        self.name = name or f"{name_prefix()}{address.replace(':', '')[-4:]}"      # Kandha-XXXX, like the firmware
        self.advertises_service = advertises_service
        self.clock = clock
        self.battery = battery
        self.charging = charging
        self.firmware = firmware
        self.config = StoleConfig()
        self.player = PatternPlayer(self.table, self.config)
        self.custom = {}
        self.last_seq = None
        self.received = []          # (monotonic, characteristic name, bytes)
        self.clients = []
        self.connect_failures = 0   # the next N connects raise
        self.rssi = -60

    def status(self):
        flags = FLAG_LOW_BATTERY if self.battery <= int(self.table.scheduler["low_battery_percent"]) and not self.charging else 0
        return StoleStatus(self.battery, self.charging, self.firmware[0], self.firmware[1], flags)

    def write(self, uuid, data):
        ids = uuids()
        now_ms = int(self.clock() * 1000)
        data = bytes(data)
        if uuid == ids["haptic"]:
            self.received.append((self.clock(), "haptic", data))
            command = HapticCommand.decode(data)
            if command.seq != self.last_seq:
                self.last_seq = command.seq
                self.player.start(command, now_ms, pattern=self.table.by_id.get(command.pattern) or self.custom.get(command.pattern))
        elif uuid == ids["config"]:
            self.received.append((self.clock(), "config", data))
            self.config = StoleConfig.decode(data)
            self.player.config = self.config
        elif uuid == ids["patterns"]:
            from app.kandha.patterns import Pattern
            self.received.append((self.clock(), "patterns", data))
            pattern_id, steps = decode_pattern_upload(data)
            self.custom[pattern_id] = Pattern(pattern_id, f"custom-{pattern_id}", "", "", "any", "system", 255, 1, tuple(steps))
        else:
            raise ValueError("Unknown characteristic.")

    def read(self, uuid):
        ids = uuids()
        if uuid == ids["status"]:
            return self.status().encode()
        if uuid == ids["config"]:
            return self.config.encode()
        raise ValueError("Characteristic is not readable.")

    # things a test or demo does to the pretend hardware
    def press(self, pad, gesture):
        self._notify(uuids()["input"], PadInput(pad, gesture).encode())

    def set_battery(self, percent, charging=None):
        self.battery = max(0, min(100, int(percent)))
        if charging is not None:
            self.charging = bool(charging)
        self._notify(uuids()["status"], self.status().encode())

    def drop(self):
        """The link breaks (out of range, power off)."""
        for client in list(self.clients):
            client._dropped()

    def _notify(self, uuid, payload):
        for client in list(self.clients):
            client._deliver(uuid, payload)


class MockBleakClient:
    def __init__(self, stole, disconnected_callback, loop_ref):
        self.stole = stole
        self.address = stole.address if stole else "00:00:00:00:00:00"
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.notify = {}
        self.loop_ref = loop_ref

    async def connect(self):
        if self.stole is None:
            raise OSError("Device not found.")
        if self.stole.connect_failures > 0:
            self.stole.connect_failures -= 1
            raise OSError("Connection failed.")
        self.is_connected = True
        self.stole.clients.append(self)
        return True

    async def disconnect(self):
        self._dropped(callback=False)
        return True

    async def write_gatt_char(self, uuid, data, response=False):
        if not self.is_connected:
            raise OSError("Not connected.")
        self.stole.write(uuid, data)

    async def read_gatt_char(self, uuid):
        if not self.is_connected:
            raise OSError("Not connected.")
        return bytearray(self.stole.read(uuid))

    async def start_notify(self, uuid, callback):
        self.notify[uuid] = callback

    def _deliver(self, uuid, payload):
        callback = self.notify.get(uuid)
        if callback and self.is_connected:
            loop = self.loop_ref()
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(callback, uuid, bytearray(payload))
            else:
                callback(uuid, bytearray(payload))

    def _dropped(self, callback=True):
        if not self.is_connected:
            return
        self.is_connected = False
        if self in self.stole.clients:
            self.stole.clients.remove(self)
        if callback and self.disconnected_callback:
            loop = self.loop_ref()
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self.disconnected_callback, self)
            else:
                self.disconnected_callback(self)


class MockBackend:
    name = "mock"

    def __init__(self, stoles=(), scan_delay=0.0):
        self.stoles = {s.address: s for s in stoles}
        self.scan_delay = scan_delay
        self.scans = 0
        self.loop = None

    def add(self, stole):
        self.stoles[stole.address] = stole
        return stole

    async def scan(self, timeout, service_uuid, prefix):
        self.scans += 1
        if self.scan_delay:
            await asyncio.sleep(min(self.scan_delay, timeout))
        return [{"address": s.address, "name": s.name, "rssi": s.rssi} for s in self.stoles.values()
                if s.advertises_service or s.name.startswith(prefix)]

    def client(self, address, disconnected_callback):
        return MockBleakClient(self.stoles.get(address), disconnected_callback, lambda: self.loop)

    def name_of(self, address):
        """The name a pretend stole has now (bleak cannot know this until a scan hears the stole)."""
        stole = self.stoles.get(address)
        return stole.name if stole else None


class SimulatedStole(MockStole):
    """The prototype's built-in stole: pairs like a real one, drains a little battery, can be told to
    go out of range. It has no radio; it lives inside the app so pairing, status and reconnection
    can be shown and tested before any hardware exists."""

    ADDRESS = "SIM:KA:ND:HA:00:01"

    def __init__(self, table=None, clock=time.monotonic):
        super().__init__(self.ADDRESS, name=f"{name_prefix()}SIM1", battery=92, charging=False, firmware=(0, 9), table=table, clock=clock)
        self.started = clock()
        self.drain_per_hour = 4            # percent; a slow, visible change during a demo day

    def status(self):
        hours = max(0.0, self.clock() - self.started) / 3600.0
        self.battery = max(5, int(92 - self.drain_per_hour * hours))
        return super().status()

    def simulate(self, action, value=None):
        """Actions the Stole panel can trigger: out_of_range, battery, charging, press."""
        if action == "out_of_range":
            self.connect_failures = 2
            self.drop()
            return {"simulated": "out of range for two reconnect attempts"}
        if action == "battery":
            self.started = self.clock() - ((92 - int(value)) / self.drain_per_hour) * 3600.0 if value is not None else self.started
            self.set_battery(int(value) if value is not None else self.battery)
            return {"simulated": f"battery {self.battery}%"}
        if action == "charging":
            self.set_battery(self.battery, charging=bool(value))
            return {"simulated": "charging" if value else "not charging"}
        if action == "press":
            pad, gesture = value
            self.press(pad, gesture)
            from app.kandha.protocol import GESTURE_NAMES, PAD_NAMES
            return {"simulated": f"pad {PAD_NAMES.get(pad, pad)} gesture {GESTURE_NAMES.get(gesture, gesture)}"}
        raise ValueError("Unknown simulation.")


def simulated_backend(table=None):
    return MockBackend([SimulatedStole(table=table)])


# ---------------------------------------------------------------------------- asyncio core
class _Abandoned(Exception):
    """A connection attempt that forget(), another pair() or stop() has replaced."""


class StoleLink:
    """Scan, pair, remember, connect, reconnect, write, listen. One paired address at a time."""

    def __init__(self, backend, on_event, store_path=None, table=None, sleep=None, clock=time.monotonic):
        self.backend = backend
        self.on_event = on_event
        self.table = table or shared_table()
        self.store_path = Path(store_path) if store_path else data_root() / "kandha" / "stole.json"
        self.sleep = sleep or asyncio.sleep
        self.clock = clock
        self.ids = uuids()
        self.prefix = name_prefix()
        self.paired = None
        self.paired_name = None
        self.client = None
        self.state = "disconnected"
        self.attempt = 0
        self.last_error = None
        self.status = None
        self.config = StoleConfig()
        self.low_battery_sent = False
        self.latencies = []        # last write round trips, ms
        self.stopping = False
        self._wake = None
        self._attempt = None       # the one connection attempt in flight (an asyncio task), shared by pair() and run()
        self._epoch = 0            # disconnect() counts up, so an attempt that outlives its cancel knows it is not wanted
        self._load()

    # ----------------------------------------------------------------- persistence
    def _load(self):
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("address"), str):
                self.paired = data["address"]
                self.paired_name = str(data.get("name") or "")
        except (OSError, ValueError):
            pass
        name_of = getattr(self.backend, "name_of", None)
        if self.paired and name_of:              # the stole's own name beats one an earlier build saved
            self.paired_name = name_of(self.paired) or self.paired_name

    def _save(self):
        if self.paired:
            atomic_json(self.store_path, {"address": self.paired, "name": self.paired_name or "", "protocol": 1})
        else:
            try:
                self.store_path.unlink()
            except OSError:
                pass

    def _set_state(self, state, **extra):
        self.state = state
        self.on_event("stole_state", {"state": state, "paired": self.paired, "name": self.paired_name, "attempt": self.attempt,
                                      "error": self.last_error, **extra})

    def snapshot(self):
        return {"state": self.state, "paired": self.paired, "name": self.paired_name, "attempt": self.attempt, "error": self.last_error,
                "status": self.status.as_dict() if self.status else None, "backend": getattr(self.backend, "name", "?"),
                "latency_ms": {"last": self.latencies[-1] if self.latencies else None,
                               "max": max(self.latencies) if self.latencies else None, "n": len(self.latencies)}}

    @property
    def connected(self):
        return self.state == "connected" and self.client is not None and self.client.is_connected

    # ----------------------------------------------------------------- scan / pair / forget
    async def scan(self, timeout=SCAN_TIMEOUT_S):
        was = self.state
        if not self.connected:
            self._set_state("scanning")
        try:
            found = await asyncio.wait_for(self.backend.scan(timeout, self.ids["service"], self.prefix), timeout + 5)
        except Exception as error:  # a Bluetooth stack failure is a message, not a crash
            self.last_error = f"Scan failed: {error}"
            found = []
        heard = next((d.get("name") for d in found or [] if isinstance(d, dict) and d.get("address") == self.paired), None)
        renamed = bool(heard) and heard not in (self.paired, self.paired_name)
        if renamed:                                 # the paired stole now has another name (new firmware): show that
            self.paired_name = str(heard)
            self._save()
        if self.state == "scanning":                # nothing else changed the state meanwhile: put it back
            self._set_state("disconnected" if was in ("scanning", "disconnected") else was)
        elif renamed:
            self._set_state(self.state)
        self.on_event("stole_scan", {"devices": found})
        return found

    async def pair(self, address, name=None):
        changed = self.paired != address
        # set the new address first, so nothing that wakes while the old link closes reconnects to it
        self.paired, self.paired_name = address, name or ""
        self._save()
        if changed:
            self.status = None
            await self.disconnect()
        if self.connected:
            self._set_state("connected")                      # this stole is already connected: keep its one client
            return self.paired == address
        self.low_battery_sent = False
        self.attempt = 0
        self._kick()
        return await self.connect_once() and self.paired == address

    async def forget(self):
        self.paired = self.paired_name = None                 # first, so run() does not reconnect while we close
        self.status = None
        self._save()
        await self.disconnect()
        if self.paired is None:                               # unless Pair came while we closed and is connecting
            self._set_state("disconnected")

    async def disconnect(self):
        """Close the live client and abandon any attempt in flight, then let run() look again."""
        client, self.client = self.client, None
        attempt, self._attempt = self._attempt, None
        self._epoch += 1                                      # whatever was connecting is no longer wanted
        if attempt is not None and not attempt.done():
            attempt.cancel()
        if self.state != "disconnected":
            self._set_state("disconnected")
        await self._close(client)
        if attempt is not None and not attempt.done():
            await asyncio.wait({attempt})
        self._kick()

    async def _close(self, client):
        if client is None:
            return
        try:
            await asyncio.wait_for(client.disconnect(), 5)
        except Exception:
            pass

    # ----------------------------------------------------------------- connection
    async def connect_once(self):
        """One attempt to connect to the paired stole. pair() and run() share the attempt in flight,
        so there is never a second client for the same stole."""
        if not self.paired or self.stopping:
            return False
        if self.connected:
            return True
        if self._attempt is None or self._attempt.done():
            self._attempt = asyncio.ensure_future(self._connect(self.paired))
        attempt = self._attempt
        await asyncio.wait({attempt})                         # waiting here never cancels the shared attempt
        return not attempt.cancelled() and attempt.result()

    async def _connect(self, address):
        self._set_state("connecting" if self.attempt == 0 else "reconnecting")
        epoch = self._epoch
        client = None

        def still_wanted():
            # asyncio.wait_for (Python 3.11) can lose a cancel that lands as connect() finishes,
            # so check by hand that no forget(), other pair() or stop() came meanwhile
            if epoch != self._epoch or self.stopping or address != self.paired:
                raise _Abandoned()

        try:
            # inside the try: a backend that cannot even build a client (bleak missing) is a message too
            client = self.backend.client(address, self._on_disconnect)
            await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT_S + 2)
            still_wanted()
            if getattr(client, "address", address) != address:
                raise OSError("Connected to an unexpected device.")
            old, self.client = self.client, client
            if old is not None and old is not client:         # never leave an earlier client open behind this one
                await self._close(old)
            await client.write_gatt_char(self.ids["config"], self.config.encode(), response=True)
            raw = await client.read_gatt_char(self.ids["status"])
            still_wanted()
            self._on_status(None, raw)
            await client.start_notify(self.ids["input"], self._only_from(client, self._on_input))
            await client.start_notify(self.ids["status"], self._only_from(client, self._on_status))
            still_wanted()
            if self.client is not client or not client.is_connected:
                raise OSError("The stole disconnected while connecting.")
        except (asyncio.CancelledError, _Abandoned) as error:  # pair() of another stole, forget() or stop()
            if self.client is client:
                self.client = None
            await self._close(client)
            if isinstance(error, asyncio.CancelledError):
                raise
            return False
        except Exception as error:
            self.last_error = str(error) or error.__class__.__name__
            if self.client is client:
                self.client = None
            await self._close(client)
            self._set_state("disconnected" if self.stopping else "reconnecting")
            return False
        self.attempt = 0
        self.last_error = None
        self._set_state("connected")
        self.on_event("stole_connected", {"address": self.paired, "name": self.paired_name})
        return True

    def _only_from(self, client, handler):
        """A notification callback that is ignored once `client` is no longer the live link."""
        def callback(characteristic, data):
            if client is self.client:
                handler(characteristic, data)
        return callback

    def _on_disconnect(self, client):
        if client is not self.client:
            return                                            # an old or half-made client closing, not the live link
        self.client = None
        if self.state == "connected":
            self.last_error = "The stole disconnected."
            self._set_state("reconnecting")
        self._kick()

    def _kick(self):
        if self._wake is not None:
            self._wake.set()

    async def run(self):
        """Keep the paired stole connected until stop(). Backoff 1, 2, 4, 8, 16, 30 s between attempts.

        pair(), forget(), a drop and stop() all kick _wake and every pass re-reads the link's state, so
        the loop never waits on a connection that has already gone."""
        self._wake = asyncio.Event()
        while not self.stopping:
            if not self.paired or self.connected:
                self._wake.clear()
                await self._wake.wait()
                continue
            target = self.paired
            try:
                ok = await self.connect_once()
            except Exception as error:                        # one bad attempt never ends the loop (or the thread)
                self.last_error = str(error) or error.__class__.__name__
                ok = False
            if ok or self.stopping or self.connected or self.paired != target:
                continue                                      # connected, stopping, or another stole was chosen
            if self._attempt is not None and not self._attempt.done():
                continue                                      # pair() started a fresh attempt meanwhile: wait on that one
            delay = backoff(self.attempt)
            self.attempt += 1
            self._set_state("reconnecting", next_try_s=delay)
            self._wake.clear()
            waiter = asyncio.ensure_future(self._wake.wait())
            sleeper = asyncio.ensure_future(self.sleep(delay))
            await asyncio.wait({waiter, sleeper}, return_when=asyncio.FIRST_COMPLETED)
            for task in (waiter, sleeper):
                if not task.done():
                    task.cancel()
            if self._wake.is_set():
                self.attempt = 0

    async def stop(self):
        self.stopping = True
        self._kick()
        await self.disconnect()

    # ----------------------------------------------------------------- traffic
    async def write_haptic(self, data):
        """Write five HAPTIC bytes. Returns the write's round trip in ms, or None when not connected."""
        client = self.client
        if client is None or not client.is_connected:
            return None
        started = self.clock()
        try:
            await client.write_gatt_char(self.ids["haptic"], bytes(data), response=False)
        except Exception as error:
            self.last_error = f"Write failed: {error}"
            self.on_event("stole_error", {"error": self.last_error})
            return None
        ms = (self.clock() - started) * 1000
        self.latencies.append(round(ms, 2))
        if len(self.latencies) > 200:
            del self.latencies[:100]
        return ms

    async def write_config(self, config):
        self.config = config
        client = self.client
        if client is None or not client.is_connected:
            return False
        try:
            await client.write_gatt_char(self.ids["config"], config.encode(), response=True)
            return True
        except Exception as error:
            self.last_error = f"Config write failed: {error}"
            self.on_event("stole_error", {"error": self.last_error})
            return False

    async def write_patterns(self, payload):
        client = self.client
        if client is None or not client.is_connected:
            return False
        await client.write_gatt_char(self.ids["patterns"], bytes(payload), response=True)
        return True

    def _on_input(self, _characteristic, data):
        if self.client is None or getattr(self.client, "address", None) != self.paired:
            return                                            # never act on pads of a device we did not pair
        try:
            pad = PadInput.decode(bytes(data))
        except ValueError:
            return
        self.on_event("input", {"device": "stole", "pad": pad.pad_name, "gesture": pad.gesture_name, "raw": bytes(data).hex()})

    def _on_status(self, _characteristic, data):
        try:
            status = StoleStatus.decode(bytes(data))
        except ValueError:
            return
        self.status = status
        self.on_event("stole_status", status.as_dict() | {"device": "stole"})
        if status.charging:
            self.low_battery_sent = False
        elif status.low and not self.low_battery_sent:
            self.low_battery_sent = True
            self.on_event("low_battery", {"battery": status.battery})


# ---------------------------------------------------------------------------- thread wrapper
class StoleBridge:
    """Runs a StoleLink on its own event loop thread; blocking helpers for the service and the UI."""

    def __init__(self, on_event, backend=None, store_path=None, table=None):
        self.backend = backend or BleakBackend()
        self.link = StoleLink(self.backend, on_event, store_path=store_path, table=table)
        self.loop = None
        self.thread = None
        self._ready = threading.Event()

    def start(self):
        if self.thread is not None:
            return
        self.loop = asyncio.new_event_loop()
        self._stopped = asyncio.Event()
        if hasattr(self.backend, "loop"):
            self.backend.loop = self.loop
        self.thread = threading.Thread(target=self._run, name="kandha-stole", daemon=True)
        self.thread.start()
        self._ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_until_complete(self.link.run())
        except Exception as error:      # the reconnect loop failed: say so, and keep serving calls until stop()
            self.link.last_error = f"The stole link stopped: {error}"
            try:
                self.link.on_event("stole_error", {"error": self.link.last_error})
            except Exception:
                pass
        try:
            # run() ends as soon as stop() begins; keep the loop until stop() has closed the link
            self.loop.run_until_complete(self._stopped.wait())
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

    async def _stop(self):
        try:
            await self.link.stop()
        finally:
            self._stopped.set()

    @property
    def running(self):
        return self.loop is not None and self.thread is not None and self.thread.is_alive()

    def call(self, coro, timeout=None):
        loop, thread = self.loop, self.thread
        if loop is None or thread is None or not thread.is_alive():   # never wait out a timeout on a loop nobody runs
            coro.close()
            raise RuntimeError("The stole bridge is not running.")
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:                # the loop closed a moment ago
            coro.close()
            raise RuntimeError("The stole bridge is not running.") from None
        deadline = None if timeout is None else time.monotonic() + timeout
        while not future.done():
            if not thread.is_alive():       # the loop has gone, so this call can never finish
                future.cancel()
                raise RuntimeError("The stole bridge stopped.")
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise TimeoutError("The stole did not answer in time.")
            concurrent.futures.wait([future], timeout=0.25 if left is None else min(0.25, left))
        try:
            return future.result()
        except concurrent.futures.CancelledError:   # stop() ended this call (a scan or pair) part way
            raise RuntimeError("The stole bridge stopped.") from None

    def post(self, coro):
        if not self.running:
            coro.close()
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        except RuntimeError:                # the loop closed a moment ago: a lost tap, never an exception
            coro.close()
            return None

    def scan(self, timeout=SCAN_TIMEOUT_S):
        return self.call(self.link.scan(timeout), timeout + 10)

    def pair(self, address, name=None):
        return self.call(self.link.pair(address, name), CONNECT_TIMEOUT_S + 10)

    def forget(self):
        return self.call(self.link.forget(), 10)

    def write_haptic(self, data):
        return self.post(self.link.write_haptic(data))

    def write_config(self, config):
        return self.post(self.link.write_config(config))

    @property
    def connected(self):
        return self.link.connected

    def snapshot(self):
        return self.link.snapshot()

    def stop(self):
        if self.loop is None:
            return
        try:
            self.call(self._stop(), 10)
        except Exception:
            try:
                self.loop.call_soon_threadsafe(self._stopped.set)
            except RuntimeError:
                pass                        # the loop has already closed
        self.thread.join(5)
        self.loop = None
        self.thread = None
