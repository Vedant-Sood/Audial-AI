# Kandha user guide

Kandha (कंधा, "shoulder") captions the room, gives every voice its own colour, shows where each
person sits, and taps the **Kandha Stole** on the shoulder of whoever is speaking. Tone changes
are felt at the collarbone. Your eyes stay on faces.

> **Prototype.** This version runs entirely without hardware. The **virtual stole** on screen
> shows every tap where and when the real stole would play it, and a built-in **simulated stole**
> shows what pairing, battery and reconnection will look like. The physical stole, its firmware
> and the Bluetooth link are prepared but have not been tested with hardware yet.

## Starting Kandha

- **Windows**: install `Kandha-Setup-<version>.exe` (or unzip `Kandha-<version>-windows.zip`)
  and open **Kandha** from the Start menu. The installer also adds **Audial-AI workspace**,
  **Kandha user guide** (this guide, opened in your web browser) and **Uninstall Kandha**.
- **From source** (macOS, Linux, Windows): install `requirements.txt` (it includes `bleak` for
  the stole's Bluetooth link), then run `python -m app.main --kandha`. Kandha is also a page in
  the Audial-AI window (**Kandha** in the navigation) and in a Chrome or Edge tab at
  `http://127.0.0.1:<port>/kandha/` while Audial-AI is running.

**Captions need the Whisper caption model**, downloaded once to this computer. Until it is
installed, a bar at the top of the Kandha window says so and offers **Get the caption model**.
That button starts Audial-AI's **Setup & models** with its progress on screen: the full model
catalogue (about 3.6 GB), the three Whisper models first (tiny, small, medium). With
Audial-AI's default **Caption quality**, Fast, Kandha captions with Whisper tiny, the first
download; Balanced uses small (the second) and Accurate medium (the third). Pause and retry keep
the files already checked. Opened from the Audial-AI window, the button switches Audial-AI to
Setup & models instead. Voices and stole taps work meanwhile. When the model is ready Kandha
reloads itself, or, if something is on screen, asks you to press **Reload Kandha** once you have
paused and saved. After that Kandha captions offline.

In a browser tab, install the model from Audial-AI's **Setup & models**. A browser tab without
the Whisper model has no captions unless you turn on **Settings
› Privacy › Let the browser's own speech service caption when Whisper is not installed**. It is
off by default because the browser may send the audio to its maker's servers; with it on, the
status line says *browser captions*. The Kandha window always captions on this computer.

Press **Start** (or `S`) to listen; the microphone is used only while listening, and a browser
tab asks for permission first. Let the people in the room know that live captions are on.

## The screens

| Screen | What it is for |
|---|---|
| **Live** | the current caption in the speaker's colour, the recent transcript, the room diagram, the virtual stole, the queue strip |
| **Stole** | pairing, battery and firmware, a test button per zone, intensity, mirror left/right, do-not-disturb, **Learn the taps** |
| **Seats** | drag voices onto seats (or select one and press `1`–`4`), save rooms, start with the last layout |
| **Review** | timeline of voices, cues, tone estimates, queue moments, taps and seat changes; transcript with tone notes; consent, saving and export |
| **Settings** | name, caption size, theme, microphone, cues per mode, when a silence counts as long, tone estimates, vocabulary, privacy (browser captions opt-in) |

Keyboard: `Q` I want to speak · `S` start/pause · `M` what did I miss (last 30 s) ·
`1` `2` `3` `4` seat a voice left, right, behind, in front (the voice whose chip has keyboard
focus, else the voice selected on Seats, else the voice speaking now) · `N` new voice ·
arrow keys move between screens · `Esc` closes a dialog.

**Demos** (in the dock, next to New voice) plays the seminar or the practicum demo at any time,
also again after one has finished, with no microphone. Starting a demo pauses listening and
clears this screen; the dialog says what it would end, so save in Review first if you want to
keep it. Tick **Play the demo voices aloud** to hear the scripted voices.

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
**New voice** (`N`) starts a new voice yourself, even in a pause: the two taps play and the six
seconds start. On **Seats** you can also select a voice (it gets a tick; select it again to let
go) and press `1`–`4`. Double-tap a pad to move the person speaking now; hold a pad to clear
their seat. The pads on the on-screen stole work the same way. Mark your own voice as **This is
me** (open the voice, then the seat row) and the stole will never tap for it. If Kandha split
one person into two colours, open one of them and **Join voices**.

After a long silence (four seconds unless you change **A silence counts as long after** in
Settings), the first person to speak properly gets one tap, even if they were the last to speak
before the silence: on their seat, or the two taps at the front if their voice is new. A cough
or a short "mm" does not count.

Save the layout as a room ("Seminar room 2.14") and Kandha offers it next time. Rooms remember
which seat the first, second and third voice usually take; they never store who those people are.

## Wearing, charging and washing the stole

The stole is a cotton or khadi scarf worn over both shoulders with the pads at the right-hand
end. The electronics sit in a zipped channel on the inside.

- **Wearing**: the two motor pockets sit on top of each shoulder, one at the back of the neck
  and one at the collarbone. If it is more comfortable the other way round, turn on **Mirror
  left and right** in the Stole screen.
- **Charging**: unzip the channel, plug a USB-C cable into the charger. No stole has been
  charged yet: roughly one to two hours is an estimate from the charger's usual current, and a
  full college day is the design target (section 5.2 of the design document; both are
  estimates, not measurements).
- **Washing**: unzip the channel, lift out the carrier with the battery, motors and the pad
  strip, wash the stole, dry it flat, slide the carrier back.

Pairing (when there is a stole): Settings → **Stole link → Real Bluetooth (experimental)**,
then Stole → **Scan** → **Pair**. Kandha remembers the stole and reconnects on its own. While it
is disconnected captions continue and the virtual stole shows every tap.

## Review and saving

The Review screen shows the session: a live one, whatever gave the captions, or a demo. Nothing
is saved unless you tick **Everyone in this session agreed to keep a transcript**. Then **Save
to sessions** keeps it in Audial-AI's sessions, and **Web page**, **Text**, **VTT**, **SRT** or
**JSON** export it. Until there is something to save and the box is ticked the buttons stay off,
and the note under them says why. If another Kandha window starts a session, this window's
**Save to sessions**, VTT, SRT and JSON turn off and the note says so; the web page and text
files still keep everything on this screen. Saving a practicum transcript with a real client
needs supervisor and ethics approval.

In the Kandha window, exports are saved to your **Downloads** folder; if the name is taken the
new file gets " (2)", " (3)" and so on, and if a file cannot be saved a warning says why. In a
browser tab, exports go wherever the browser saves downloads.

**How accurate is this?** opens the tone model's measured numbers and limits. The estimates
are learned from acted American English and have not been tested on Indian English or Hindi
speakers or in real seminars.

## Closing Kandha, and what it keeps

Closing the Kandha window stops listening, as Pause does, and lets an export that is still
being saved finish (up to about ten seconds) before the window lets go of the page and the
microphone. Opening Kandha again from Audial-AI makes a new window. When you close the Audial-AI
window, it first asks whether to save its own unsaved transcript (Cancel changes nothing); then
Kandha closes before Audial-AI.

The Kandha window keeps its settings (name, theme, caption size, microphone, vocabulary and
similar) in one file on this computer, `kandha/page-settings.json` in Audial-AI's data folder
(`%LOCALAPPDATA%\AccessibilityAI` on Windows), never audio or transcripts; a browser tab keeps
them in the browser. Kandha remembers the microphone by its name, so the choice survives a
restart.

## Privacy

Audio never leaves the computer: the microphone feeds the voice engine in the page and
Audial-AI's Whisper model over the loopback address only. The one exception is your choice:
in a browser tab, the opt-in **Let the browser's own speech service caption when Whisper is not
installed** (off by default) lets the browser caption, and the browser may send the audio to its
maker's servers; the status line then says *browser captions*. No recording is kept, and a
transcript is kept only when you tick the consent box and save. The stole link carries taps, pad
presses and battery level, never audio or words. There is no telemetry.
