# Current verification

Run `python -m pytest -q`, `npm test`, and `python -m app.main --smoke-test`.
The current release report is `docs/validation-0.3.json`. Browser endpoint tests
need local socket access; headless Linux uses `QT_QPA_PLATFORM=offscreen`.
These checks do not record microphones or cameras.

The original uploaded benchmark, trained weights and historical experiment records
remain in the repository for provenance. They do not establish a new Indian voice
accuracy result. Windows device capture, target-machine speed, and signer assessment
require testing on the target machine.
