from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch


INPUT_HINT_KEYWORDS = [
    "input",
    "feature",
    "seq",
    "window",
    "lookback",
    "d_model",
    "dim",
    "hidden",
    "num_layers",
    "n_layers",
    "n_features",
    "num_features",
    "freq",
    "horizon",
    "pred",
]


def _safe_repr(value: Any, max_len: int = 300) -> str:
    try:
        text = repr(value)
    except Exception as exc:
        text = f"<repr failed: {exc}>"

    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _load_checkpoint(path: Path) -> Any:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _find_state_dict(checkpoint: Any) -> tuple[str, dict[str, Any] | None]:
    if isinstance(checkpoint, dict):
        for key in [
            "state_dict",
            "model_state_dict",
            "model",
            "net",
            "network",
            "module",
            "model_state",
        ]:
            value = checkpoint.get(key)
            if isinstance(value, dict) and value:
                tensor_like_count = sum(hasattr(v, "shape") for v in value.values())
                if tensor_like_count > 0:
                    return key, value

        tensor_like_count = sum(hasattr(v, "shape") for v in checkpoint.values())
        if tensor_like_count > 0:
            return "<checkpoint_is_state_dict>", checkpoint

    return "", None


def _summarize_mapping(name: str, value: Any) -> None:
    if not isinstance(value, dict):
        print(f"{name}: {type(value).__name__} = {_safe_repr(value)}")
        return

    print(f"{name}: dict with {len(value)} keys")
    sample_keys = list(value.keys())[:30]
    print(f"{name} sample keys: {sample_keys}")

    input_related = {}
    for key, item in value.items():
        key_text = str(key).lower()
        if any(hint in key_text for hint in INPUT_HINT_KEYWORDS):
            input_related[str(key)] = _safe_repr(item)

    if input_related:
        print(f"{name} input-related fields:")
        print(json.dumps(input_related, ensure_ascii=False, indent=2))


def inspect_checkpoint(path: str) -> dict[str, Any]:
    ckpt_path = Path(path)
    report: dict[str, Any] = {
        "path": str(ckpt_path),
        "exists": ckpt_path.exists(),
        "ok": False,
    }

    if not ckpt_path.exists():
        report["error"] = f"checkpoint not found: {ckpt_path}"
        return report

    try:
        checkpoint = _load_checkpoint(ckpt_path)
    except Exception as exc:
        report["error"] = f"torch.load failed: {type(exc).__name__}: {exc}"
        return report

    report["ok"] = True
    report["checkpoint_type"] = type(checkpoint).__name__

    if isinstance(checkpoint, dict):
        keys = list(checkpoint.keys())
        report["checkpoint_key_count"] = len(keys)
        report["checkpoint_keys"] = [str(k) for k in keys[:50]]
        report["has_state_dict"] = any(
            k in checkpoint
            for k in [
                "state_dict",
                "model_state_dict",
                "model",
                "net",
                "network",
                "module",
                "model_state",
            ]
        )
        report["has_optimizer_state_dict"] = "optimizer_state_dict" in checkpoint
        report["has_model_state_dict"] = "model_state_dict" in checkpoint
        for key in ["config", "cfg", "args", "epoch", "best_metric", "best_score", "metric"]:
            report[f"has_{key}"] = key in checkpoint
            if key in checkpoint:
                report[key] = _safe_repr(checkpoint[key], max_len=1000)
    else:
        report["checkpoint_repr"] = _safe_repr(checkpoint, max_len=1000)

    state_dict_key, state_dict = _find_state_dict(checkpoint)
    report["state_dict_container_key"] = state_dict_key

    if state_dict:
        state_keys = [str(k) for k in list(state_dict.keys())]
        report["state_dict_key_count"] = len(state_keys)
        report["state_dict_first_20_keys"] = state_keys[:20]
        report["state_dict_first_30_keys"] = state_keys[:30]
        tensor_shapes = {}
        for key, value in list(state_dict.items())[:60]:
            if hasattr(value, "shape"):
                tensor_shapes[str(key)] = list(value.shape)
        report["state_dict_first_tensor_shapes"] = tensor_shapes
        report["model_structure_guess"] = _infer_structure_from_state_dict(state_dict)

    input_related = {}
    if isinstance(checkpoint, dict):
        for key, value in checkpoint.items():
            if hasattr(value, "shape"):
                continue

            key_text = str(key).lower()
            if any(hint in key_text for hint in INPUT_HINT_KEYWORDS):
                input_related[str(key)] = _safe_repr(value, max_len=1000)

            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if hasattr(sub_value, "shape"):
                        continue

                    sub_key_text = str(sub_key).lower()
                    if any(hint in sub_key_text for hint in INPUT_HINT_KEYWORDS):
                        input_related[f"{key}.{sub_key}"] = _safe_repr(
                            sub_value,
                            max_len=1000,
                        )

    report["input_related_fields"] = input_related

    summary_path = ckpt_path.parent / "summary.json"
    report["adjacent_summary_json_found"] = summary_path.exists()
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            report["summary_model_name"] = summary.get("model_name")
            report["summary_run_name"] = summary.get("run_name")
            report["summary_best_epoch"] = summary.get("best_epoch")
            report["summary_best_score"] = summary.get("best_score")
            args = summary.get("args") or {}
            report["summary_args_available"] = bool(args)
            report["summary_input_output_guess"] = {
                "model_name": args.get("model_name", summary.get("model_name")),
                "d_feat": args.get("d_feat"),
                "seq_len": args.get("seq_len"),
                "gate_input_start_index": args.get("gate_input_start_index"),
                "gate_input_end_index": args.get("gate_input_end_index"),
                "input_shape": (
                    f"[N, {args.get('seq_len')}, {args.get('gate_input_end_index')}]"
                    if args.get("seq_len") and args.get("gate_input_end_index")
                    else None
                ),
                "output_dim": 1,
                "label_handling": {
                    "train_label_zscore": args.get("train_label_zscore"),
                    "eval_loss_label_zscore": args.get("eval_loss_label_zscore"),
                    "monitor": args.get("monitor"),
                },
            }
        except Exception as exc:
            report["adjacent_summary_json_error"] = f"{type(exc).__name__}: {exc}"
    return report


