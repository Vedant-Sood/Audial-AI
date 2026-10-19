"""Checks for leakage, confidence calibration and safe model activation."""
import copy
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from scipy.special import softmax

from accessibilityai_upgrade.predict import EmotionModel
from accessibilityai_upgrade.ssl_features import FEATURE_VERSION, pool_layers, PooledEncoder
from scripts.train_ssl_emotion import validate_manifest, cluster_interval
from scripts.activate_emotion import activate
from accessibilityai_upgrade.emotion_heads import LayerHeadEnsemble, SpeakerNuisanceProjection, NumericMLPHead


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


class RecordingHead:
    classes_ = np.array(["angry","disgust","fear","happy","neutral","sad"])

    def decision_function(self,X):
        self.seen=np.asarray(X).copy()
        return np.tile(np.arange(6),(len(X),1))


def test_fusion_runtime_appends_exact_training_acoustic_features(tmp_path,monkeypatch):
    from accessibilityai_upgrade import ssl_features
    from accessibilityai_upgrade.audio import extract_features
    global_values=np.arange(192,dtype=np.float32).reshape(24,2,4)
    class Encoder:
        def __init__(self,*args,**kwargs):pass
        def extract(self,samples,max_layer=None):
            assert max_layer==24
            return global_values
    monkeypatch.setattr(ssl_features,"PooledEncoder",Encoder)
    path=tmp_path/"emotion.joblib"
    joblib.dump({"feature_version":"ssl-acoustic-stack-v1","encoder":"WAVLM_LARGE",
        "encoder_file":"encoder.pth","encoder_sha256":"0"*64,"precision":"bfloat16","cpu_threads":4,
        "layers":list(range(1,25)),"aggregation":"concat","model":RecordingHead(),"temperature":1,
        "classes":RecordingHead.classes_.tolist(),"threshold":0,"feature_count":192+183},path)
    samples=(0.2*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
    model=EmotionModel(path);prediction=model.predict_samples(samples)
    acoustic,_=extract_features(samples)
    expected=np.concatenate([global_values.ravel(),acoustic])
    np.testing.assert_array_equal(model.bundle["model"].seen[0],expected)
    assert prediction["tone"]=="sad" and len(prediction["probabilities"])==6


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


def test_speaker_projection_needs_no_test_speaker_identity():
    # Identity controls the first coordinate; emotion the second. Training
    # speakers receive identical emotion distributions, as in CREMA-D.
    X = np.array([[-10., -1], [-10., 1], [10., -1], [10., 1]])
    transform = SpeakerNuisanceProjection(1).fit(X, groups=["a", "a", "b", "b"])
    unseen = np.array([[20., -1], [20., 1]])
    np.testing.assert_allclose(transform.transform(unseen), [[0., -1], [0., 1]], atol=1e-12)
    with pytest.raises(ValueError, match="speaker IDs"):
        SpeakerNuisanceProjection().fit(X)


def test_neural_early_stopping_accepts_real_string_emotion_labels():
    labels=np.repeat(["angry","disgust","fear","happy","neutral","sad"],30)
    X=np.random.default_rng(4).normal(size=(len(labels),8)).astype(np.float32)
    with pytest.warns(UserWarning,match="Maximum iterations"):
        model=NumericMLPHead(max_iter=2).fit(X,labels)
    assert set(model.predict(X[:10])).issubset(set(labels))
    assert model.predict_proba(X[:10]).shape == (10,6)


def test_layer_mixture_survives_serialization_with_identical_logits(tmp_path):
    import torch
    from accessibilityai_upgrade.layer_mix import LayerMixNetwork, LayerMixHead
    torch.manual_seed(7)
    net = LayerMixNetwork((24,2,4),hidden=16,dropout=0.5).eval()
    state = {k:v.detach().numpy().copy() for k,v in net.state_dict().items()}
    mean = np.arange(192,dtype=np.float32)/100
    scale = np.linspace(0.5,2,192,dtype=np.float32)
    classes = ["angry","disgust","fear","happy","neutral","sad"]
    head = LayerMixHead((24,2,4),mean,scale,state,16,0.5,2,classes)
    X = np.random.default_rng(9).normal(size=(5,192)).astype(np.float32)
    with torch.inference_mode():
        expected = net(torch.from_numpy((X-mean)/scale)).numpy()
    path = tmp_path/"layer-mix.joblib"
    joblib.dump(head,path)
    restored = joblib.load(path)
    np.testing.assert_allclose(restored.decision_function(X),expected,atol=1e-6)
    np.testing.assert_allclose(restored.predict_proba(X).sum(1),1,atol=1e-6)
    np.testing.assert_array_equal(restored.classes_,classes)
    np.testing.assert_allclose(restored.decision_function(X),restored.decision_function(X),atol=0)


def test_cached_kernel_predictions_equal_full_kernel_with_only_support_vectors(tmp_path):
    from sklearn.svm import SVC
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics.pairwise import euclidean_distances
    from accessibilityai_upgrade.kernel_head import CachedRBFHead
    rng=np.random.default_rng(8)
    X=rng.normal(size=(120,12)).astype(np.float32)
    y=np.repeat(["angry","disgust","fear","happy","neutral","sad"],20)
    pre=StandardScaler().fit(X)
    A=pre.transform(X).astype(np.float32)
    gamma=0.02
    model=SVC(C=10,kernel="precomputed",break_ties=True).fit(np.exp(-gamma*euclidean_distances(A,squared=True)),y)
    head=CachedRBFHead(pre,model,A[model.support_],gamma,len(A))
    unseen=rng.normal(size=(10,12)).astype(np.float32)
    expected=model.decision_function(np.exp(-gamma*euclidean_distances(pre.transform(unseen),A,squared=True)))
    path=tmp_path/"kernel.joblib"
    joblib.dump(head,path)
    restored=joblib.load(path)
    np.testing.assert_allclose(restored.decision_function(unseen),expected,atol=1e-6)
    assert restored.predict(unseen).tolist()==model.classes_[expected.argmax(1)].tolist()


def test_temporal_head_uses_matching_global_and_frame_preprocessing_after_serialization(tmp_path):
    import torch
    from accessibilityai_upgrade.temporal_head import TemporalNetwork,TemporalHead
    torch.manual_seed(8)
    shape,bins=(24,2,4),8
    net=TemporalNetwork(shape,bins,width=16,dropout=0.5).eval()
    state={k:v.detach().numpy().copy() for k,v in net.state_dict().items()}
    gm=np.arange(192,dtype=np.float32)/10;gs=np.linspace(1,2,192,dtype=np.float32)
    fm=np.arange(4,dtype=np.float32);fs=np.linspace(1,2,4,dtype=np.float32)
    classes=["angry","disgust","fear","happy","neutral","sad"]
    head=TemporalHead(shape,bins,gm,gs,fm,fs,state,16,0.5,classes)
    X=np.random.default_rng(8).normal(size=(3,192+32)).astype(np.float32)
    with torch.inference_mode():
        expected=net(torch.from_numpy((X[:,:192]-gm)/gs),torch.from_numpy((X[:,192:].reshape(3,8,4)-fm)/fs)).numpy()
    path=tmp_path/"temporal.joblib";joblib.dump(head,path)
    np.testing.assert_allclose(joblib.load(path).decision_function(X),expected,atol=1e-6)


def test_model_page_install_verifies_and_selects_the_evaluated_head(tmp_path, monkeypatch):
    from io import BytesIO
    from app.models import manager, catalogue
    from app.models.download import Asset
    from app.utils.paths import data_root
    from accessibilityai_upgrade.ssl_features import ENCODERS
    root = tmp_path / "source"
    bundled = root / "models" / "emotion-wavlm"
    bundled.mkdir(parents=True)
    head, encoder = b"trusted test head; not unpickled", b"test encoder; not unpickled"
    digest = hashlib.sha256(encoder).hexdigest()
    report = {"model_sha256": hashlib.sha256(head).hexdigest(), "feature_version": FEATURE_VERSION,
              "encoder": "WAVLM_LARGE", "encoder_sha256": digest,
              "split_summary": {"test": {"speakers": ["a"]}}, "test": {"accuracy": 0.8},
              "dataset": "CREMA-D", "target_met": False}
    (bundled / "emotion.joblib").write_bytes(head)
    (bundled / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(catalogue, "project_root", lambda: root)
    monkeypatch.setitem(ENCODERS["WAVLM_LARGE"], "sha256", digest)
    monkeypatch.setattr(catalogue.CatalogueInstaller, "resolve_assets", lambda *args: [Asset("https://example.org/encoder", "encoder.pth", digest, size=len(encoder))])
    monkeypatch.setattr(catalogue.urllib.request, "urlopen", lambda *a, **kw: BytesIO(encoder))
    model_manager = manager.ModelManager(tmp_path / "models")
    model_manager.install("emotion-wavlm", progress=lambda _: None)
    assert model_manager.installed("emotion-wavlm")
    selection = json.loads((data_root() / "emotion_selection.json").read_text(encoding="utf-8"))
    assert selection["test_accuracy"] == 0.8
    assert selection["target_met"] is False
    assert hashlib.sha256(Path(selection["path"]).read_bytes()).hexdigest() == report["model_sha256"]
