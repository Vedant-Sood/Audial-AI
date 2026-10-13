# Isolated Indian Sign Language research model

The new model uses restored features from 84 real INCLUDE videos, four source labels, 48 frames and 196 pose features. Its reconstructed bidirectional GRU has 298,660 parameters. The source implementation was unavailable, so it was retrained from scratch. Signer identities were unavailable; the bundled split is clip-disjoint only.

Run from the project root in the installed environment:

    python -m training.sign_recognition.train --config training/configs/sign_lights_upgrade.yaml
    python -m training.sign_recognition.evaluate --checkpoint models/research/sign.pt --data datasets/sign.npz --output sign_test.json
    python -m training.sign_recognition.inference --checkpoint models/research/sign.pt --features assets/sign_evaluation.npy

Use training/configs/sign_rtx4060.yaml for an unmeasured local CUDA profile. Resume with --resume PATH/latest.pt; pause/stop behavior is in docs/local_training.md. Expansion needs licensed ISL media, signer annotations and the shared MediaPipe feature schema. The original sign preprocessing CLI was unavailable in the uploads; the supplied NPZ can be used directly to reproduce this training run.

New measured result: 16/16 test clips correct, macro-F1 1.0. The original experiment's 15/16 result remains a historical source record. Softmax is uncalibrated and cannot reliably reject every unknown sign. Data and derived assets retain INCLUDE CC-BY-4.0 attribution in LICENSE_NOTICES.md.
