AccessibilityAI 0.4.1 upgrades voice emotion analysis with a newly trained
WavLM-Large ensemble. It scores 80.8% overall accuracy on 814 CREMA-D clips from
ten held-out actors, compared with 51.6% for the original calibrated baseline.
Confidence-accepted estimates reach 88.8% accuracy at 81.9% coverage; remaining
clips display uncertain. The requested 85–90% accuracy across all clips remains
unmet, and natural conversation accuracy has not been measured.

Install **WavLM voice emotion (CREMA-D)** from **Advanced tools → Models**, then
enable voice emotion estimates in Settings. The native ZIP includes the trained
classifier. Its original ~1.3 GB encoder downloads explicitly once, is checked
against SHA-256, and is selected for the next session. Allow about 2.7 GB of disk
space for installation and the verified active copy. Inference then runs locally.

The source includes complete data hashes, 97 development comparisons, separate
speaker partitions for selection and calibration, final class metrics,
actor-bootstrap uncertainty, model activation checks, and a separate documented
listener-rating experiment. The original model remains available as a fallback.
Windows release publication is gated on regression and executable startup checks.
