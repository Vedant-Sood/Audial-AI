# Using Audial-AI

## Listen and read

Open **Conversation**, select **Microphone** or **Computer / app audio**, and
click **Start listening**. Pause/resume and Stop control that session. If a caption
model is missing, open **Setup & models** for automatic setup progress and recovery. Speaker labels are optional; leave their backend off for simple captions.

**Open audio / video** processes a local recording instead of opening the
microphone. The Captions tab shows completed words. Voice & emotion shows voice
measurements and optional emotion estimates. Save or export a completed session
as TXT, JSON, CSV, SRT or VTT. Tone estimates never rewrite spoken words.

Set the speech language in Settings. English remains the default. Hindi and
other listed Indian languages use multilingual Whisper; recognition quality
varies by language, model and audio conditions. Settings take effect on the next
session after saving.

## Native Indian Sign Language

Open **Indian Sign Language**, enter text, then click **Display in ISL**. Paste
from the clipboard or click **Open document / subtitles / media**. Text, Markdown,
CSV, HTML, DOCX, text PDF, SRT, VTT and transcript JSON share the same ISL pathway.
Choose a recording to transcribe its audio track into the same display; a caption
model must be installed. You can also listen live on this page.

ISL is the sign-language default regardless of your speech language setting.
**ISL with captions** is enabled at startup and visible on every page. Changing
it persists your preference; explicit typed/document requests still play.
Desktop and browser share the preference and any added vocabulary pack.
Voice & emotion also supplies captions for ISL if a caption model is installed;
otherwise it explains that installation is needed while keeping measurements available.

Use extracts up to 20,000 characters or documents up to 2 MB. Text files must be
UTF-8; DOCX and PDF use their normal formats. Encrypted PDFs and scans need text
copied or extracted by another tool. Oversized input is rejected with a clear
message rather than silently shortened. Longer valid plans retain every step.

Known phrases use the included hand/body poses. For example, **धन्यवाद** and
**शुक्रिया** use the thank-you phrase; **शुभ रात्रि** uses good night. Unknown
content is displayed as **Text · no loaded ISL sign**, in order with known signs.
It remains visible in the input and caption. This is a coverage fallback, not an
ISL translation. Add an appropriately licensed vocabulary using **Add an ISL
vocabulary**. Keep its JSON and media folder together. It extends the bundled
signs; **Use bundled vocabulary** resets the selection. Both displays use the
same pack. [The pack format](isl.md) documents media, sources, licenses and aliases.

Pause, change speed, or enable Reduced motion and advance one frame at a time.
**Float sign display** keeps captions and signs visible above other windows.
The optional webcam controls recognize isolated signs from the small trained
vocabulary; they cannot recognize arbitrary gestures or continuous sentences.

## Emotion color pool

In **Settings**, enable voice emotion estimates and select a color for Angry,
Disgust, Fear, Happy, Neutral, Sad, and Uncertain. **Reset emotion colors** restores
the default pool; **Save settings** persists your choices. The Voice & emotion
badge shows both its color and text, using a readable foreground automatically.
Recorded-level plot colors are separate from emotion colors.

Uncertain means the model lacks enough evidence: silence, clipping, unsuitable
segment length or low confidence. Model confidence is not measured accuracy.
The current emotion model has not reached the requested 85–90% Indian voice
accuracy. Treat its output as an experimental acoustic estimate.

The browser companion has its own color inputs and Save colors button, backed
by the same local settings when launched from the desktop. It sends captured
media only to the local app process. Browser tab/audio support depends on the
browser and Windows capture permissions.

## Files, models and troubleshooting

The normal Setup.exe includes the runtime and starts full catalogue preparation
on first launch. **Setup & models** shows pause/retry/resume and gated requirements.
Models, settings, sessions and logs use `%LOCALAPPDATA%\AccessibilityAI`.
Upgrades/reinstall preserve this data; uninstall keeps it unless you explicitly
choose deletion. Required speech voices are managed by Windows.

A startup failure writes
`%LOCALAPPDATA%\AccessibilityAI\startup-error.log`. If GPU setup fails in a
source installation, use `setup.bat --cpu`. Native CPU and NVIDIA builds are separate; the NVIDIA build also falls back to CPU.
Actual microphone, camera and system-audio availability must be checked on your
Windows computer. Advanced tools → Diagnostics provides device checks; run them
only when you want the app to open those devices.


## Notifications and browser tabs

Warnings appear without blocking your task. Failures remain visible above the
workspace with recovery actions. **Notifications** opens the local history and
occurrence counts; acknowledging an alert does not delete its history. Keyboard
focus has one amber outline. Clicking a control does not leave a dotted frame.
The latest 500 caption rows stay visible; exports contain the complete session.

For browser meetings, enable **Developer mode** on Chrome or Edge's extensions
page, use **Load unpacked** to select the installed `browser-extension` folder,
pin Audial-AI, and invoke its toolbar popup while the desired tab is active.
**Capture this tab** requires that browser gesture. Its LIVE badge and source
title show what is captured. The tab list spans windows; **Open selected tab**
focuses a source so you can invoke its toolbar action. **Stop** releases capture.
Closing tabs, restarting the extension or disconnecting the desktop clears stale
ownership. A normal webpage cannot discover unrelated tabs on its own.

Vocal-expression estimates are optional and may arrive after captions. A changing,
noisy, clipped or low-confidence signal remains uncertain. Word content is never
rewritten. Objective pitch/recorded level continue even if the optional model
fails. The released WavLM head is prepared automatically without replacing an
explicit existing selection; the original bundled head remains available through
developer activation tools. See the current model evaluation for limitations.

## Voices, queue and tone cues (Kandha's voice engine)

In the browser companion, open **Voices, queue and tone cues · Kandha**.

- **Colour and arrow per voice** (on by default). The live panel shows who is speaking, and
  transcript rows carry the same colour. When diarization is off, exports name captions
  *Voice 1*, *Voice 2*… instead of *Unattributed*. Colours last for one session; they are not
  identities.
- **Tone cues** (off by default). *Voice rose*, *voice softened*, *hesitation* and *long
  silence* flash on the panel. Tick **Vibrate this device for cues** on Android to feel them.
  The Sanket wrist band is retired; the full Kandha app taps them on the Kandha Stole.
- **Compare with their usual voice** (off by default). This is an experimental estimate such
  as *more intense than usual* or *softer, sad-sounding*. An emotion is named, in your
  vocal-expression colours, only when the engine is at least 80% sure, and only after it has heard
  that person a few times. It is a hint to look again, not a fact about feelings.
- **I want to speak** (or **Q**) lights a strip across the top of the live panel. It floats
  with **Float this panel**, so you can hold it up in a seminar.

These preferences also apply when you capture a tab with the extension. **Open Kandha full
screen** (or the extension's **Open Sanket** button, whose `/sanket/` address now opens Kandha)
opens the full Kandha app: lecture, seminar and practicum modes, seats, the virtual stole, a
session review, and English or हिन्दी captions from this computer's Whisper model. See
[sanket.md](sanket.md) for how the voice engine works and how accurate it is, and the
[Kandha user guide](kandha/USER_GUIDE.md) for the app.
