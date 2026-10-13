import torch
from torch import nn


class SignGRU(nn.Module):
    def __init__(self, input_dim=196, hidden_size=96, layers=2, dropout=0.2, classes=4, **ignored):
        super().__init__()
        self.input = nn.Sequential(nn.Linear(input_dim, hidden_size), nn.LayerNorm(hidden_size), nn.GELU())
        self.gru = nn.GRU(hidden_size, hidden_size, layers, batch_first=True, bidirectional=True,
                          dropout=dropout if layers > 1 else 0)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden_size * 2, classes))

    def forward(self, values):
        sequence, _ = self.gru(self.input(values))
        return self.head(sequence.mean(dim=1))


class FeatureMLP(nn.Module):
    def __init__(self, input_dim=80, hidden_size=96, dropout=0.2, classes=8, **ignored):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(input_dim, hidden_size), nn.LayerNorm(hidden_size), nn.GELU(),
                                 nn.Dropout(dropout), nn.Linear(hidden_size, hidden_size // 2), nn.GELU(),
                                 nn.Linear(hidden_size // 2, classes))

    def forward(self, values):
        return self.net(values)


def make_model(task, config, classes):
    if task == "sign":
        return SignGRU(classes=classes, **config)
    if task not in {"prosody", "diarization"}:
        raise ValueError("Unknown training task.")
    return FeatureMLP(classes=classes, **config)
