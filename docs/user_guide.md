# Using AccessibilityAI

## Listen and read

Open **Conversation**, select **Microphone** or **Computer / app audio**, and
click **Start listening**. Pause/resume and Stop control that session. If a caption
model is missing, the app explains which model to install in Advanced tools →
Models. Speaker labels are optional; leave their backend off for simple captions.

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

The portable ZIP includes Python and native runtime files. Extract every folder;
do not move only its BAT launcher. Caption models are installed on request and
stored under `%LOCALAPPDATA%\AccessibilityAI`. Settings and sessions are local.

If launch fails, use **Diagnose startup.bat**. A startup failure also writes
`%LOCALAPPDATA%\AccessibilityAI\startup-error.log`. If GPU setup fails in a
source installation, use `setup.bat --cpu`. The portable distribution uses CPU.
Actual microphone, camera and system-audio availability must be checked on your
Windows computer. Advanced tools → Diagnostics provides device checks; run them
only when you want the app to open those devices.
