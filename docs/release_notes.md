AccessibilityAI 0.3.0 simplifies the desktop navigation and audio source controls,
adds persistent color assignments for every supported voice emotion, and makes
native ISL phrase playback accept multiline text, Hindi aliases and subtitle files.
Unsupported text remains visible in playback order. Local audio/video decoding
also accepts common compressed formats.

This release includes a Windows portable packaging tool, a native executable
build workflow, and a speaker-disjoint Indian voice training and evaluation path.

The included emotion weights remain the previous CREMA-D baseline. Their
historical full-test accuracy is 51.6%; 85–90% accuracy on Indian voices has not
been demonstrated. ISL coverage remains the four bundled phrases, with support
for importing licensed vocabularies. Fluent, arbitrary sentence translation is
not implemented. See the user guide and model documentation for measured scope.
