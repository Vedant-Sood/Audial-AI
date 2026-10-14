"""Speaker-OOF stacking of speech embeddings and acoustic emotion features."""
import numpy as np
from scipy.special import log_softmax

from .ssl_features import pool_layers
from .train import raw_logits

FEATURE_VERSION="ssl-acoustic-stack-v1"


def member_input(member,global_features,acoustic):
    if member["kind"]=="acoustic":return acoustic
    return pool_layers(global_features,member["layers"],member["aggregation"])


def meta_features(members,global_features,acoustic):
    logits=[log_softmax(raw_logits(m["model"],member_input(m,global_features,acoustic)),axis=1) for m in members]
    return np.concatenate([*logits,acoustic[:,-15:]],axis=1).astype(np.float32)


class FusionStackHead:
    def __init__(self,members,meta_model,feature_shape,acoustic_count=183):
        self.members=members;self.meta_model=meta_model
        self.feature_shape=tuple(feature_shape);self.acoustic_count=acoustic_count
        self.classes_=meta_model.classes_
        if any(not np.array_equal(m["model"].classes_,self.classes_) for m in members):
            raise ValueError("Stacking classifier class orders differ.")

    def _features(self,X):
        X=np.asarray(X,dtype=np.float32)
        size=int(np.prod(self.feature_shape))
        if X.ndim!=2 or X.shape[1]!=size+self.acoustic_count:
            raise ValueError("Stacking feature dimensions differ.")
        return meta_features(self.members,X[:,:size].reshape((-1,*self.feature_shape)),X[:,size:])

    def decision_function(self,X):return self.meta_model.decision_function(self._features(X))
    def predict_proba(self,X):return self.meta_model.predict_proba(self._features(X))
    def predict(self,X):return self.meta_model.predict(self._features(X))