def _infer_structure_from_state_dict(state_dict: dict[str, Any]) -> dict[str, Any]:
    guess: dict[str, Any] = {}

    def shape_of(key: str):
        value = state_dict.get(key)
        return list(value.shape) if hasattr(value, "shape") else None

    feature_gate_shape = shape_of("feature_gate.trans.weight")
    if feature_gate_shape and len(feature_gate_shape) == 2:
        guess["stock_feature_count_from_feature_gate"] = int(feature_gate_shape[0])
        guess["market_context_count_from_feature_gate"] = int(feature_gate_shape[1])

    input_proj_shape = (
        shape_of("feat_to_model.input_proj.weight")
        or shape_of("feat_to_model.weight")
        or shape_of("feat_to_model.0.weight")
    )
    if input_proj_shape and len(input_proj_shape) == 2:
        guess["d_model_from_input_proj"] = int(input_proj_shape[0])
        guess["d_feat_from_input_proj"] = int(input_proj_shape[1])

    pred_head_shape = shape_of("pred_head.weight") or shape_of("out.2.weight")
    if pred_head_shape and len(pred_head_shape) == 2:
        guess["output_dim_from_pred_head"] = int(pred_head_shape[0])
        guess["pred_head_input_dim"] = int(pred_head_shape[1])

    temporal_keys = [str(k) for k in state_dict if str(k).startswith("temporal_unet.")]
    guess["has_temporal_unet"] = bool(temporal_keys)
    guess["temporal_unet_key_count"] = len(temporal_keys)

    if "stock_feature_count_from_feature_gate" in guess and "market_context_count_from_feature_gate" in guess:
        end = guess["stock_feature_count_from_feature_gate"] + guess["market_context_count_from_feature_gate"]
        guess["likely_input_feature_dim"] = end
        guess["likely_input_shape"] = "[N, seq_len, %d]" % end

    return guess


def print_report(report: dict[str, Any]) -> None:
    print("=" * 80)
    print("External Model Checkpoint Inspection")
    print("=" * 80)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("=" * 80)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Path to .pth checkpoint")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print_report(inspect_checkpoint(args.path))
