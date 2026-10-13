# Current verification

Run `python -m pytest -q`, `npm test`, and `python -m app.main --smoke-test`.
The current release report is `docs/validation-0.3.1.json`. Browser endpoint tests
need local socket access; headless Linux uses `QT_QPA_PLATFORM=offscreen`.
These checks do not record microphones or cameras.

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
