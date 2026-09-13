"""Cursor 대화에서 식단·러닝 기록을 data.json에 넣기 위한 헬퍼."""
from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any, Dict, Optional

from src.services import analyze_meal_text_priority
from src.storage import append_run_log, load_data, upsert_diet_log


def ingest_meal_text(
    meal_text: str,
    log_date: Optional[str] = None,
    analyze: bool = True,
    macros: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """말로 풀어서 준 하루 식단을 저장한다. 날짜 기본값은 오늘."""
    day = log_date or date.today().isoformat()
    notes = "Cursor 대화에서 저장"
    if macros is None and analyze:
        data = load_data()
        result = analyze_meal_text_priority(
            meal_text=meal_text,
            nutrition_targets=data.get("profile", {}).get("nutrition_targets", {}),
            recent_diet_logs=data.get("diet_logs", []),
        )
        macros = {
            "kcal": float(result.get("kcal", 0) or 0),
            "carb_g": float(result.get("carb_g", 0) or 0),
            "protein_g": float(result.get("protein_g", 0) or 0),
            "fat_g": float(result.get("fat_g", 0) or 0),
            "sugar_g": float(result.get("sugar_g", 0) or 0),
        }
        notes = str(result.get("notes") or notes)
    elif macros is None:
        macros = {"kcal": 0, "carb_g": 0, "protein_g": 0, "fat_g": 0, "sugar_g": 0}
    upsert_diet_log(day, meal_text, macros, notes)
    return {"date": day, "macros": macros, "feedback": notes}


def ingest_run(
    *,
    log_date: Optional[str] = None,
    distance_km: float = 0.0,
    pace: str = "",
    duration_min: float = 0.0,
    calories_kcal: float = 0.0,
    cadence_spm: int = 0,
    elevation_gain_m: float = 0.0,
    rpe: int = 0,
    memo: str = "",
) -> Dict[str, Any]:
    day = log_date or date.today().isoformat()
    append_run_log(
        log_date=day,
        distance_km=float(distance_km or 0),
        pace=str(pace or ""),
        duration_min=float(duration_min or 0),
        calories_kcal=float(calories_kcal or 0),
        cadence_spm=int(cadence_spm or 0),
        elevation_gain_m=float(elevation_gain_m or 0),
        rpe=int(rpe or 0),
        memo=memo or "Cursor 대화에서 저장",
    )
    return {"date": day, "distance_km": float(distance_km or 0)}


def _main() -> None:
    parser = argparse.ArgumentParser(description="식단/러닝 기록 추가")
    sub = parser.add_subparsers(dest="cmd", required=True)

    meal = sub.add_parser("meal", help="식단 텍스트 저장")
    meal.add_argument("text", help="먹은 것 설명")
    meal.add_argument("--date", default="")
    meal.add_argument("--no-ai", action="store_true")

    run = sub.add_parser("run", help="러닝 기록 저장")
    run.add_argument("--date", default="")
    run.add_argument("--km", type=float, required=True)
    run.add_argument("--pace", default="")
    run.add_argument("--min", type=float, default=0.0)
    run.add_argument("--kcal", type=float, default=0.0)
    run.add_argument("--cadence", type=int, default=0)
    run.add_argument("--elev", type=float, default=0.0)
    run.add_argument("--rpe", type=int, default=0)
    run.add_argument("--memo", default="")

    args = parser.parse_args()
    if args.cmd == "meal":
        out = ingest_meal_text(args.text, log_date=args.date or None, analyze=not args.no_ai)
    else:
        out = ingest_run(
            log_date=args.date or None,
            distance_km=args.km,
            pace=args.pace,
            duration_min=args.min,
            calories_kcal=args.kcal,
            cadence_spm=args.cadence,
            elevation_gain_m=args.elev,
            rpe=args.rpe,
            memo=args.memo,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
