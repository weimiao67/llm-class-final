"""Pure parts of the SageMaker training job and its launcher (no GPU libraries or AWS needed)."""

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


train = load("train_job", ROOT / "training" / "job" / "train.py")
launch = load("launch_train", ROOT / "scripts" / "launch_train.py")

SYSTEM = {"role": "system", "content": "planner prompt"}
USER = {"role": "user", "content": "Rank Utah cities by rent growth in 2024"}
TARGET = {"role": "assistant", "content": '{"call": {"tool": "analyze", "plan": {}}}'}


def test_prompt_completion_split_trains_only_the_final_turn():
    bad = {"role": "assistant", "content": '{"call": {"tool": "analyze"}}'}
    feedback = {"role": "user", "content": "TOOL RESULT: {...}"}
    rec = train.to_prompt_completion({"messages": [SYSTEM, USER, bad, feedback, TARGET]})
    assert rec["completion"] == [TARGET]
    assert rec["prompt"] == [SYSTEM, USER, bad, feedback]  # the rejected call is context only


def test_records_must_end_with_the_assistant_turn():
    with pytest.raises(ValueError, match="must end with the assistant"):
        train.to_prompt_completion({"messages": [SYSTEM, USER]})


def test_read_records_samples_deterministically(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"messages": [SYSTEM, USER | {"content": str(i)}, TARGET]})
            for i in range(20)
        )
    )
    a = train.read_records(path, num_samples=5, seed=1)
    assert len(a) == 5 and a == train.read_records(path, num_samples=5, seed=1)
    assert len(train.read_records(path)) == 20


def test_job_defaults_match_the_design_recipe():
    args = train.parse_args([])
    assert args.model_name == "Qwen/Qwen2.5-3B-Instruct"
    assert (args.lora_r, args.lora_alpha, args.learning_rate) == (16, 32, 2e-4)
    assert args.max_length >= 2048 and not args.no_merge
    assert set(train.LORA_TARGET_MODULES) == {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    }


def test_summary_reports_dev_loss_per_epoch():
    args = train.parse_args([])
    history = [
        {"loss": 1.2, "epoch": 0.5},
        {"eval_loss": 0.4, "epoch": 1.0},
        {"loss": 0.3, "epoch": 1.5},
        {"eval_loss": 0.35, "epoch": 2.0},
    ]
    s = train.summarize_run(history, 600.0, 12 * 1024**3, {"data_version": "abc"}, args)
    assert (s["first_logged_loss"], s["final_logged_loss"]) == (1.2, 0.3)
    assert s["dev_loss_by_epoch"] == [
        {"epoch": 1.0, "eval_loss": 0.4},
        {"epoch": 2.0, "eval_loss": 0.35},
    ]
    assert s["data_version"] == "abc" and s["peak_vram_gb"] == 12.0


# ---- launcher --------------------------------------------------------------------------------


def write_data(path: Path, version: str) -> Path:
    path.mkdir(parents=True)
    for name in ("train.jsonl", "dev.jsonl"):
        (path / name).write_text("{}\n")
    (path / "manifest.json").write_text(json.dumps({"data_version": version}))
    return path


def test_data_dir_must_be_complete_and_match_its_version(tmp_path):
    good = write_data(tmp_path / "076967313a", "076967313a")
    assert launch.check_data_dir(good)["data_version"] == "076967313a"
    renamed = write_data(tmp_path / "other", "076967313a")
    with pytest.raises(SystemExit, match="holds data version"):
        launch.check_data_dir(renamed)
    (good / "dev.jsonl").unlink()
    with pytest.raises(SystemExit, match="missing"):
        launch.check_data_dir(good)


def ns(**kw):
    base = {"smoke": False, "name": None, "epochs": None, "learning_rate": None, "lora_r": None}
    return argparse.Namespace(**(base | kw))


def test_hyperparameters_pass_only_overrides():
    assert launch.hyperparameters(ns()) == {}  # train.py's defaults are the run's settings
    assert launch.hyperparameters(ns(epochs=3.0, learning_rate=1e-4)) == {
        "epochs": 3.0,
        "learning-rate": 1e-4,
    }
    smoke = launch.hyperparameters(ns(smoke=True))
    assert smoke["num-samples"] == 32 and smoke["epochs"] == 1


def test_job_names():
    assert launch.job_name(ns()) == "final-wm-qwen-lora"
    assert launch.job_name(ns(smoke=True)) == "final-wm-qwen-lora-smoke"
    assert launch.job_name(ns(name="ep3")) == "final-wm-qwen-lora-ep3"


def test_job_source_dir_is_self_contained():
    files = {p.name for p in (ROOT / launch.SOURCE_DIR).iterdir()}
    assert {"train.py", "requirements.txt"} <= files
    source = (ROOT / launch.SOURCE_DIR / "train.py").read_text()
    assert "from training" not in source and "from agent" not in source
