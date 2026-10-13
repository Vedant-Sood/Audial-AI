AccessibilityAI 0.3.1 makes Indian Sign Language the default across typed text,
clipboard/page selections, documents, subtitles, live speech captions and local
recordings. Desktop and browser share the selected ISL vocabulary and automatic
caption preference. Long plans retain every sign/text step, and unknown passages
remain readable in order. DOCX, text PDF, CSV and HTML join the existing inputs.
Local dictionary videos show the original signer in the native displays; failed
media falls back to text and later signs continue.

The desktop retains the simpler navigation, readable audio controls and persistent
emotion color pool introduced in 0.3.0. Tests cover default ISL routing, document
extraction, shared packs, mixed scripts, long queues and playback recovery. The
Windows build workflow gates native ZIP publication on target-platform checks.

The shipped vocabulary still contains four phrases; no extra sign corpus was
downloaded in this cloud. This is dictionary playback, not fluent arbitrary ISL
sentence translation. The bundled emotion weights remain the CREMA-D baseline
(historical full-test accuracy 51.6%); 85–90% Indian voice accuracy is unmeasured
and has not been achieved. Consult docs/validation-0.3.1.json for current results
and Windows packaging status, and docs/isl.md for input and vocabulary details.
