from typing import Any, Dict

from src.services import analyze_meal_with_ai
from src.storage import append_run_log, load_data, upsert_diet_log


def diet_analyze_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = load_data()
    meal_text = payload.get("meal_text", "")
    log_date = payload.get("date", "")
    nutrition_targets = data.get("profile", {}).get("nutrition_targets", {})
    recent_diet_logs = data.get("diet_logs", [])

    result = analyze_meal_with_ai(
        meal_text=meal_text,
        nutrition_targets=nutrition_targets,
        recent_diet_logs=recent_diet_logs,
    )
    macros = {
        "kcal": float(result.get("kcal", 0)),
        "carb_g": float(result.get("carb_g", 0)),
        "protein_g": float(result.get("protein_g", 0)),
        "fat_g": float(result.get("fat_g", 0)),
        "sugar_g": float(result.get("sugar_g", 0)),
    }
    if log_date:
        upsert_diet_log(log_date, meal_text, macros, "")
    return {"macros": macros}


def run_log_upsert_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    append_run_log(
        log_date=str(payload.get("date", "")),
        distance_km=float(payload.get("distance_km", 0)),
        pace=str(payload.get("pace", "")),
        duration_min=float(payload.get("duration_min", 0)),
        calories_kcal=float(payload.get("calories_kcal", 0)),
        cadence_spm=int(payload.get("cadence_spm", 0)),
        elevation_gain_m=float(payload.get("elevation_gain_m", 0)),
        rpe=int(payload.get("rpe", 0)),
        memo=str(payload.get("memo", "")),
    )
    return {"ok": True}
