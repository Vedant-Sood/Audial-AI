"""RBF speech classifier with reusable development kernels.

Only training support vectors are saved. Inference builds the public sklearn
precomputed-kernel input; unused training columns are zero because libsvm reads
support columns only. No private sklearn model attributes are modified.
"""
import numpy as np
from sklearn.metrics.pairwise import euclidean_distances
from scipy.special import softmax


class CachedRBFHead:
    def __init__(self, preprocessing, classifier, support_vectors, gamma, train_count):
        self.preprocessing = preprocessing
        self.classifier = classifier
        self.support_vectors = np.asarray(support_vectors, dtype=np.float32)
        self.gamma = float(gamma)
        self.train_count = int(train_count)
        self.classes_ = classifier.classes_

    def decision_function(self, X):
        values = self.preprocessing.transform(X).astype(np.float32)
        distances = euclidean_distances(values, self.support_vectors, squared=True)
        support = np.exp(-self.gamma*distances)
        kernel = np.zeros((len(values), self.train_count), dtype=np.float64)
        kernel[:, self.classifier.support_] = support
        return self.classifier.decision_function(kernel)

    def predict_proba(self, X):
        return softmax(self.decision_function(X),axis=1)

    def predict(self, X):
        return self.classes_[self.decision_function(X).argmax(1)]
