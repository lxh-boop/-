import torch.nn as nn


class Alpha158MLP(nn.Module):
    def __init__(self, input_dim, hidden_dims=(256, 128, 64), dropout=0.2):
        super().__init__()

        self.model_config = {
            "input_dim": input_dim,
            "hidden_dims": list(hidden_dims),
            "dropout": dropout,
        }

        layers = []
        prev_dim = input_dim

        for hidden_dim in hidden_dims:
            layers.append(nn.Linear(prev_dim, hidden_dim))
            layers.append(nn.BatchNorm1d(hidden_dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            prev_dim = hidden_dim

        self.backbone = nn.Sequential(*layers)

        self.reg_head = nn.Linear(prev_dim, 1)
        self.cls_head = nn.Linear(prev_dim, 1)

    def forward(self, x):
        h = self.backbone(x)
        reg_out = self.reg_head(h).squeeze(-1)
        cls_logit = self.cls_head(h).squeeze(-1)
        return reg_out, cls_logit