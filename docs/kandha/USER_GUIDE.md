# Kandha user guide

Kandha (कंधा, "shoulder") captions the room, gives every voice its own colour, shows where each
person sits, and taps the **Kandha Stole** on the shoulder of whoever is speaking. Tone changes
are felt at the collarbone. Your eyes stay on faces.

> **Prototype.** This version runs entirely without hardware. The **virtual stole** on screen
> shows every tap exactly as the real stole would play it, and a built-in **simulated stole**
> shows what pairing, battery and reconnection will look like. The physical stole, its firmware
> and the Bluetooth link are prepared but have not been tested with hardware yet.

## Starting Kandha

- **Windows**: install `Kandha-Setup-<version>.exe` (or unzip `Kandha-<version>-windows.zip`)
  and open **Kandha** from the Start menu. The first run opens Audial-AI's **Setup & models**
  to download the Whisper caption model; after that Kandha works offline.
- **From source** (macOS, Linux, Windows): `python -m app.main --kandha`. Kandha is also a
  page in the Audial-AI window (**Kandha** in the navigation) and in a Chrome or Edge tab at
  `http://127.0.0.1:<port>/kandha/` while Audial-AI is running. In a browser tab, when the
  Whisper model is not installed, captions come from the browser's own speech recognition (the
  status line says *browser captions*), which may use the browser maker's servers; the Kandha
  window always captions on this computer.

Press **Start** (or `S`). Kandha asks for the microphone once. Let the people in the room know
that live captions are on.

## The screens

| Screen | What it is for |
|---|---|
| **Live** | the current caption in the speaker's colour, the recent transcript, the room diagram, the virtual stole, the queue strip |
| **Stole** | pairing, battery and firmware, a test button per zone, intensity, mirror left/right, do-not-disturb, **Learn the taps** |
| **Seats** | drag voices onto seats, save rooms, start with the last layout |
| **Review** | timeline of voices, cues, tone estimates, queue moments, taps and seat changes; transcript with tone notes; consent and export |
| **Settings** | name, caption size, theme, microphone, cues per mode, tone estimates, vocabulary, privacy |

Keyboard: `Q` I want to speak · `S` start/pause · `M` what did I miss (last 30 s) ·
`1` `2` `3` `4` seat the current voice left, right, behind, in front · `N` new voice ·
arrow keys move between screens · `Esc` closes a dialog.

## Modes

- **Lecture**: one speaker. No seat taps; the stole only answers the queue pad and marks a
  long silence.
- **Seminar**: several voices. Seat taps on; tone cues off unless you turn them on in Settings.
- **Practicum**: two voices, tone cues on. The partner is usually in front.
- **Do not disturb**: only the queue pad answers.

## The taps (learn them in five minutes)

Open **Stole → Learn the taps**. Each pattern plays on the stole (or the virtual stole) while
the screen says what it means.

| You feel | It means |
|---|---|
| one firm tap on a shoulder | someone on that side started speaking: look there |
| two short taps at the front | a new voice: touch the L, R or B pad within six seconds to say where they sit |
| one tap at the front | a known voice without a seat is speaking |
| one slow swell at the front | the voice softened (quieter or sadder than usual for that person) |
| three quick taps at the front | the voice rose (louder or more intense than usual) |
| a soft flutter at the front | hesitation: several short pauses |
| two gentle ticks on both shoulders | long silence: the floor is open |
| one short squeeze on both shoulders | your "I want to speak" is on |
| one longer squeeze on both shoulders | you have been waiting a while (at most once a minute) |
| three slow pulses at the back of the neck | the stole's battery is at 20 % |

Kandha is quiet by default. Tone cues are rate-limited (one every 3 s at most, the same cue at
most every 8 s) and a tap is never played late. Tone cues describe what a voice did, never what
someone feels.

## Seating voices

When two taps at the front announce a new voice, touch the **L**, **R** or **B** pad on the
stole within six seconds, press `1`–`4`, or drag the voice onto a seat on the **Seats** screen.
Double-tap a pad to move the person speaking now; hold a pad to clear their seat. Mark your own
voice as **This is me** (open the voice, then the seat row) and the stole will never tap for it.

Save the layout as a room ("Seminar room 2.14") and Kandha offers it next time. Rooms remember
which seat the first, second and third voice usually take; they never store who those people are.

## Wearing, charging and washing the stole

The stole is a cotton or khadi scarf worn over both shoulders with the pads at the right-hand
end. The electronics sit in a zipped channel on the inside.

- **Wearing**: the two motor pockets sit on top of each shoulder, one at the back of the neck
  and one at the collarbone. If it is more comfortable the other way round, turn on **Mirror
  left and right** in the Stole screen.
- **Charging**: unzip the channel, plug a USB-C cable into the charger. A full charge takes
  about two hours; the design target is a full college day (section 5.2 of the design
  document is an estimate, not a measurement).
- **Washing**: unzip the channel, lift out the carrier with the battery, motors and the pad
  strip, wash the stole, dry it flat, slide the carrier back.

Pairing (when there is a stole): Settings → **Stole link → Real Bluetooth**, then Stole →
**Scan** → **Pair**. Kandha remembers the stole and reconnects on its own. While it is
disconnected captions continue and the virtual stole shows every tap.

## Review and saving

The Review screen shows the session. Nothing is saved unless you tick **Everyone in this
session agreed to keep a transcript**. Then you can save to Audial-AI's sessions or export as a
web page, text, VTT, SRT or JSON. Saving a practicum transcript with a real client needs
supervisor and ethics approval.

**How accurate is this?** opens the tone model's measured numbers and limits. The estimates
are learned from acted American English and have not been tested on Indian English or Hindi
speakers or in real seminars.

## Privacy

Audio never leaves the computer: the microphone feeds the voice engine in the page and
Audial-AI's Whisper model over the loopback address only. No recording is kept. The stole link
carries taps, pad presses and battery level, never audio or words. There is no telemetry.
