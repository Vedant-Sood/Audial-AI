# Exact unpublished starting point

The correct prior session is **Set up Audial-AI**, thread
`01a13368-eb86-76cd-9003-48a769e5c07b`. Its final handoff identifies:

- `AccessibilityAI-unpublished-changes-2026-10-14.zip`, 538,130 bytes.
- SHA256 `a0ea9fc59f29f66e1a4f4c6c1291e22b8982c1d2154a8ab59c8ada2c6dd5db33`.
- Unpublished head `0e062394f146add0abde5bd3ef9bd006a0274b61`.
- Five commits after public `65f6bc0609b4e7dfde31873ed5d18d8ea3e46368`:
  `6823b9d`, `81bf831`, `3e7f2ff`, `f3501a0`, `0e06239`.

The archive contains a patch series, source, reports and documentation. It
excludes raw corpora, feature caches and unpromoted model weights. The recorded
best research result was 902/1078 (83.6735%), below the 85% target; no research
checkpoint was promoted. Historical checks were 88 Python and 14 Node tests.
These are prior-session results, not current validation.

**The archive itself is still absent from the mounted Library and attachments.**
The original `/workspace/artifacts/...zip` path belongs to the earlier isolated
workspace. Fetching its full commit from origin failed with **not our ref**.
The public branch still starts at 65f6bc0. No reset, force push, replacement with
an older archive, or claim of a completed merge has been made.

A verified baseline bundle and the available partial prior-session source diffs
are preserved under `/workspace/shared/downloads`. The source-diff JSON contains
file changes only, excludes private reasoning, and explicitly marks truncation;
it cannot substitute for the five complete patches. Independent 0.5.0 work is
isolated on `codex/audial-desktop-upgrade` in the existing checkout. The missing
patch series must be recovered, hash-checked and ordinarily merged before this
branch is called the complete continuation of the unpublished work.
