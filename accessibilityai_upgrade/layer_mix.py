"""Trainable layer mixtures on a frozen, checksum-verified speech encoder.

Only the small emotion head is optimized. Actor identities are used for
training-only style augmentation and are neither supplied nor inferred at run
time. Published heads serialize numerical state, not a second speech encoder.
"""
import numpy as np
import torch
from torch import nn
from scipy.special import softmax


class LayerMixNetwork(nn.Module):
    def __init__(self, shape, hidden=256, dropout=0.4, branches=2):
        super().__init__()
        layers, statistics, width = shape
        self.shape = tuple(shape)
        initial = torch.full((branches, layers), -2.0)
        for i in range(branches):
            start, end = ((3, 15) if i == 0 else (11, layers))
            initial[i, start:end] = 0
        self.layer_logits = nn.Parameter(initial)
        self.network = nn.Sequential(
            nn.Linear(branches*statistics*width, hidden), nn.LayerNorm(hidden),
            nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden, 6),
        )

    def forward(self, X):
        X = X.reshape(-1, self.shape[0], self.shape[1]*self.shape[2])
        mixed = torch.einsum("nlw,bl->nbw", X, self.layer_logits.softmax(dim=1))
        return self.network(mixed.flatten(1))


class LayerMixHead:
    """Portable six-class head, using the same preprocessing as development."""
    def __init__(self, feature_shape, mean, scale, state, hidden, dropout, branches, classes):
        self.feature_shape = tuple(feature_shape)
        self.mean = np.asarray(mean, dtype=np.float32)
        self.scale = np.asarray(scale, dtype=np.float32)
        self.state = {k:np.asarray(v) for k,v in state.items()}
        self.hidden, self.dropout, self.branches = hidden, dropout, branches
        self.classes_ = np.asarray(classes)
        self._network = None

    def __getstate__(self):
        result = dict(self.__dict__)
        result["_network"] = None
        return result

    def decision_function(self, X):
        if self._network is None:
            self._network = LayerMixNetwork(self.feature_shape, self.hidden, self.dropout, self.branches)
            self._network.load_state_dict({k:torch.from_numpy(v.copy()) for k,v in self.state.items()}, strict=True)
            self._network.eval().requires_grad_(False)
        values = (np.asarray(X, dtype=np.float32)-self.mean)/self.scale
        with torch.inference_mode():
            return self._network(torch.from_numpy(values)).numpy()

    def predict_proba(self, X):
        return softmax(self.decision_function(X), axis=1)

    def predict(self, X):
        return self.classes_[self.decision_function(X).argmax(1)]
