import copy
import random

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, Dataset

from config import (
    MODEL_PRED_COL,
    MODEL_REG_LABEL_COL,
    TORCH_BATCH_SIZE,
    TORCH_DROPOUT,
    TORCH_EPOCHS,
    TORCH_HIDDEN_DIMS,
    TORCH_LR,
    TORCH_PATIENCE,
    TORCH_WEIGHT_DECAY,
)

from torch_models import Alpha158MLP


def set_torch_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class AlphaDataset(Dataset):
    def __init__(self, x, y_reg, y_cls):
        self.x = torch.tensor(x, dtype=torch.float32)
        self.y_reg = torch.tensor(y_reg, dtype=torch.float32)
        self.y_cls = torch.tensor(y_cls, dtype=torch.float32)

    def __len__(self):
        return len(self.x)

    def __getitem__(self, idx):
        return self.x[idx], self.y_reg[idx], self.y_cls[idx]


def split_train_valid_by_date(train_df: pd.DataFrame, valid_ratio=0.2):
    dates = sorted(train_df["date"].unique())

    if len(dates) < 50:
        return train_df.copy(), train_df.copy()

    split_idx = int(len(dates) * (1 - valid_ratio))
    split_date = dates[split_idx]

    inner_train_df = train_df[train_df["date"] < split_date].copy()
    valid_df = train_df[train_df["date"] >= split_date].copy()

    return inner_train_df, valid_df


def make_xy(df: pd.DataFrame, feature_cols, scaler=None, fit_scaler=False):
    x = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    x = x.astype(np.float32)

    if fit_scaler:
        scaler = StandardScaler()
        x = scaler.fit_transform(x).astype(np.float32)
    else:
        x = scaler.transform(x).astype(np.float32)

    y_reg = df[MODEL_REG_LABEL_COL].values.astype(np.float32)
    y_cls = df["future_5d_up"].values.astype(np.float32)

    return x, y_reg, y_cls, scaler


def train_one_epoch(model, loader, optimizer, device):
    model.train()

    mse_loss = torch.nn.MSELoss()
    bce_loss = torch.nn.BCEWithLogitsLoss()

    total_loss = 0.0

    for x, y_reg, y_cls in loader:
        x = x.to(device)
        y_reg = y_reg.to(device)
        y_cls = y_cls.to(device)

        pred_reg, pred_logit = model(x)

        loss_reg = mse_loss(pred_reg, y_reg)
        loss_cls = bce_loss(pred_logit, y_cls)

        loss = loss_reg + loss_cls

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * len(x)

    return total_loss / len(loader.dataset)


@torch.no_grad()
def evaluate_loss(model, loader, device):
    model.eval()

    mse_loss = torch.nn.MSELoss()
    bce_loss = torch.nn.BCEWithLogitsLoss()

    total_loss = 0.0

    for x, y_reg, y_cls in loader:
        x = x.to(device)
        y_reg = y_reg.to(device)
        y_cls = y_cls.to(device)

        pred_reg, pred_logit = model(x)

        loss_reg = mse_loss(pred_reg, y_reg)
        loss_cls = bce_loss(pred_logit, y_cls)

        loss = loss_reg + loss_cls
        total_loss += loss.item() * len(x)

    return total_loss / len(loader.dataset)


@torch.no_grad()
def predict_torch_mlp(model, scaler, df: pd.DataFrame, feature_cols, device=None):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = model.to(device)
    model.eval()

    x = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    x = scaler.transform(x).astype(np.float32)

    x_tensor = torch.tensor(x, dtype=torch.float32)
    loader = DataLoader(x_tensor, batch_size=1024, shuffle=False)

    pred_reg_list = []
    pred_prob_list = []

    for batch_x in loader:
        batch_x = batch_x.to(device)

        pred_score, pred_logit = model(batch_x)

        pred_score = pred_score.detach().cpu().numpy()
        up_prob = torch.sigmoid(pred_logit).detach().cpu().numpy()

        pred_reg_list.append(pred_score)
        pred_prob_list.append(up_prob)

    pred_score = np.concatenate(pred_reg_list)
    up_prob = np.concatenate(pred_prob_list)

    return pred_score, up_prob


def train_torch_mlp(train_df: pd.DataFrame, test_df: pd.DataFrame, feature_cols):
    set_torch_seed(42)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Torch] device = {device}")

    inner_train_df, valid_df = split_train_valid_by_date(train_df, valid_ratio=0.2)

    x_train, y_train_reg, y_train_cls, scaler = make_xy(
        inner_train_df,
        feature_cols,
        scaler=None,
        fit_scaler=True
    )

    x_valid, y_valid_reg, y_valid_cls, _ = make_xy(
        valid_df,
        feature_cols,
        scaler=scaler,
        fit_scaler=False
    )

    train_dataset = AlphaDataset(x_train, y_train_reg, y_train_cls)
    valid_dataset = AlphaDataset(x_valid, y_valid_reg, y_valid_cls)

    train_loader = DataLoader(
        train_dataset,
        batch_size=TORCH_BATCH_SIZE,
        shuffle=True,
        drop_last=False
    )

    valid_loader = DataLoader(
        valid_dataset,
        batch_size=TORCH_BATCH_SIZE,
        shuffle=False,
        drop_last=False
    )

    model = Alpha158MLP(
        input_dim=len(feature_cols),
        hidden_dims=TORCH_HIDDEN_DIMS,
        dropout=TORCH_DROPOUT
    ).to(device)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=TORCH_LR,
        weight_decay=TORCH_WEIGHT_DECAY
    )

    best_valid_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    patience_count = 0

    for epoch in range(1, TORCH_EPOCHS + 1):
        train_loss = train_one_epoch(model, train_loader, optimizer, device)
        valid_loss = evaluate_loss(model, valid_loader, device)

        print(
            f"[Torch][Epoch {epoch:03d}] "
            f"train_loss={train_loss:.6f} valid_loss={valid_loss:.6f}"
        )

        if valid_loss < best_valid_loss:
            best_valid_loss = valid_loss
            best_state = copy.deepcopy(model.state_dict())
            patience_count = 0
        else:
            patience_count += 1

        if patience_count >= TORCH_PATIENCE:
            print(f"[Torch] early stopping at epoch {epoch}")
            break

    model.load_state_dict(best_state)

    test_pred_df = test_df.copy()

    pred_score, up_prob = predict_torch_mlp(
        model=model,
        scaler=scaler,
        df=test_pred_df,
        feature_cols=feature_cols,
        device=device
    )

    test_pred_df[MODEL_PRED_COL] = pred_score
    test_pred_df["up_prob"] = up_prob
    test_pred_df["pred_cls"] = (test_pred_df["up_prob"] >= 0.5).astype(int)

    score_rmse = mean_squared_error(
        test_pred_df[MODEL_REG_LABEL_COL],
        test_pred_df[MODEL_PRED_COL],
    ) ** 0.5

    acc = accuracy_score(
        test_pred_df["future_5d_up"],
        test_pred_df["pred_cls"]
    )

    try:
        auc = roc_auc_score(
            test_pred_df["future_5d_up"],
            test_pred_df["up_prob"]
        )
    except Exception:
        auc = np.nan

    base_metrics = {
        "rmse": float(score_rmse),
        "score_rmse": float(score_rmse),
        "regression_target": MODEL_REG_LABEL_COL,
        "prediction_column": MODEL_PRED_COL,
        "accuracy": float(acc),
        "auc": float(auc) if not np.isnan(auc) else None,
        "best_valid_loss": float(best_valid_loss),
        "device": device,
    }

    return model, scaler, test_pred_df, base_metrics
