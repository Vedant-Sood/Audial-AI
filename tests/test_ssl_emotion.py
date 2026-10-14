"""Checks for leakage, confidence calibration and safe model activation."""
import copy
import hashlib
import json

import joblib
import numpy as np
import pytest
from scipy.special import softmax

from accessibilityai_upgrade.predict import EmotionModel
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, pool_layers, PooledEncoder
from scripts.train_ssl_emotion import validate_manifest, cluster_interval
from scripts.activate_emotion import activate
from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble


def manifest():
    labels = ["angry", "disgust", "fear", "happy", "neutral", "sad"]
    names = ["train", "validation", "calibration_fit", "calibration_policy", "test"]
    return {
        "splits": {name: {"speakers": [str(i)], "clips": 6} for i, name in enumerate(names)},
        "clips": [{"speaker_id": str(i), "partition": name, "label": label,
                   "file": f"{i}-{label}.wav", "sha256": f"{i}-{label}"}
                  for i, name in enumerate(names) for label in labels],
    }


def test_edited_manifests_cannot_share_speakers_or_audio():
    original = manifest()
    validate_manifest(original)
    leaked = copy.deepcopy(original)
    leaked["splits"]["test"]["speakers"] = ["0"]
    with pytest.raises(ValueError, match="Speaker leakage"):
        validate_manifest(leaked)
    leaked = copy.deepcopy(original)
    leaked["clips"][-1]["sha256"] = leaked["clips"][0]["sha256"]
    with pytest.raises(ValueError, match="Identical audio"):
        validate_manifest(leaked)
    leaked = copy.deepcopy(original)
    leaked["clips"][-1]["speaker_id"] = "0"
    with pytest.raises(ValueError, match="assigned partition"):
        validate_manifest(leaked)


def test_layer_pooling_is_identical_for_batches_and_single_utterances():
    features = np.random.default_rng(7).normal(size=(4, 12, 2, 16)).astype(np.float32)
    pooled = pool_layers(features, [4, 6, 8])
    assert pooled.shape == (4, 32)
    for i in range(4):
        np.testing.assert_array_equal(pooled[i], pool_layers(features[i], [4, 6, 8]))
    with pytest.raises(ValueError, match="layer"):
        pool_layers(features, [0])
    concat = pool_layers(features, [4, 6, 8], "concat")
    assert concat.shape == (4, 96)
    np.testing.assert_array_equal(concat[0], pool_layers(features[0], [4, 6, 8], "concat"))


def test_temperature_calibration_preserves_full_test_predicted_labels():
    logits = np.random.default_rng(42).normal(size=(50, 6))
    for temperature in [0.05, 0.3, 1.0, 10.0, 100.0]:
        np.testing.assert_array_equal(softmax(logits / temperature, axis=1).argmax(1), logits.argmax(1))


def test_interval_resamples_speakers_instead_of_independent_clips():
    # One perfect and one incorrect speaker: cluster uncertainty stays large,
    # regardless of how many nearly identical clips each speaker contributes.
    labels = np.repeat("happy", 200)
    predicted = np.r_[np.repeat("happy", 100), np.repeat("sad", 100)]
    speakers = np.repeat(["a", "b"], 100)
    assert cluster_interval(labels, predicted, speakers) == [0.0, 1.0]


def test_ssl_silence_abstains_before_opening_a_large_encoder(tmp_path):
    path = tmp_path / "emotion.joblib"
    joblib.dump({"feature_version": FEATURE_VERSION, "feature_count": 2048}, path)
    model = EmotionModel(path)
    assert model.predict_samples(np.zeros(16000, np.float32))["reason"] == "insufficient_audio"
    assert model.encoder is None


def test_changed_encoder_is_rejected_before_loading_weights(tmp_path):
    checkpoint = tmp_path / "encoder.pth"
    checkpoint.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        PooledEncoder("WAVLM_LARGE", checkpoint, "0" * 64)


def test_activation_rejects_corrupted_encoder_without_changing_selection(tmp_path):
    folder = tmp_path / "model"
    folder.mkdir()
    model = folder / "emotion.joblib"
    model.write_bytes(b"not unpickled during verification")
    report = {"model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
              "feature_version": FEATURE_VERSION, "encoder": "WAVLM_LARGE",
              "encoder_sha256": "0" * 64, "split_summary": {"test": {"speakers": ["a"]}},
              "test": {"accuracy": 0.75}, "dataset": "CREMA-D", "target_met": False}
    (folder / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    (folder / "encoder.pth").write_bytes(b"changed")
    from app.utils.paths import data_root
    selection = data_root() / "emotion_selection.json"
    selection.write_text('{"previous": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        activate(folder)
    assert json.loads(selection.read_text(encoding="utf-8")) == {"previous": True}


class FixedHead:
    classes_ = np.array(["happy", "sad"])

    def __init__(self, logits):
        self.logits = np.array(logits)

    def decision_function(self, X):
        return np.tile(self.logits, (len(X), 1))


def test_voting_serialization_preserves_class_order_and_predictions(tmp_path):
    members = [{"model": FixedHead([3, -1]), "layers": [1], "aggregation": "mean"},
               {"model": FixedHead([2, 1]), "layers": [2], "aggregation": "mean"}]
    model = LayerHeadEnsemble(members, (2, 2, 4))
    features = np.arange(32).reshape(2, 2, 2, 4)
    X = pool_layers(features, [1, 2], "concat")
    path = tmp_path / "ensemble.joblib"
    joblib.dump(model, path)
    restored = joblib.load(path)
    assert restored.predict(X).tolist() == ["happy", "happy"]
    np.testing.assert_allclose(restored.predict_proba(X), model.predict_proba(X))
    members[1]["model"].classes_ = np.array(["sad", "happy"])
    with pytest.raises(ValueError, match="class order"):
        LayerHeadEnsemble(members, (2, 2, 4))
