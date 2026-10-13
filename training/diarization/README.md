# Enrolled-speaker head research pipeline

This optional component trains a fixed enrolled-speaker vocabulary from preprocessed 192-dimensional ECAPA embeddings. No enrolled-speaker head was trained in this update. Live speaker IDs use pretrained ECAPA and session centroid matching; that is separate from this identity head.

Provide a finite NPZ with X, y, split, labels and groups plus a real-data provenance JSON as required by training.runner.load_data. Retain the declared enrolled vocabulary across train/val/test. The original CSV preprocessing module was unavailable in the uploads.

    python -m training.diarization.train --config training/configs/diarization_rtx4060.yaml
    python -m training.diarization.evaluate --checkpoint training/experiments/diarization_local/best.pt --data datasets/diarization.npz --output enrolled_test.json
    python -m training.diarization.inference --checkpoint training/experiments/diarization_local/best.pt --ecapa-path YOUR_MODEL_FOLDER/ecapa --audio YOUR_REAL_AUDIO.wav

An enrolled-speaker score does not establish DER or overlap performance. Use reference meeting turns with scripts.evaluate_speech for declared corpus evaluation, and read the scoring limits in docs/local_training.md.
