# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

from app_version import APP_NAME


project_root = Path.cwd()
include_optional_ml = os.environ.get("STOCK_DAILY_INCLUDE_OPTIONAL_ML", "0") == "1"

root_modules = [
    "alpha158",
    "app_version",
    "backtest",
    "backtest_engine",
    "backtest_metrics",
    "backtest_rebalance",
    "calibration",
    "confidence_scoring",
    "config",
    "data_local",
    "data_tushare",
    "daily_incremental_update",
    "event_rules",
    "llm_client",
    "llm_explainer",
    "llm_prompts",
    "local_config",
    "market_context",
    "model_factory",
    "model_zoo_backend",
    "news_data",
    "news_db_sync",
    "news_features",
    "rag_indexer",
    "rag_retriever",
    "rag_store",
    "rag_utils",
    "ranking_schema",
    "risk_scoring",
    "runtime_paths",
    "scheduler_manager",
    "universe",
]

project_packages = [
    "app",
    "agent",
    "core",
    "database",
    "evaluation",
    "model_backends",
    "news_mapping",
    "pipelines",
    "portfolio",
    "rag",
    "scheduler",
    "scoring",
    "skills",
]

hiddenimports = list(root_modules)
for package in project_packages:
    hiddenimports += collect_submodules(package)

hiddenimports += [
    "model_zoo.metadata",
    "model_zoo.ohlcv_windows",
    "model_zoo.registry",
]
if include_optional_ml:
    hiddenimports += collect_submodules("external_models")
    hiddenimports += collect_submodules("model_zoo.adapters")

hiddenimports += [
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.web.cli",
    "webview",
    "webview.platforms.edgechromium",
]

datas = [
    ("app.py", "."),
    (".streamlit/config.toml", ".streamlit"),
]

for directory in [
    "database/migrations",
    "database/seed",
    "resources",
    "model_zoo/configs",
]:
    path = project_root / directory
    if path.exists():
        datas.append((str(path), directory))

for source_dir, target_dir in [
    ("data", "bundled_seed/data"),
    ("models", "bundled_seed/models"),
    ("outputs", "bundled_seed/outputs"),
]:
    path = project_root / source_dir
    if path.exists():
        datas.append((str(path), target_dir))

datas += collect_data_files("streamlit")
datas += collect_data_files("plotly")
datas += collect_data_files("rfc3987_syntax")
datas += copy_metadata("streamlit")

excludes = [
    "tests",
    "pytest",
    "pytest_cov",
    "pytest_mock",
    "pytest_playwright",
    "playwright",
]
if not include_optional_ml:
    excludes += [
        "accelerate",
        "chronos",
        "datasets",
        "jax",
        "jaxlib",
        "lightning",
        "momentfm",
        "pytorch_lightning",
        "tensorboard",
        "tensorflow",
        "timesfm",
        "torch",
        "torchaudio",
        "torchvision",
        "transformers",
        "uni2ts",
    ]


a = Analysis(
    ["desktop_launcher.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
