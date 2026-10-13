import numpy as np
import pytest
import torch
from app.inference.sign import resample_sequence, validate_checkpoint
from training.networks import SignGRU


def test_sequence_resampling():
    x = np.zeros((3, 196), np.float32)
    x[-1] = 1
    sampled = resample_sequence(x, 48)
    assert sampled.shape == (48, 196)
    assert (sampled[0] == 0).all() and (sampled[-1] == 1).all()


def test_sign_network_forward_and_backward():
    torch.set_num_threads(2)
    model = SignGRU(hidden_size=16, layers=1, classes=4)
    # Shape/gradient verification only; this is not a training accuracy experiment.
    scores = model(torch.zeros(2, 12, 196))
    assert scores.shape == (2, 4)
    scores.sum().backward()
    assert model.head[-1].weight.grad is not None


def test_asl_checkpoint_rejected():
    with pytest.raises(ValueError):
        validate_checkpoint({"task":"sign", "labels":["a"], "model":{}, "language":"ASL"}, "sign")


def test_nonfinite_sequence_rejected():
    with pytest.raises(ValueError):
        resample_sequence(np.full((4, 196), np.nan))
