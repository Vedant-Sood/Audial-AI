"""Portable classifier voting for independently selected WavLM layers."""
import numpy as np
from scipy.special import softmax
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from .ssl_features import pool_layers
from .train import raw_logits


class SpeakerNuisanceProjection(TransformerMixin, BaseEstimator):
    """Remove dominant between-voice directions learned on training actors.

    Inference needs only the acoustic vector, without a speaker identity or any
    recordings from the test speaker. This is not test-speaker normalization.
    """
    def __init__(self, components=8):
        self.components = components

    def fit(self, X, y=None, groups=None):
        if groups is None or len(groups) != len(X):
            raise ValueError("Training speaker IDs are required for nuisance projection.")
        groups = np.asarray(groups)
        self.center_ = np.asarray(X).mean(axis=0)
        means = np.stack([X[groups == speaker].mean(axis=0)-self.center_ for speaker in np.unique(groups)])
        _, _, basis = np.linalg.svd(means, full_matrices=False)
        self.basis_ = basis[:min(self.components, len(means)-1)]
        self.n_features_in_ = X.shape[1]
        return self

    def transform(self, X):
        return X - ((X-self.center_) @ self.basis_.T) @ self.basis_


class ListenerHead(BaseEstimator):
    """Learn audio-only majority labels, preserving genuine rater ties.

    A clip can have several equally popular listener labels. Independent binary
    losses retain each of these labels; prediction returns one best label.
    """
    def __init__(self, C=0.01, neural=False, seed=42):
        self.C, self.neural, self.seed = C, neural, seed

    def fit(self, X, y):
        self.classes_ = np.array(["angry", "disgust", "fear", "happy", "neutral", "sad"])
        if self.neural:
            self.model_ = MLPClassifier(hidden_layer_sizes=(256,), alpha=1.0,
                batch_size=128, learning_rate_init=0.0005, max_iter=150,
                early_stopping=True, n_iter_no_change=12, random_state=self.seed)
        else:
            self.model_ = OneVsRestClassifier(LogisticRegression(C=self.C, max_iter=1200, random_state=self.seed))
        self.model_.fit(X, y)
        return self

    def decision_function(self, X):
        if hasattr(self.model_, "decision_function"):
            return self.model_.decision_function(X)
        return np.log(np.maximum(self.model_.predict_proba(X), 1e-12))

    def predict(self, X):
        return self.classes_[self.decision_function(X).argmax(axis=1)]


class NumericMLPHead(BaseEstimator):
    """Encode string labels before sklearn's numeric early-stopping scorer."""
    def __init__(self, seed=42, max_iter=150):
        self.seed, self.max_iter = seed, max_iter

    def fit(self, X, y):
        self.classes_, numeric = np.unique(y, return_inverse=True)
        self.model_ = MLPClassifier(hidden_layer_sizes=(256,), alpha=1.0,
            batch_size=min(128,len(X)), learning_rate_init=0.0005,
            max_iter=self.max_iter, early_stopping=True, n_iter_no_change=12,
            random_state=self.seed)
        self.model_.fit(X, numeric)
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X)

    def predict(self, X):
        return self.classes_[self.model_.predict(X)]


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
