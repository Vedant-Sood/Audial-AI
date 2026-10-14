"""Portable classifier voting for independently selected WavLM layers."""
import numpy as np
from scipy.special import softmax

from .ssl_features import pool_layers
from .train import raw_logits


class LayerHeadEnsemble:
    """Uniform soft voting; every member was fitted on training speakers only."""
    def __init__(self, members, feature_shape):
        self.members = members
        self.feature_shape = tuple(feature_shape)
        self.classes_ = members[0]["model"].classes_
        if any(not np.array_equal(member["model"].classes_, self.classes_) for member in members):
            raise ValueError("Ensemble class order differs.")

    def predict_proba(self, X):
        features = np.asarray(X).reshape((-1, *self.feature_shape))
        probabilities = []
        for member in self.members:
            pooled = pool_layers(features, member["layers"], member["aggregation"])
            probabilities.append(softmax(raw_logits(member["model"], pooled), axis=1))
        return np.stack(probabilities).mean(0)

    def decision_function(self, X):
        return np.log(np.maximum(self.predict_proba(X), 1e-12))

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(1)]
