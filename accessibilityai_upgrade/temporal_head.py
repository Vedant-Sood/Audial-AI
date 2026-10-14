"""Emotion heads combining an utterance's speech frames and global statistics."""
import numpy as np
import torch
from torch import nn
from scipy.special import softmax

FEATURE_VERSION="ssl-global-temporal-v1"


class TemporalNetwork(nn.Module):
    def __init__(self,global_shape,bins=64,width=128,dropout=0.4):
        super().__init__()
        self.global_shape=tuple(global_shape)
        self.bins=bins
        layers,statistics,channels=global_shape
        initial=torch.full((2,layers),-2.0)
        initial[0,3:15]=0;initial[1,11:]=0
        self.layer_logits=nn.Parameter(initial)
        self.global_stem=nn.Sequential(nn.Linear(2*statistics*channels,64),
            nn.LayerNorm(64),nn.GELU(),nn.Dropout(dropout))
        self.frame_stem=nn.Sequential(nn.Linear(channels,width),nn.LayerNorm(width),nn.GELU())
        self.context=nn.Sequential(nn.Conv1d(width,width,3,padding=1,groups=8),nn.GELU(),
            nn.Conv1d(width,width,3,padding=2,dilation=2,groups=8),nn.GELU())
        self.attention=nn.Sequential(nn.Linear(width,64),nn.Tanh(),nn.Linear(64,1))
        self.classifier=nn.Sequential(nn.Linear(2*width+64,128),nn.LayerNorm(128),
            nn.GELU(),nn.Dropout(dropout),nn.Linear(128,6))

    def forward(self,global_values,frames):
        values=global_values.reshape(-1,self.global_shape[0],self.global_shape[1]*self.global_shape[2])
        mixed=torch.einsum("nlw,bl->nbw",values,self.layer_logits.softmax(1)).flatten(1)
        global_embedding=self.global_stem(mixed)
        local=self.frame_stem(frames)
        local=local+self.context(local.transpose(1,2)).transpose(1,2)
        weights=self.attention(local).softmax(1)
        mean=(weights*local).sum(1)
        std=((weights*(local-mean[:,None,:]).square()).sum(1)+1e-5).sqrt()
        return self.classifier(torch.cat([global_embedding,mean,std],dim=1))


class TemporalHead:
    def __init__(self,global_shape,bins,global_mean,global_scale,frame_mean,frame_scale,
                 state,width,dropout,classes):
        self.global_shape=tuple(global_shape);self.bins=bins
        self.global_mean=np.asarray(global_mean,dtype=np.float32)
        self.global_scale=np.asarray(global_scale,dtype=np.float32)
        self.frame_mean=np.asarray(frame_mean,dtype=np.float32)
        self.frame_scale=np.asarray(frame_scale,dtype=np.float32)
        self.state={k:np.asarray(v) for k,v in state.items()}
        self.width,self.dropout=width,dropout
        self.classes_=np.asarray(classes);self._network=None

    def __getstate__(self):
        result=dict(self.__dict__);result["_network"]=None;return result

    def decision_function(self,X):
        X=np.asarray(X,dtype=np.float32)
        size=int(np.prod(self.global_shape))
        global_values=(X[:,:size]-self.global_mean)/self.global_scale
        frames=X[:,size:].reshape(-1,self.bins,self.global_shape[-1])
        frames=(frames-self.frame_mean)/self.frame_scale
        if self._network is None:
            self._network=TemporalNetwork(self.global_shape,self.bins,self.width,self.dropout)
            self._network.load_state_dict({k:torch.from_numpy(v.copy()) for k,v in self.state.items()},strict=True)
            self._network.eval().requires_grad_(False)
        with torch.inference_mode():
            return self._network(torch.from_numpy(global_values),torch.from_numpy(frames)).numpy()

    def predict_proba(self,X):return softmax(self.decision_function(X),axis=1)
    def predict(self,X):return self.classes_[self.decision_function(X).argmax(1)]


class ProbabilityVoteHead:
    """Validation-selected probability voting across compatible numerical heads."""
    def __init__(self,members,weights=None):
        self.members=members
        self.weights=np.asarray(weights if weights is not None else np.ones(len(members)),dtype=float)
        self.weights/=self.weights.sum()
        self.classes_=members[0].classes_
        if any(not np.array_equal(m.classes_,self.classes_) for m in members):
            raise ValueError("Ensemble class order differs.")
    def predict_proba(self,X):return sum(w*m.predict_proba(X) for w,m in zip(self.weights,self.members))
    def decision_function(self,X):return np.log(np.maximum(self.predict_proba(X),1e-12))
    def predict(self,X):return self.classes_[self.predict_proba(X).argmax(1)]
