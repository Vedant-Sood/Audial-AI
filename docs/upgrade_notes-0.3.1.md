# AccessibilityAI 0.3.1 delivery

ISL is the fixed default across supported inputs, independent of speech language.
The native application and browser share vocabulary selection and the automatic
caption preference. Documents and subtitles use the common text adapter; audio
and video recordings use completed local speech captions. Long valid plans keep
every step, including readable unknown text. Added ISL packs extend bundled signs.

Validation passed 54 Python tests, 14 JavaScript tests, a real browser flow, and
native video → text → pose playback on Linux. Windows CI passed the same source
checks and startup of the packaged native executable. Its native ZIP is published
through the gated release workflow. Device capture and caption speed on the user's
Windows machine remain separate checks; Whisper weights must be installed once.

Shipped ISL coverage remains four phrases. No additional corpus was downloaded
because current cloud egress blocks Zenodo. This is dictionary playback, not fluent
arbitrary ISL sentence translation. The emotion model is unchanged: historical
CREMA-D full-test accuracy 51.6%, with no new Indian-voice benchmark or trained
Indian model. The 85–90% target remains unmet. See isl.md and model_cards.md.

Reusable setup instructions, exact cloud dependencies and required download
hosts are saved in the environment draft. Saving the draft did not apply its
network rules. The workflow uses ordinary read-only validation diagnostics;
repository write permission is scoped to the explicitly requested release job.
