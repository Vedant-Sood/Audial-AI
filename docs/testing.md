# Current verification

Run `python -m pytest -q`, `npm test`, and `python -m app.main --smoke-test`.
The current release report is [0.5.0 validation](validation-0.5.0.md). Browser endpoint tests
need local socket access; headless Linux uses `QT_QPA_PLATFORM=offscreen`.
These checks do not record microphones or cameras.

After complete model setup, run `python -m app.main --verify-inference` for
imported-file ASR/expression/prosody and `--verify-live-inference` for the same
models through the streaming capture loop. Both block socket connections. The
streaming check sends the supplied licensed recording in real-time 20-ms PCM
blocks; it validates VAD, asynchronous captions/expression, objective prosody,
and Stop/resource release. It does not validate a physical capture device or
the browser transport.

`python -m scripts.verify_browser --browser <executable> --native-host <worker.exe>
--output <directory>` separately exercises real Chromium/Edge extension APIs,
the OS toolbar capture grant, native PCM, source identity/switching, reload,
suspension/restoration, disconnect/reconnect and cleanup. Generated tones verify
the actual selected source; this transport-only check deliberately replaces ASR.
The fast browser workflow packages the product native host independently. The
full release workflow runs it against the complete desktop worker executable.
Managed extension restrictions remain enforced; a policy block is not a pass.

The original uploaded benchmark, trained weights and historical experiment records
remain in the repository for provenance. They do not establish a new Indian voice
accuracy result. Windows device capture, target-machine speed, and signer assessment
require testing on the target machine.

`tests/test_isl_inputs.py` covers the fixed ISL default, old-settings migration,
shared pack selection, mixed scripts/symbols, genuine video byte ranges, all
document adapters, input limits, long plans, and recovery from invalid pose media.
Browser tests exercise text/pose ordering, pause, manual motion and local video
references. Native startup/video checks use the bundled source-labelled assets;
they do not establish signer-reviewed sentence translation accuracy.

The Windows workflow preserves failed-check output in standard artifacts,
summaries and bounded error annotations. Validation uses read-only repository
permissions. Native releases require Windows tests and executable startup to pass.
