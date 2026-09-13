"""식단 탄단지·폭식/단것 패턴, 훈련량 적정도 분석."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.run_plan_parser import extract_month_plan_sections, load_phases_from_profile

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

SWEET_KEYWORDS = [
    "케이크",
    "케익",
    "초콜릿",
    "초코",
    "아이스크림",
    "과자",
    "디저트",
    "사탕",
    "쿠키",
    "도넛",
    "도너츠",
    "생크림",
    "카스테라",
    "마카롱",
    "브라우니",
    "푸딩",
    "젤리",
    "와플",
    "크로플",
    "프라푸치노",
    "프라푸",
    "버블티",
    "밀크티",
    "콜라",
    "사이다",
    "환타",
    "시럽",
    "꿀",
    "설탕",
    "달달",
    "단거",
    "단 거",
    "스위트",
    "티라미수",
    "치즈케이크",
]

BINGE_KEYWORDS = [
    "폭식",
    "야식",
    "배달",
    "치킨",
    "피자",
    "버거",
    "와퍼",
    "라면",
    "2인분",
    "두 인분",
    "많이 먹",
    "참지 못",
    "참지못",
    "무한리필",
    "세트",
    "너겟",
    "튀김",
    "후라이드",
    "족발",
    "보쌈",
    "마라탕",
    "떡볶이",
]


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _parse_hhmm(text: str) -> Optional[int]:
    m = re.search(r"(\d{1,2})\s*[:시]\s*(\d{2})?", text or "")
    if not m:
        return None
    hour = int(m.group(1))
    if hour > 23:
        return None
    return hour


def time_bucket(hour: Optional[int], slot: str = "") -> str:
    if hour is None:
        slot = (slot or "").strip()
        if slot in ("아침",):
            return "아침(05–10시)"
        if slot in ("점심",):
            return "점심(11–15시)"
        if slot in ("저녁",):
            return "저녁(16–20시)"
        if slot in ("간식", "야식"):
            return "야식(21시~)"
        return "시간 미상"
    if 5 <= hour <= 10:
        return "아침(05–10시)"
    if 11 <= hour <= 15:
        return "점심(11–15시)"
    if 16 <= hour <= 20:
        return "저녁(16–20시)"
    return "야식(21시~)"


def _contains_any(text: str, words: List[str]) -> List[str]:
    t = text or ""
    hits: List[str] = []
    for w in words:
        if not w:
            continue
        if w == "2인분":
            if re.search(r"(?<![/\d])2인분", t):
                hits.append(w)
            continue
        if w.lower() in t.lower():
            hits.append(w)
    return hits


def split_meal_slots(meal_text: str) -> List[Dict[str, Any]]:
    """아침/점심/저녁/간식/야식 블록을 시간·본문으로 나눈다."""
    text = (meal_text or "").strip()
    if not text:
        return []
    pattern = re.compile(r"(아침|점심|저녁|간식|야식)\s*(?:\(([^)]*)\))?\s*[:：]\s*")
    matches = list(pattern.finditer(text))
    if not matches:
        hour = _parse_hhmm(text)
        return [
            {
                "slot": "기타",
                "time": "",
                "hour": hour,
                "text": text,
                "bucket": time_bucket(hour, ""),
            }
        ]
    rows: List[Dict[str, Any]] = []
    for i, mm in enumerate(matches):
        start = mm.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        slot = mm.group(1)
        time_raw = (mm.group(2) or "").strip()
        hour = _parse_hhmm(time_raw) or _parse_hhmm(body)
        rows.append(
            {
                "slot": slot,
                "time": time_raw,
                "hour": hour,
                "text": body,
                "bucket": time_bucket(hour, slot),
            }
        )
    return rows


def macro_kcal_split(macros: Dict[str, Any]) -> Dict[str, float]:
    carb = float(macros.get("carb_g", 0) or 0)
    protein = float(macros.get("protein_g", 0) or 0)
    fat = float(macros.get("fat_g", 0) or 0)
    c_kcal = carb * 4.0
    p_kcal = protein * 4.0
    f_kcal = fat * 9.0
    total = c_kcal + p_kcal + f_kcal
    if total <= 0:
        stored = float(macros.get("kcal", 0) or 0)
        return {
            "carb_kcal": 0.0,
            "protein_kcal": 0.0,
            "fat_kcal": 0.0,
            "from_macros": 0.0,
            "carb_pct": 0.0,
            "protein_pct": 0.0,
            "fat_pct": 0.0,
            "kcal": stored,
        }
    return {
        "carb_kcal": round(c_kcal, 1),
        "protein_kcal": round(p_kcal, 1),
        "fat_kcal": round(f_kcal, 1),
        "from_macros": round(total, 1),
        "carb_pct": round(100.0 * c_kcal / total, 1),
        "protein_pct": round(100.0 * p_kcal / total, 1),
        "fat_pct": round(100.0 * f_kcal / total, 1),
        "kcal": float(macros.get("kcal", 0) or total),
    }


def extract_month_km_targets(plan_md: str) -> Dict[int, float]:
    targets: Dict[int, float] = {}
    sections = extract_month_plan_sections(plan_md)
    for month, body in sections.items():
        m = re.search(r"목표\s*마일리지\s*[:：]\s*(\d+(?:\.\d+)?)\s*km", body, flags=re.I)
        if m:
            targets[int(month)] = float(m.group(1))
    if not targets:
        for m in re.finditer(
            r"🗓️\s*(\d{1,2})\s*월[\s\S]{0,240}?목표\s*마일리지\s*[:：]\s*(\d+(?:\.\d+)?)\s*km",
            plan_md or "",
            flags=re.I,
        ):
            targets[int(m.group(1))] = float(m.group(2))
    return targets


def planned_weekly_km(month_target_km: Optional[float]) -> Optional[float]:
    if month_target_km is None:
        return None
    return round(float(month_target_km) / 4.345, 1)


def _week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def analyze_nutrition(
    diet_logs: List[Dict[str, Any]],
    nutrition_targets: Optional[Dict[str, Any]] = None,
    as_of: Optional[date] = None,
    lookback_days: int = 28,
) -> Dict[str, Any]:
    nt = nutrition_targets or {}
    today = as_of or date.today()
    cutoff = today - timedelta(days=max(lookback_days - 1, 0))
    logs = []
    for log in diet_logs:
        d = _to_date(log.get("date"))
        if not d or d < cutoff or d > today:
            continue
        logs.append((d, log))
    logs.sort(key=lambda x: x[0])

    if not logs:
        return {
            "days": 0,
            "period": f"{cutoff.isoformat()} ~ {today.isoformat()}",
            "avg_kcal": 0.0,
            "avg_macros": {"kcal": 0, "carb_g": 0, "protein_g": 0, "fat_g": 0, "sugar_g": 0},
            "ratio": macro_kcal_split({}),
            "target": nt,
            "high_kcal_days": [],
            "high_sugar_days": [],
            "sweet_events": [],
            "binge_events": [],
            "bucket_counts": {},
            "weekday_risk": [],
            "insights": ["아직 이 기간 식단 기록이 없습니다. Cursor에 오늘 먹은 것을 말해 주세요."],
        }

    kcal_list: List[float] = []
    carb_list: List[float] = []
    pro_list: List[float] = []
    fat_list: List[float] = []
    sugar_list: List[float] = []
    sweet_events: List[Dict[str, Any]] = []
    binge_events: List[Dict[str, Any]] = []
    bucket_counter: Counter[str] = Counter()
    weekday_sweet: Counter[str] = Counter()
    weekday_binge: Counter[str] = Counter()
    high_kcal_days: List[Dict[str, Any]] = []
    high_sugar_days: List[Dict[str, Any]] = []

    target_kcal = float(nt.get("kcal", 0) or 0)
    target_sugar = float(nt.get("sugar_g", 40) or 40)
    target_protein = float(nt.get("protein_g", 120) or 120)

    for d, log in logs:
        macros = log.get("macros", {}) or {}
        kcal = float(macros.get("kcal", 0) or 0)
        carb = float(macros.get("carb_g", 0) or 0)
        protein = float(macros.get("protein_g", 0) or 0)
        fat = float(macros.get("fat_g", 0) or 0)
        sugar = float(macros.get("sugar_g", 0) or 0)
        kcal_list.append(kcal)
        carb_list.append(carb)
        pro_list.append(protein)
        fat_list.append(fat)
        sugar_list.append(sugar)
        meal_text = str(log.get("meal_text") or "")
        slots = split_meal_slots(meal_text)
        wday = WEEKDAY_KO[d.weekday()]

        if target_kcal and kcal >= target_kcal * 1.25:
            high_kcal_days.append(
                {
                    "date": d.isoformat(),
                    "weekday": wday,
                    "kcal": round(kcal, 0),
                    "over_by": round(kcal - target_kcal, 0),
                }
            )
        if sugar >= max(target_sugar, 1) * 1.15:
            high_sugar_days.append(
                {
                    "date": d.isoformat(),
                    "weekday": wday,
                    "sugar_g": round(sugar, 1),
                    "kcal": round(kcal, 0),
                }
            )

        for slot in slots:
            body = str(slot.get("text") or "")
            if not body:
                continue
            sweets = _contains_any(body, SWEET_KEYWORDS)
            binges = _contains_any(body, BINGE_KEYWORDS)
            if sweets:
                event = {
                    "date": d.isoformat(),
                    "weekday": wday,
                    "slot": slot.get("slot"),
                    "time": slot.get("time") or "",
                    "bucket": slot.get("bucket"),
                    "keywords": sweets,
                    "text": body[:160],
                }
                sweet_events.append(event)
                bucket_counter[str(slot.get("bucket"))] += 1
                weekday_sweet[wday] += 1
            if binges or (sweets and slot.get("bucket") == "야식(21시~)"):
                binge_events.append(
                    {
                        "date": d.isoformat(),
                        "weekday": wday,
                        "slot": slot.get("slot"),
                        "time": slot.get("time") or "",
                        "bucket": slot.get("bucket"),
                        "keywords": list(dict.fromkeys(binges + sweets)),
                        "text": body[:160],
                    }
                )
                weekday_binge[wday] += 1
                if not sweets:
                    bucket_counter[str(slot.get("bucket"))] += 1

    n = max(len(logs), 1)
    avg_macros = {
        "kcal": round(sum(kcal_list) / n, 1),
        "carb_g": round(sum(carb_list) / n, 1),
        "protein_g": round(sum(pro_list) / n, 1),
        "fat_g": round(sum(fat_list) / n, 1),
        "sugar_g": round(sum(sugar_list) / n, 1),
    }
    ratio = macro_kcal_split(
        {
            "kcal": avg_macros["kcal"],
            "carb_g": avg_macros["carb_g"],
            "protein_g": avg_macros["protein_g"],
            "fat_g": avg_macros["fat_g"],
        }
    )

    weekday_risk = []
    for w in WEEKDAY_KO:
        weekday_risk.append(
            {
                "weekday": w,
                "단것": int(weekday_sweet.get(w, 0)),
                "폭식신호": int(weekday_binge.get(w, 0)),
            }
        )
    peak_bucket = bucket_counter.most_common(1)[0][0] if bucket_counter else ""
    peak_wday = max(weekday_risk, key=lambda x: x["단것"] + x["폭식신호"]) if weekday_risk else None

    insights: List[str] = []
    if target_kcal:
        gap = avg_macros["kcal"] - target_kcal
        if gap <= -250:
            insights.append(
                f"평균 섭취 {avg_macros['kcal']:.0f}kcal로 목표({target_kcal:.0f})보다 {abs(gap):.0f}kcal 낮습니다. "
                "풀마라톤 훈련 중이면 회복·롱런 질의 떨어질 수 있습니다."
            )
        elif gap >= 250:
            insights.append(
                f"평균 섭취 {avg_macros['kcal']:.0f}kcal로 목표보다 {gap:.0f}kcal 많습니다. "
                "체지방 감량이 우선이면 야식·단것부터 줄이는 편이 안전합니다."
            )
        else:
            insights.append(f"평균 섭취 {avg_macros['kcal']:.0f}kcal로 목표({target_kcal:.0f}) 근처에 있습니다.")

    if target_protein and avg_macros["protein_g"] < target_protein * 0.85:
        insights.append(
            f"평균 단백질 {avg_macros['protein_g']:.0f}g으로 목표({target_protein:.0f}g)에 못 미칩니다. "
            "근력 유지·근성장을 위해 매 끼 단백질을 먼저 채우세요."
        )
    elif target_protein and avg_macros["protein_g"] >= target_protein:
        insights.append(f"평균 단백질 {avg_macros['protein_g']:.0f}g으로 근력 목표 선을 지키고 있습니다.")

    if ratio["carb_pct"] < 40:
        insights.append(
            f"탄수화물 비율 {ratio['carb_pct']}%로 낮습니다. 12/06 풀코스 대비 주중 질주·롱런 날은 탄수화물을 더 쓰는 편이 좋습니다."
        )
    elif ratio["carb_pct"] > 60:
        insights.append(
            f"탄수화물 비율 {ratio['carb_pct']}%로 높습니다. 단것·음료 탄수가 많은지 시간을 함께 보세요."
        )

    if sweet_events:
        insights.append(
            f"단것 신호 {len(sweet_events)}건. 가장 잦은 시간대는 {peak_bucket or '기록 부족'}입니다."
        )
    if binge_events:
        insights.append(f"폭식·고자극 식사 신호 {len(binge_events)}건이 잡혔습니다.")
    if peak_wday and (peak_wday["단것"] + peak_wday["폭식신호"]) > 0:
        insights.append(
            f"{peak_wday['weekday']}요일에 단것/폭식 신호가 몰립니다. 그 요일 전 끼니를 든든히 하거나 훈련을 오전에 두는 실험을 해보세요."
        )
    if not sweet_events and not binge_events:
        insights.append("이 기간에는 단것·폭식 키워드가 거의 없습니다. 기록에 시간(예: 21:30 야식)을 남겨 주면 패턴이 더 정확해집니다.")

    return {
        "days": len(logs),
        "period": f"{logs[0][0].isoformat()} ~ {logs[-1][0].isoformat()}",
        "avg_kcal": avg_macros["kcal"],
        "avg_macros": avg_macros,
        "ratio": ratio,
        "target": nt,
        "high_kcal_days": high_kcal_days[-8:],
        "high_sugar_days": high_sugar_days[-8:],
        "sweet_events": sweet_events[-12:],
        "binge_events": binge_events[-12:],
        "bucket_counts": dict(bucket_counter),
        "weekday_risk": weekday_risk,
        "insights": insights,
    }


def analyze_training(
    run_logs: List[Dict[str, Any]],
    profile: Dict[str, Any],
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    today = as_of or date.today()
    race = _to_date(profile.get("goal_race_date")) or date(2026, 12, 6)
    dday = (race - today).days
    plan_md = str(profile.get("custom_run_plan_md") or "")
    month_targets = extract_month_km_targets(plan_md)
    month_target = month_targets.get(today.month)
    weekly_target = planned_weekly_km(month_target)
    phases = load_phases_from_profile(profile)

    parsed: List[Tuple[date, Dict[str, Any]]] = []
    for log in run_logs:
        d = _to_date(log.get("date"))
        if not d:
            continue
        parsed.append((d, log))
    parsed.sort(key=lambda x: x[0])

    def km_between(start: date, end: date) -> float:
        total = 0.0
        for d, log in parsed:
            if start <= d <= end:
                total += float(log.get("distance_km", 0) or 0)
        return round(total, 2)

    last7 = km_between(today - timedelta(days=6), today)
    last28 = km_between(today - timedelta(days=27), today)
    month_start = today.replace(day=1)
    month_km = km_between(month_start, today)
    iso_year, iso_week, _ = today.isocalendar()
    week_km = 0.0
    longest = 0.0
    sessions = 0
    for d, log in parsed:
        y, w, _ = d.isocalendar()
        dist = float(log.get("distance_km", 0) or 0)
        if y == iso_year and w == iso_week:
            week_km += dist
            if dist > 0.5:
                sessions += 1
        if d >= today - timedelta(days=27):
            longest = max(longest, dist)
    week_km = round(week_km, 2)
    chronic_weekly = round(last28 / 4.0, 2) if last28 else 0.0
    acwr = round(last7 / chronic_weekly, 2) if chronic_weekly > 0 else None

    last_run = parsed[-1][0] if parsed else None
    gap_days = (today - last_run).days if last_run else None

    verdict = "기록 없음"
    reasons: List[str] = []
    if gap_days is None:
        verdict = "기록 없음"
        reasons.append("러닝 기록이 없어 훈련량을 판단할 수 없습니다. NRC 캡처나 거리·페이스를 Cursor에 넣어 주세요.")
    elif gap_days >= 10:
        verdict = "부족"
        reasons.append(f"마지막 러닝이 {gap_days}일 전({last_run.isoformat()})입니다. 상하이까지 {dday}일인데 공백이 깁니다.")
    elif weekly_target and week_km < weekly_target * 0.7:
        verdict = "부족"
        reasons.append(
            f"이번 주 {week_km:.1f}km로 월간 목표 환산 주간량({weekly_target:.1f}km)의 70% 미만입니다."
        )
    elif weekly_target and week_km > weekly_target * 1.35:
        verdict = "과함"
        reasons.append(
            f"이번 주 {week_km:.1f}km로 계획 주간량({weekly_target:.1f}km)보다 많습니다. 부상 예방을 위해 다음날은 쉽거나 휴식이 낫습니다."
        )
    else:
        verdict = "적당"
        reasons.append("최근 거리와 계획 주간량이 크게 어긋나지 않습니다.")

    if acwr is not None and acwr >= 1.5:
        verdict = "과함"
        reasons.append(f"급성/만성 부하비(ACWR) {acwr}로 최근 7일이 평소보다 급증했습니다.")
    elif acwr is not None and acwr <= 0.5 and last7 < 8:
        if verdict != "과함":
            verdict = "부족"
        reasons.append(f"ACWR {acwr}로 최근 훈련이 평소보다 급감했습니다.")

    month_pace = None
    if month_target:
        elapsed = max((today - month_start).days + 1, 1)
        days_in_month = (date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1) - timedelta(days=1)).day
        expected = month_target * (elapsed / days_in_month)
        month_pace = {
            "target_km": month_target,
            "actual_km": month_km,
            "expected_by_today_km": round(expected, 1),
            "gap_km": round(month_km - expected, 1),
        }
        if month_km < expected * 0.6 and verdict == "적당":
            verdict = "부족"
            reasons.append(f"이번 달 {month_km:.1f}km로 오늘까지의 기대치({expected:.1f}km)에 못 미칩니다.")

    long_hint = ""
    if today.month == 9:
        long_hint = "9월 롱런 목표 18–24km"
    elif today.month == 10:
        long_hint = "10월 롱런 목표 24–30km"
    elif today.month == 11:
        long_hint = "11월은 테이퍼, 중거리 10–16km"

    if longest and "18" in (long_hint or "") and longest < 16:
        reasons.append(f"최근 4주 최장거리 {longest:.1f}km로, 9월 롱런(18–24km)까지 아직 여유가 필요합니다.")

    if dday > 0:
        reasons.append(f"D-{dday} (2026-12-06 상하이 풀). 단기 목표는 완주, 체지방·근력은 레이스 후 또는 회복 주에 강하게 가져가세요.")
    elif dday == 0:
        reasons.append("오늘이 대회일입니다. 새 자극 훈련은 하지 마세요.")
    else:
        reasons.append("대회가 지났습니다. 이제 체지방 감량·근력 증가를 주목표로 전환해도 됩니다.")

    return {
        "dday": dday,
        "race_date": race.isoformat(),
        "verdict": verdict,
        "week_km": round(week_km, 1),
        "last7_km": last7,
        "last28_km": last28,
        "month_km": month_km,
        "weekly_target_km": weekly_target,
        "month_target_km": month_target,
        "month_pace": month_pace,
        "sessions_this_week": sessions,
        "longest_4w_km": round(longest, 1),
        "acwr": acwr,
        "last_run_date": last_run.isoformat() if last_run else "",
        "gap_days": gap_days,
        "long_hint": long_hint,
        "reasons": reasons,
        "has_plan": bool(phases),
    }


def dual_goal_notes(nutrition: Dict[str, Any], training: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    dday = int(training.get("dday") or 0)
    verdict = str(training.get("verdict") or "")
    avg_kcal = float((nutrition.get("avg_macros") or {}).get("kcal") or 0)
    target = float((nutrition.get("target") or {}).get("kcal") or 0)
    protein = float((nutrition.get("avg_macros") or {}).get("protein_g") or 0)

    if dday > 21:
        notes.append(
            "지금부터 12/06까지는 완주 체력이 1순위입니다. 공격적 체지방 감량(큰 적자)은 롱런 질을 깎을 수 있습니다."
        )
        if target and target <= 1600 and (verdict in {"부족", "적당"}):
            notes.append(
                f"목표 {target:.0f}kcal는 다이어트로선 낮습니다. 훈련량이 올라가는 주에는 1800–2100kcal 전후·단백질 우선이 완주에 유리합니다."
            )
        if verdict == "부족":
            notes.append("체중보다 먼저 주간 킬로와 주 1회 롱런을 복구하는 것이 레이스 리스크를 낮춥니다.")
    else:
        notes.append("레이스가 가깝습니다. 체중 감량보다 탄수화물·수면·테이퍼를 우선하세요.")

    if protein and protein < 90:
        notes.append("근력을 지키려면 적자를 두더라도 단백질은 하루 100g 이상을 목표로 하세요.")
    return notes


def build_dashboard(
    data: Dict[str, Any],
    as_of: Optional[date] = None,
    lookback_days: int = 28,
) -> Dict[str, Any]:
    profile = data.get("profile", {}) or {}
    nutrition = analyze_nutrition(
        data.get("diet_logs", []) or [],
        profile.get("nutrition_targets") or {},
        as_of=as_of,
        lookback_days=lookback_days,
    )
    if nutrition.get("days", 0) == 0:
        nutrition = analyze_nutrition(
            data.get("diet_logs", []) or [],
            profile.get("nutrition_targets") or {},
            as_of=as_of,
            lookback_days=400,
        )
        if nutrition.get("days", 0) > 0:
            nutrition["insights"] = [
                "최근 기간에는 식단이 없어, 예전에 쌓인 기록으로 패턴을 보여 줍니다. 오늘 먹은 것을 Cursor에 말해 주세요."
            ] + list(nutrition.get("insights") or [])
    training = analyze_training(data.get("run_logs", []) or [], profile, as_of=as_of)
    return {
        "nutrition": nutrition,
        "training": training,
        "dual_goals": dual_goal_notes(nutrition, training),
    }
