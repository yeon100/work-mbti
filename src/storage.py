import json
import os
import uuid
from datetime import date
from typing import Any, Dict, List

from src.config import DATA_FILE
from src.default_run_plan_md import DEFAULT_CUSTOM_RUN_PLAN_MD

PLAN_UNDO_MAX = 20


def _default_data() -> Dict[str, Any]:
    return {
        "profile": {
            "name": "",
            "goal_race_date": "2026-12-01",
            "goal_marathon_time": "04:30:00",
            "custom_run_plan_md": DEFAULT_CUSTOM_RUN_PLAN_MD,
            "custom_run_plan_md_undo_stack": [],
            "nutrition_targets": {
                "kcal": 2000,
                "carb_g": 250,
                "protein_g": 120,
                "fat_g": 60,
                "sugar_g": 40,
            },
        },
        "diet_logs": [],
        "run_logs": [],
        "plans": [],
    }


def ensure_data_file() -> None:
    folder = os.path.dirname(DATA_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(_default_data(), f, ensure_ascii=False, indent=2)


def load_data() -> Dict[str, Any]:
    ensure_data_file()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    patched = False
    prof = data.get("profile", {})
    if "custom_run_plan_md" not in prof:
        prof["custom_run_plan_md"] = DEFAULT_CUSTOM_RUN_PLAN_MD
        data["profile"] = prof
        patched = True
    if "custom_run_plan_md_undo_stack" not in prof or not isinstance(
        prof.get("custom_run_plan_md_undo_stack"), list
    ):
        prof["custom_run_plan_md_undo_stack"] = []
        data["profile"] = prof
        patched = True

    for lg in data.get("run_logs", []):
        if isinstance(lg, dict) and not lg.get("id"):
            lg["id"] = str(uuid.uuid4())
            patched = True

    if patched:
        save_data(data)
    return data


def push_run_plan_undo(profile: Dict[str, Any], previous_md: str) -> None:
    """플랜 저장 직전 스냅샷을 실행취소 스택에 넣는다."""
    stack = profile.get("custom_run_plan_md_undo_stack")
    if not isinstance(stack, list):
        stack = []
    stack.append(str(previous_md or ""))
    profile["custom_run_plan_md_undo_stack"] = stack[-PLAN_UNDO_MAX:]


def save_data(data: Dict[str, Any]) -> None:
    ensure_data_file()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def upsert_diet_log(
    log_date: str,
    meal_text: str,
    macros: Dict[str, float],
    feedback: str,
) -> None:
    data = load_data()
    logs: List[Dict[str, Any]] = data.get("diet_logs", [])
    record = {
        "date": log_date,
        "meal_text": meal_text,
        "macros": macros,
        "feedback": feedback,
        "updated_at": date.today().isoformat(),
    }
    logs = [x for x in logs if x.get("date") != log_date]
    logs.append(record)
    logs.sort(key=lambda x: x.get("date", ""))
    data["diet_logs"] = logs
    save_data(data)


def append_run_log(
    log_date: str,
    distance_km: float,
    pace: str,
    duration_min: float,
    calories_kcal: float,
    cadence_spm: int,
    elevation_gain_m: float,
    rpe: int,
    memo: str,
) -> None:
    """같은 날짜에 여러 건 기록 가능(추가만 하며 덮어쓰지 않음)."""
    data = load_data()
    logs: List[Dict[str, Any]] = data.get("run_logs", [])
    record = {
        "id": str(uuid.uuid4()),
        "date": log_date,
        "distance_km": distance_km,
        "pace": pace,
        "duration_min": duration_min,
        "calories_kcal": calories_kcal,
        "cadence_spm": cadence_spm,
        "elevation_gain_m": elevation_gain_m,
        "rpe": rpe,
        "memo": memo,
        "updated_at": date.today().isoformat(),
    }
    logs.append(record)
    logs.sort(key=lambda x: (str(x.get("date", "")), str(x.get("id", ""))))
    data["run_logs"] = logs
    save_data(data)


def delete_diet_logs_by_indices(indices: List[int]) -> int:
    """diet_logs에서 지정 인덱스 행을 제거한다. indices는 0..len-1."""
    if not indices:
        return 0
    data = load_data()
    logs: List[Dict[str, Any]] = data.get("diet_logs", [])
    want = set(int(i) for i in indices if 0 <= int(i) < len(logs))
    if not want:
        return 0
    before = len(logs)
    data["diet_logs"] = [l for j, l in enumerate(logs) if j not in want]
    save_data(data)
    return before - len(data["diet_logs"])


def delete_run_logs_by_indices(indices: List[int]) -> int:
    if not indices:
        return 0
    data = load_data()
    logs: List[Dict[str, Any]] = data.get("run_logs", [])
    want = set(int(i) for i in indices if 0 <= int(i) < len(logs))
    if not want:
        return 0
    before = len(logs)
    data["run_logs"] = [l for j, l in enumerate(logs) if j not in want]
    save_data(data)
    return before - len(data["run_logs"])
