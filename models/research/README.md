# Research model artifacts

The current sign.pt is the newly reconstructed/retrained four-label ISL SignGRU. Its model card is sign.json and its experiment is training/experiments/sign_lights_upgrade. It scored 16/16 on the very small supplied clip-disjoint test split; signer independence is unverified and scores are uncalibrated.

The current optional voice-tone model lives in models/emotion/emotion.joblib and was trained on CREMA-D. It is used directly when enabled in Settings.

The research ONNX files and original sign_cloud/prosody_cloud experiment checkpoints were restored from uploads. They are historical artifacts of the original implementation. Their outputs and old reported metrics do not establish performance of the newly reconstructed network. The original prosody best.pt, its data features and its implementation details were not fully available, so no rebuilt prosody.pt is supplied here. No enrolled-speaker head or full sign-translation model was trained in this update.
