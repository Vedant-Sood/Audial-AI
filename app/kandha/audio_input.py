"""Multichannel audio for direction finding (decision 0027): live capture or a recorded file.

The Kandha page keeps its own mono microphone for the voice engine and captions. This is a
second, separate input used only to work out where speech comes from. Audio stays in memory:
blocks go to the DirectionTracker and are dropped; nothing is written, logged or sent.

Modes (KandhaSettings.audio_mode):
- "mono": no direction input (the default).
- "stereo": two microphones that really are two (a laptop array, a USB stereo mic).
- "quad": a 4-channel interface or array, microphones on a square (the pod's geometry).
- "recorded": a WAV file played back in real time, looping; SIMULATED. A .json beside it
  (from app.kandha.room_synth) gives the microphone positions; otherwise 2 channels are
  treated as stereo and 4 as quad.

Linux with PipeWire: a specific microphone is chosen with a device of the form
"pulse:<source name>" (see `pactl list sources short`), opened through the PulseAudio
compatibility layer, so the laptop's two-channel array can be used while the page uses
another microphone.
"""
import json
import os
from pathlib import Path
import queue
import threading
import time

import numpy as np

from app.kandha.direction import ArrayGeometry, DirectionTracker, is_fake_stereo

RATE = 48000
BLOCK = 2400          # 50 ms


def geometry_for(mode, channels, spacing_m=0.03, swap=False, sidecar=None):
    if sidecar and sidecar.get("positions"):
        return ArrayGeometry(sidecar.get("geometry", "recorded"), tuple(tuple(p) for p in sidecar["positions"]))
    if mode == "quad" or channels == 4:
        return ArrayGeometry.quad()
    return ArrayGeometry.stereo(spacing_m, swap)


def list_devices():
    """Input devices with at least two channels, plus PipeWire/PulseAudio sources by name."""
    out = []
    try:
        import sounddevice as sd
        for index, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) >= 1:
                out.append({"id": str(index), "name": dev["name"], "channels": int(dev["max_input_channels"]),
                            "rate": int(dev.get("default_samplerate") or 0)})
    except Exception as error:   # no PortAudio: say so rather than fail
        out.append({"id": "", "name": f"Audio devices unavailable: {error}", "channels": 0, "rate": 0})
    try:
        import subprocess
        listing = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True, timeout=3)
        for line in listing.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 4 and not parts[1].endswith(".monitor"):
                spec = parts[3]
                channels = next((int(tok[:-2]) for tok in spec.split() if tok.endswith("ch") and tok[:-2].isdigit()), 0)
                out.append({"id": "pulse:" + parts[1], "name": parts[1], "channels": channels, "rate": 0, "pulse": True})
    except Exception:
        pass
    return out


class DirectionInput:
    """Runs one audio source into a DirectionTracker on a background thread."""

    def __init__(self, mode, clock, device="", spacing_m=0.03, swap=False, recorded_file="", on_error=None):
        if mode not in ("stereo", "quad", "recorded"):
            raise ValueError("Direction needs the stereo, quad or recorded audio mode.")
        self.mode = mode
        self.clock = clock
        self.device = device
        self.spacing_m = spacing_m
        self.swap = swap
        self.recorded_file = recorded_file
        self.on_error = on_error or (lambda message: None)
        self.stop_event = threading.Event()
        self.tracker = None
        self.thread = None
        self.error = None
        self.fake_checked = False
        self.info = {}

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self.mode == "recorded":
            self._start_file()
        else:
            self._start_live()
        return self

    def stop(self):
        self.stop_event.set()
        stream = getattr(self, "stream", None)
        if stream is not None:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(2)

    def _fail(self, message):
        self.error = message
        self.on_error(message)

    # ------------------------------------------------------------------ live capture
    def _start_live(self):
        import sounddevice as sd
        channels = 4 if self.mode == "quad" else 2
        device = self.device or None
        if isinstance(device, str) and device.startswith("pulse:"):
            os.environ["PULSE_SOURCE"] = device[len("pulse:"):]      # read by PortAudio's pulse device
            device = "pulse"
        elif isinstance(device, str) and device.isdigit():
            device = int(device)
        self.tracker = DirectionTracker(geometry_for(self.mode, channels, self.spacing_m, self.swap), RATE)
        blocks = queue.Queue(maxsize=200)

        def callback(data, frames, timing, status):
            try:
                blocks.put_nowait(data.copy())
            except queue.Full:
                pass

        try:
            self.stream = sd.InputStream(device=device, channels=channels, samplerate=RATE, blocksize=BLOCK,
                                         dtype="float32", callback=callback)
            self.stream.start()
        except Exception as error:
            raise ValueError(f"Could not open a {channels}-channel input on {self.device or 'the default device'}: {error}")
        self.info = {"device": self.device or "default", "channels": channels, "rate": RATE, "simulated": False}
        self.thread = threading.Thread(target=self._pump, args=(blocks,), name="kandha-direction", daemon=True)
        self.thread.start()

    def _pump(self, blocks):
        seen = []
        while not self.stop_event.is_set():
            try:
                block = blocks.get(timeout=0.2)
            except queue.Empty:
                continue
            if not self.fake_checked:
                seen.append(block)
                if sum(len(b) for b in seen) >= RATE:            # one second to decide
                    self.fake_checked = True
                    if self.tracker.geometry.channels == 2 and is_fake_stereo(np.vstack(seen)):
                        self._fail("This microphone is really mono: both channels carry the same signal, so it "
                                   "cannot tell left from right. Choose another microphone or use Mono.")
                        return
            self.tracker.feed(block, self.clock())

    # ------------------------------------------------------------------ recorded file (SIMULATED)
    def _start_file(self):
        import soundfile as sf
        path = Path(self.recorded_file)
        if not path.is_file():
            raise ValueError("Choose a recorded WAV file for the Recorded mode.")
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
        if audio.shape[1] < 2:
            raise ValueError("The recorded file has one channel: direction needs two or four.")
        sidecar = None
        meta = path.with_suffix(".json")
        if meta.is_file():
            try:
                sidecar = json.loads(meta.read_text(encoding="utf-8"))
            except ValueError:
                sidecar = None
        self.tracker = DirectionTracker(geometry_for("recorded", audio.shape[1], self.spacing_m, self.swap, sidecar), rate)
        self.info = {"device": path.name, "channels": int(audio.shape[1]), "rate": int(rate), "simulated": True,
                     "truth": sidecar.get("talkers") if sidecar else None}
        self.thread = threading.Thread(target=self._play, args=(audio, rate), name="kandha-direction-file", daemon=True)
        self.thread.start()

    def _play(self, audio, rate):
        block = int(rate * 0.05)
        start = time.monotonic()
        position = 0
        while not self.stop_event.is_set():
            chunk = audio[position:position + block]
            if len(chunk) < block:                                  # loop the file
                need = block - len(chunk)
                chunk = np.vstack((chunk, audio[:need]))
                position = need
            else:
                position += block
            self.tracker.feed(chunk, self.clock())
            start += block / rate
            delay = start - time.monotonic()
            if delay > 0:
                self.stop_event.wait(delay)

    # ------------------------------------------------------------------ status
    def status(self):
        latest = self.tracker.latest() if self.tracker else {}
        return {"mode": self.mode, "error": self.error, **self.info, **latest}
