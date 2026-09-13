import csv
import io
import re
import textwrap
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image

from src.run_plan_parser import (
    build_plan_markdown_from_month_bodies,
    extract_month_plan_sections,
    load_phases_from_profile,
    match_run_to_plan,
    planned_summary_for_date,
    strip_leading_month_banner,
)
from src.storage import (
    append_run_log,
    delete_diet_logs_by_indices,
    delete_run_logs_by_indices,
    load_data,
    push_run_plan_undo,
    save_data,
    upsert_diet_log,
)
from src.analysis import build_dashboard
from src.mcp_tools import diet_analyze_tool, run_log_upsert_tool
from src.services import analyze_meal_text_priority, parse_chat_image_to_log, unified_coach_chat


st.set_page_config(page_title="마라톤 & 식단 코칭 비서", page_icon="🏃", layout="wide")
st.title("🏃 마라톤 & 식단 코칭 비서")
st.caption(
    "식단·러닝은 Cursor 대화로 넣으면 됩니다. NRC 캡처를 채팅에 붙여넣거나, 여기 앱에서 확인해도 됩니다. "
    "단기: 2026-12-06 상하이 풀 완주 · 장기: 체지방 감량·근력 증가"
)

data = load_data()
profile = data.get("profile", {})
nutrition_targets = profile.get("nutrition_targets", {})
plan_phases = load_phases_from_profile(profile)


def week_key(date_text: str) -> str:
    dt = datetime.fromisoformat(date_text).date()
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def month_key(date_text: str) -> str:
    dt = datetime.fromisoformat(date_text).date()
    return f"{dt.year}-{dt.month:02d}"


def run_kcal(distance_km: float) -> float:
    # 러닝 소모 칼로리 근사치(체중 정보 없이 간단 계산)
    return distance_km * 60.0


def run_kcal_from_log(run_log: Dict[str, Any]) -> float:
    # NRC(러닝 앱) 추정 칼로리를 우선 사용하고, 없으면 거리 기반 근사치를 사용
    nrc_kcal = float(run_log.get("calories_kcal", 0) or 0)
    if nrc_kcal > 0:
        return nrc_kcal
    return run_kcal(float(run_log.get("distance_km", 0) or 0))


def diet_grade(net_kcal: float, sugar_g: float, protein_g: float) -> str:
    if abs(net_kcal) <= 150 and sugar_g <= 40 and protein_g >= 100:
        return "우수"
    if abs(net_kcal) <= 300 and sugar_g <= 55 and protein_g >= 80:
        return "양호"
    if abs(net_kcal) <= 500:
        return "미흡"
    return "자제"


def normalize_image_payload(raw_bytes: bytes) -> Optional[Dict[str, Any]]:
    """업로드/붙여넣기 이미지를 PNG 바이트로 정규화한다."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return {"bytes": out.getvalue(), "mime": "image/png"}
    except Exception:
        return None


def aggregate_diet(
    diet_logs: List[Dict[str, Any]],
    run_logs: List[Dict[str, Any]],
    nt: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    run_by_day: Dict[str, float] = {}
    for x in run_logs:
        d = x.get("date")
        if not d:
            continue
        run_by_day[str(d)] = run_by_day.get(str(d), 0.0) + run_kcal_from_log(x)
    weekly: Dict[str, Dict[str, Any]] = {}
    monthly: Dict[str, Dict[str, Any]] = {}
    _nt = nt if nt is not None else nutrition_targets
    target_kcal = float(_nt.get("kcal", 2000) or 2000)

    for log in diet_logs:
        day = log.get("date", "")
        macros = log.get("macros", {}) or {}
        kcal = float(macros.get("kcal", 0) or 0)
        sugar = float(macros.get("sugar_g", 0) or 0)
        protein = float(macros.get("protein_g", 0) or 0)
        burned = float(run_by_day.get(day, 0))
        net_delta = (kcal - burned) - target_kcal
        grade = diet_grade(net_kcal=net_delta, sugar_g=sugar, protein_g=protein)

        wk = week_key(day)
        mk = month_key(day)
        for bucket, key in ((weekly, wk), (monthly, mk)):
            if key not in bucket:
                bucket[key] = {
                    "period": key,
                    "기록일수": 0,
                    "총섭취kcal": 0.0,
                    "총소모kcal(러닝)": 0.0,
                    "순섭취kcal": 0.0,
                    "목표대비평균오차kcal": 0.0,
                    "우수": 0,
                    "양호": 0,
                    "미흡": 0,
                    "자제": 0,
                }
            b = bucket[key]
            b["기록일수"] += 1
            b["총섭취kcal"] += kcal
            b["총소모kcal(러닝)"] += burned
            b["순섭취kcal"] += (kcal - burned)
            b["목표대비평균오차kcal"] += net_delta
            b[grade] += 1

    for bucket in (weekly, monthly):
        for key, b in bucket.items():
            days = max(b["기록일수"], 1)
            b["목표대비평균오차kcal"] = round(b["목표대비평균오차kcal"] / days, 1)
            for k in ("총섭취kcal", "총소모kcal(러닝)", "순섭취kcal"):
                b[k] = round(b[k], 1)
            for g in ("우수", "양호", "미흡", "자제"):
                b[f"{g}%"] = round(100.0 * b[g] / days, 1)
            del b["우수"]
            del b["양호"]
            del b["미흡"]
            del b["자제"]

    return {
        "weekly": sorted(weekly.values(), key=lambda x: x["period"], reverse=True),
        "monthly": sorted(monthly.values(), key=lambda x: x["period"], reverse=True),
    }


def aggregate_run(run_logs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    weekly: Dict[str, Dict[str, Any]] = {}
    monthly: Dict[str, Dict[str, Any]] = {}
    for log in run_logs:
        day = log.get("date", "")
        dist = float(log.get("distance_km", 0) or 0)
        duration = float(log.get("duration_min", 0) or 0)
        cadence = float(log.get("cadence_spm", 0) or 0)
        elevation = float(log.get("elevation_gain_m", 0) or 0)
        rpe = int(log.get("rpe", 0) or 0)
        for bucket, key in ((weekly, week_key(day)), (monthly, month_key(day))):
            if key not in bucket:
                bucket[key] = {
                    "period": key,
                    "러닝횟수": 0,
                    "총거리km": 0.0,
                    "총시간분": 0.0,
                    "평균RPE": 0.0,
                    "평균케이던스": 0.0,
                    "총고도상승m": 0.0,
                    "고강도비율(RPE>=8)%": 0.0,
                    "총소모kcal(입력)": 0.0,
                    "_rpe_total": 0.0,
                    "_hard_count": 0,
                    "_cadence_total": 0.0,
                }
            b = bucket[key]
            b["러닝횟수"] += 1
            b["총거리km"] += dist
            b["총시간분"] += duration
            b["총고도상승m"] += elevation
            b["총소모kcal(입력)"] += run_kcal_from_log(log)
            b["_rpe_total"] += rpe
            b["_cadence_total"] += cadence
            if rpe >= 8:
                b["_hard_count"] += 1

    for bucket in (weekly, monthly):
        for _, b in bucket.items():
            n = max(b["러닝횟수"], 1)
            b["총거리km"] = round(b["총거리km"], 1)
            b["총시간분"] = round(b["총시간분"], 1)
            b["총고도상승m"] = round(b["총고도상승m"], 1)
            b["총소모kcal(입력)"] = round(b["총소모kcal(입력)"], 1)
            b["평균RPE"] = round(b["_rpe_total"] / n, 1)
            b["평균케이던스"] = round(b["_cadence_total"] / n, 1)
            b["고강도비율(RPE>=8)%"] = round(100.0 * b["_hard_count"] / n, 1)
            del b["_rpe_total"]
            del b["_hard_count"]
            del b["_cadence_total"]

    return {
        "weekly": sorted(weekly.values(), key=lambda x: x["period"], reverse=True),
        "monthly": sorted(monthly.values(), key=lambda x: x["period"], reverse=True),
    }


def to_csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    # 서로 다른 행에 필드가 달라도 CSV로 안전하게 내보낼 수 있도록
    # 모든 키의 합집합을 헤더로 사용한다.
    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def clamp_domain(values: List[float], min_span: float = 1.0) -> List[float]:
    if not values:
        return [0.0, 1.0]
    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        pad = max(abs(vmin) * 0.1, min_span)
        return [vmin - pad, vmax + pad]
    pad = (vmax - vmin) * 0.1
    return [vmin - pad, vmax + pad]


def _meal_blocks_from_segment(segment: str) -> Dict[str, str]:
    """'아침(08:00): … 점심(13:00): …' 형태 한 덩어리에서 끼별 본문만 추출."""
    out: Dict[str, str] = {"아침": "", "점심": "", "저녁": "", "간식": "", "야식": ""}
    matches = list(re.finditer(r"(아침|점심|저녁|간식|야식)\([^)]*\):\s*", segment))
    for i, mm in enumerate(matches):
        key = str(mm.group(1))
        start = mm.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(segment)
        out[key] = segment[start:end].strip()
    return out


def split_meal_text(meal_text: str) -> Dict[str, str]:
    """식사 텍스트를 아침/점심/저녁으로 나눈다. 한 줄·여러 줄 모두에서 레이블이 옆 칸으로 밀리지 않게 한다."""
    result: Dict[str, str] = {"아침": "", "점심": "", "저녁": "", "간식": "", "야식": ""}
    if not meal_text:
        return result
    text = meal_text.strip()

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not re.search(r"(?:아침|점심|저녁|간식|야식)\([^)]*\):\s*", s):
            continue
        sub = _meal_blocks_from_segment(s)
        for key in ("아침", "점심", "저녁", "간식", "야식"):
            if sub.get(key):
                result[key] = (
                    (result[key] + "\n" + sub[key]).strip() if result[key] else sub[key]
                )

    if any(result[k].strip() for k in result):
        return result

    one = re.sub(r"\s+", " ", text)
    if re.search(r"(?:아침|점심|저녁|간식|야식)\([^)]*\):\s*", one):
        return _meal_blocks_from_segment(one)

    result["점심"] = text
    return result


def diet_table_rows(diet_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in diet_logs:
        meal = split_meal_text(str(log.get("meal_text", "")))
        macros = log.get("macros", {}) or {}
        rows.append(
            {
                "date": log.get("date", ""),
                "총칼로리": float(macros.get("kcal", 0) or 0),
                "아침": meal.get("아침", ""),
                "점심": meal.get("점심", ""),
                "저녁": meal.get("저녁", ""),
                "간식/야식": " / ".join(
                    x for x in (meal.get("간식", ""), meal.get("야식", "")) if str(x).strip()
                ),
                "C": float(macros.get("carb_g", 0) or 0),
                "P": float(macros.get("protein_g", 0) or 0),
                "F": float(macros.get("fat_g", 0) or 0),
                "S": float(macros.get("sugar_g", 0) or 0),
            }
        )
    return rows


def run_table_rows(
    run_logs: List[Dict[str, Any]],
    phases: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    ph = plan_phases if phases is None else phases
    rows: List[Dict[str, Any]] = []
    for log in run_logs:
        d_raw = log.get("date", "")
        try:
            d_obj = datetime.fromisoformat(str(d_raw)).date()
        except Exception:
            d_obj = date.today()
        dist = float(log.get("distance_km", 0) or 0)
        memo = str(log.get("memo", "") or "")
        icon, detail = match_run_to_plan(ph, d_obj, dist, memo)
        visual = "🟢" if icon == "O" else ("🔴" if icon == "X" else "⚪")
        rows.append(
            {
                "date": d_raw,
                "km": dist,
                "pace": log.get("pace", ""),
                "min": float(log.get("duration_min", 0) or 0),
                "kcal": float(log.get("calories_kcal", 0) or 0),
                "cadence": int(log.get("cadence_spm", 0) or 0),
                "피로도": int(log.get("rpe", 0) or 0),
                "memo": memo,
                "계획요약": planned_summary_for_date(ph, d_obj),
                "일치": visual,
                "일치설명": detail,
                "updated_at": log.get("updated_at", ""),
            }
        )
    return rows


def aggregate_plan_compliance(
    run_logs: List[Dict[str, Any]],
    phases: List[Any],
    view_mode: str,
) -> List[Dict[str, Any]]:
    """플랜 대비 O/X 집계. view_mode: 최근 14일(일자별) / 주별 / 월별."""
    today = date.today()
    cutoff = today - timedelta(days=13)

    def bucket_key(d_obj: date) -> str:
        if view_mode == "최근 14일":
            return d_obj.isoformat()
        if view_mode == "주별":
            y, w, _ = d_obj.isocalendar()
            return f"{y}-W{w:02d}"
        return month_key(d_obj.isoformat())

    bucket: Dict[str, Dict[str, int]] = {}
    for log in run_logs:
        d_raw = log.get("date", "")
        try:
            d_obj = datetime.fromisoformat(str(d_raw)).date()
        except Exception:
            continue
        if view_mode == "최근 14일" and d_obj < cutoff:
            continue
        icon, _ = match_run_to_plan(
            phases,
            d_obj,
            float(log.get("distance_km", 0) or 0),
            str(log.get("memo", "") or ""),
        )
        if icon == "—":
            continue
        key = bucket_key(d_obj)
        if key not in bucket:
            bucket[key] = {"O": 0, "X": 0}
        bucket[key][icon] += 1  # type: ignore[index]

    rows: List[Dict[str, Any]] = []
    for key in sorted(bucket.keys(), reverse=True):
        b = bucket[key]
        o = int(b["O"])
        x = int(b["X"])
        tot = max(o + x, 1)
        rows.append(
            {
                "기간": key,
                "O": o,
                "X": x,
                "일치율%": round(100.0 * o / tot, 1),
            }
        )
    return rows


def add_dummy_7_days() -> None:
    today = date.today()
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        distance = [6.2, 8.5, 5.0, 10.0, 0.0, 14.2, 7.3][6 - i]
        duration = [40, 54, 33, 62, 0, 95, 48][6 - i]
        calories = [430, 560, 330, 670, 0, 980, 500][6 - i]
        cadence = [168, 170, 166, 172, 0, 165, 171][6 - i]
        elevation = [25, 40, 18, 55, 0, 120, 35][6 - i]
        rpe = [5, 6, 4, 7, 2, 8, 6][6 - i]
        pace = [6.45, 6.35, 6.60, 6.20, 0, 6.70, 6.35][6 - i]
        pace_text = "휴식" if distance == 0 else f"{int(pace)}:{int((pace % 1) * 60):02d} /km"
        memo = ["이지런", "템포", "회복조깅", "인터벌 느낌", "휴식", "LSD", "이지런"][6 - i]

        run_log_upsert_tool(
            {
                "date": d,
                "distance_km": distance,
                "pace": pace_text,
                "duration_min": duration,
                "calories_kcal": calories,
                "cadence_spm": cadence,
                "elevation_gain_m": elevation,
                "rpe": rpe,
                "memo": memo,
            }
        )

        meal_templates = [
            "아침 오트밀+바나나, 점심 닭가슴살 샐러드, 저녁 현미밥+두부",
            "아침 토스트+계란, 점심 비빔밥, 저녁 연어덮밥",
            "아침 요거트+견과, 점심 김밥, 저녁 닭볶음탕 소량",
            "아침 바나나+우유, 점심 파스타, 저녁 샐러드+계란",
            "아침 죽, 점심 국밥 반공기, 저녁 과일+단백질쉐이크",
            "아침 베이글, 점심 떡갈비+밥, 저녁 샐러드+고구마",
            "아침 시리얼, 점심 된장찌개+밥, 저녁 닭가슴살+채소",
        ]
        macro_templates = [
            {"kcal": 1850, "carb_g": 220, "protein_g": 118, "fat_g": 54, "sugar_g": 35},
            {"kcal": 2100, "carb_g": 280, "protein_g": 105, "fat_g": 62, "sugar_g": 48},
            {"kcal": 1700, "carb_g": 195, "protein_g": 92, "fat_g": 50, "sugar_g": 33},
            {"kcal": 2000, "carb_g": 250, "protein_g": 96, "fat_g": 58, "sugar_g": 45},
            {"kcal": 1600, "carb_g": 180, "protein_g": 84, "fat_g": 46, "sugar_g": 28},
            {"kcal": 2300, "carb_g": 305, "protein_g": 112, "fat_g": 70, "sugar_g": 60},
            {"kcal": 1950, "carb_g": 240, "protein_g": 110, "fat_g": 56, "sugar_g": 38},
        ]
        upsert_diet_log(d, meal_templates[6 - i], macro_templates[6 - i], "")


tab_home, tab_diet, tab_run, tab_plan, tab_chat = st.tabs(
    ["홈", "식단 기록", "러닝 기록", "플랜 생성/조회", "Chat"]
)

with tab_home:
    home_hdr_l, home_hdr_r = st.columns([6, 1], vertical_alignment="center")
    with home_hdr_l:
        st.markdown("#### 분석 기준")
    with home_hdr_r:
        view_mode = st.segmented_control(
            "분석 기준",
            options=["최근 14일", "주별", "월별"],
            default="최근 14일",
            label_visibility="collapsed",
        )
    _home_data = load_data()
    diet_logs = _home_data.get("diet_logs", [])
    run_logs = _home_data.get("run_logs", [])
    _home_prof = _home_data.get("profile", {})
    _home_nt = _home_prof.get("nutrition_targets", {}) or {}
    _home_phases = load_phases_from_profile(_home_prof)
    _lookback = 14 if view_mode == "최근 14일" else (56 if view_mode == "주별" else 120)
    _dash = build_dashboard(_home_data, lookback_days=_lookback)
    _nut = _dash["nutrition"]
    _trn = _dash["training"]
    _ratio = _nut.get("ratio") or {}

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        _dday = int(_trn.get("dday") or 0)
        st.metric("상하이 풀", f"D-{_dday}" if _dday > 0 else "D-Day" if _dday == 0 else "완주 이후")
    with m2:
        st.metric("평균 섭취 kcal", f"{float(_nut.get('avg_kcal') or 0):.0f}")
    with m3:
        st.metric(
            "탄단지 비율",
            f"{_ratio.get('carb_pct', 0):.0f} / {_ratio.get('protein_pct', 0):.0f} / {_ratio.get('fat_pct', 0):.0f}",
            help="탄수화물 / 단백질 / 지방의 칼로리 비율(%)",
        )
    with m4:
        st.metric("이번 주 km", f"{float(_trn.get('week_km') or 0):.1f}")
    with m5:
        st.metric(
            "훈련량",
            str(_trn.get("verdict") or "-"),
            delta=None,
        )
    st.caption(
        f"식단 {_nut.get('days', 0)}일 · {_nut.get('period', '')} · "
        f"주간 목표 환산 {_trn.get('weekly_target_km') or '-'}km · "
        f"월간 목표 {_trn.get('month_target_km') or '-'}km"
    )

    _insight_bits = list(_nut.get("insights") or []) + list(_trn.get("reasons") or []) + list(_dash.get("dual_goals") or [])
    if _insight_bits:
        with st.expander("코치 요약 (칼로리·탄단지·폭식 시점·훈련량)", expanded=True):
            for _line in _insight_bits[:10]:
                st.markdown(f"- {_line}")

    _pat_l, _pat_r = st.columns(2, gap="large")
    with _pat_l:
        st.markdown("##### 단것·폭식이 나오는 시간")
        _bucket = _nut.get("bucket_counts") or {}
        if _bucket:
            _bdf = pd.DataFrame(
                [{"시간대": k, "횟수": int(v)} for k, v in _bucket.items()]
            )
            _bchart = (
                alt.Chart(_bdf)
                .mark_bar()
                .encode(
                    x=alt.X("횟수:Q", axis=alt.Axis(title="횟수", tickMinStep=1)),
                    y=alt.Y("시간대:N", sort=["아침(05–10시)", "점심(11–15시)", "저녁(16–20시)", "야식(21시~)", "시간 미상"], axis=alt.Axis(title=None)),
                    tooltip=["시간대", "횟수"],
                )
                .properties(height=160)
            )
            st.altair_chart(_bchart, width="stretch")
        else:
            st.caption("단것·폭식 키워드가 아직 없습니다. 끼니 옆에 시간(예: 저녁(21:30))을 남겨 주세요.")
        _events = list(_nut.get("sweet_events") or []) + list(_nut.get("binge_events") or [])
        if _events:
            _seen = set()
            _uniq = []
            for _ev in _events:
                _key = (_ev.get("date"), _ev.get("slot"), _ev.get("text"))
                if _key in _seen:
                    continue
                _seen.add(_key)
                _uniq.append(_ev)
            _edf = pd.DataFrame(
                [
                    {
                        "날짜": x.get("date"),
                        "요일": x.get("weekday"),
                        "때": x.get("bucket"),
                        "키워드": ", ".join(x.get("keywords") or []),
                        "내용": x.get("text"),
                    }
                    for x in _uniq[-8:]
                ]
            )
            st.dataframe(_edf, width="stretch", hide_index=True, height=220)
    with _pat_r:
        st.markdown("##### 요일별 단것/폭식 신호")
        _wr = _nut.get("weekday_risk") or []
        if _wr and any(int(x.get("단것") or 0) + int(x.get("폭식신호") or 0) for x in _wr):
            _wdf = pd.DataFrame(_wr)
            _wlong = _wdf.melt(id_vars=["weekday"], value_vars=["단것", "폭식신호"], var_name="유형", value_name="건수")
            _wchart = (
                alt.Chart(_wlong)
                .mark_bar()
                .encode(
                    x=alt.X("weekday:N", sort=["월", "화", "수", "목", "금", "토", "일"], axis=alt.Axis(title=None)),
                    y=alt.Y("건수:Q", axis=alt.Axis(title="건수", tickMinStep=1)),
                    color=alt.Color("유형:N", legend=alt.Legend(title=None)),
                    tooltip=["weekday", "유형", "건수"],
                )
                .properties(height=160)
            )
            st.altair_chart(_wchart, width="stretch")
        else:
            st.caption("요일 패턴을 보려면 며칠치 식단이 더 필요합니다.")
        _ratio_df = pd.DataFrame(
            [
                {"영양소": "탄수화물", "비율%": float(_ratio.get("carb_pct") or 0)},
                {"영양소": "단백질", "비율%": float(_ratio.get("protein_pct") or 0)},
                {"영양소": "지방", "비율%": float(_ratio.get("fat_pct") or 0)},
            ]
        )
        if float(_ratio.get("from_macros") or 0) > 0:
            _rchart = (
                alt.Chart(_ratio_df)
                .mark_bar()
                .encode(
                    x=alt.X("비율%:Q", axis=alt.Axis(title="칼로리 비율(%)"), scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("영양소:N", sort=["탄수화물", "단백질", "지방"], axis=alt.Axis(title=None)),
                    tooltip=["영양소", "비율%"],
                )
                .properties(height=140)
            )
            st.altair_chart(_rchart, width="stretch")
            _am = _nut.get("avg_macros") or {}
            st.caption(
                f"평균 C {_am.get('carb_g', 0):.0f}g · P {_am.get('protein_g', 0):.0f}g · "
                f"F {_am.get('fat_g', 0):.0f}g · 당 {_am.get('sugar_g', 0):.0f}g"
            )

    left, right = st.columns(2, gap="large")
    run_by_day: Dict[str, float] = {}
    for x in run_logs:
        d0 = x.get("date")
        if not d0:
            continue
        run_by_day[str(d0)] = run_by_day.get(str(d0), 0.0) + run_kcal_from_log(x)
    target_kcal = float(_home_nt.get("kcal", 2000) or 2000)

    diet_dates = []
    diet_delta = []
    diet_grade_count = {"우수": 0, "양호": 0, "미흡": 0, "자제": 0}
    for log in sorted(diet_logs, key=lambda x: x.get("date", ""))[-14:]:
        d = log.get("date", "")
        macros = log.get("macros", {}) or {}
        intake = float(macros.get("kcal", 0) or 0)
        burned = float(run_by_day.get(str(d), 0))
        protein = float(macros.get("protein_g", 0) or 0)
        sugar = float(macros.get("sugar_g", 0) or 0)
        delta = (intake - burned) - target_kcal
        grade = diet_grade(delta, sugar, protein)
        diet_dates.append(d)
        diet_delta.append(round(delta, 1))
        diet_grade_count[grade] += 1

    run_dates = []
    run_dist = []
    for log in sorted(run_logs, key=lambda x: x.get("date", ""))[-14:]:
        run_dates.append(log.get("date", ""))
        run_dist.append(float(log.get("distance_km", 0) or 0))

    with left:
        st.subheader("식단 분석")
        if diet_logs:
            if view_mode == "최근 14일":
                labels = diet_dates
                values = diet_delta
            else:
                diet_stats = aggregate_diet(diet_logs, run_logs, nt=_home_nt)
                rows = diet_stats["weekly"] if view_mode == "주별" else diet_stats["monthly"]
                labels = [x["period"] for x in list(reversed(rows[-12:]))]
                values = [float(x["목표대비평균오차kcal"]) for x in list(reversed(rows[-12:]))]

            st.metric("평균 목표 오차(kcal)", round(sum(values) / max(len(values), 1), 1))
            chart_df = pd.DataFrame({"x": labels, "y": values})
            y_domain = clamp_domain(values, min_span=50.0)
            line_chart = (
                alt.Chart(chart_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("x:N", axis=alt.Axis(title=None, labels=False, ticks=False, domain=False)),
                    y=alt.Y("y:Q", axis=alt.Axis(title=None), scale=alt.Scale(domain=y_domain)),
                    tooltip=[
                        alt.Tooltip("x:N", title="Date"),
                        alt.Tooltip("y:Q", title="오차(kcal)"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(line_chart, width="stretch")
            grade_df = pd.DataFrame(
                {
                    "등급": ["우수", "양호", "미흡", "자제"],
                    "일수": [
                        diet_grade_count.get("우수", 0),
                        diet_grade_count.get("양호", 0),
                        diet_grade_count.get("미흡", 0),
                        diet_grade_count.get("자제", 0),
                    ],
                }
            )
            grade_chart = (
                alt.Chart(grade_df)
                .mark_bar()
                .encode(
                    y=alt.Y("등급:N", sort=["우수", "양호", "미흡", "자제"], axis=alt.Axis(title=None)),
                    color=alt.Color(
                        "등급:N",
                        scale=alt.Scale(
                            domain=["우수", "양호", "미흡", "자제"],
                            range=["#22c55e", "#84cc16", "#f59e0b", "#ef4444"],
                        ),
                        legend=None,
                    ),
                    x=alt.X(
                        "일수:Q",
                        axis=alt.Axis(title=None, labels=False, ticks=True, tickMinStep=1),
                        scale=alt.Scale(domain=[0, max(1, max(grade_df["일수"]))]),
                    ),
                    tooltip=[
                        alt.Tooltip("등급:N", title="등급"),
                        alt.Tooltip("일수:Q", title="일수"),
                    ],
                )
                .properties(height=180)
            )
            st.altair_chart(grade_chart, width="stretch")
        else:
            st.info("식단 데이터가 없어서 분석 그래프를 표시할 수 없습니다.")

    with right:
        st.subheader("러닝 분석")
        if run_logs:
            if view_mode == "최근 14일":
                labels = run_dates
                dist_values = run_dist
            else:
                run_stats = aggregate_run(run_logs)
                rows = run_stats["weekly"] if view_mode == "주별" else run_stats["monthly"]
                rows = list(reversed(rows[-12:]))
                labels = [x["period"] for x in rows]
                dist_values = [float(x["총거리km"]) for x in rows]

            st.metric("총 거리(km)", round(sum(dist_values), 1))
            dist_df = pd.DataFrame({"x": labels, "y": dist_values})
            dist_chart = (
                alt.Chart(dist_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("x:N", axis=alt.Axis(title=None, labels=False, ticks=False, domain=False)),
                    y=alt.Y(
                        "y:Q",
                        axis=alt.Axis(title=None),
                        scale=alt.Scale(domain=clamp_domain(dist_values, min_span=1.0)),
                    ),
                    tooltip=[
                        alt.Tooltip("x:N", title="Date"),
                        alt.Tooltip("y:Q", title="거리(km)"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(dist_chart, width="stretch")

            st.markdown("##### 커스텀 러닝 플랜 대비 일치")
            if not _home_phases:
                st.caption("플랜 생성 탭에서 훈련 계획을 저장하면 집계됩니다.")
            else:
                comp_rows = aggregate_plan_compliance(run_logs, _home_phases, view_mode)
                if view_mode == "주별":
                    comp_rows = comp_rows[:12]
                elif view_mode == "월별":
                    comp_rows = comp_rows[:12]
                comp_df = pd.DataFrame(comp_rows)
                if comp_df.empty:
                    st.caption("이 구간에 플랜과 매칭되는 기록이 없습니다. (플랜 월·기록 날짜를 확인하세요.)")
                else:
                    st.dataframe(comp_df, width="stretch", hide_index=True)
        else:
            st.info("러닝 데이터가 없어서 분석 그래프를 표시할 수 없습니다.")

with tab_diet:
    st.subheader("식단 기록 입력")
    log_date = st.date_input("날짜", value=date.today(), key="diet_date")
    st.caption(
        "Cursor에 말로 알려 주셔도 됩니다. 여기 적을 때는 아침/점심/저녁/간식 시간과 양을 나눠 주세요. "
        "예: 저녁(21:30): 케이크 한 조각"
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        breakfast_time = st.text_input("아침 시간", value="08:00", key="breakfast_time")
        breakfast_text = st.text_area(
            "아침 식사/양",
            placeholder="예: 오트밀 1그릇, 바나나 1개",
            height=100,
            key="breakfast_text",
        )
    with c2:
        lunch_time = st.text_input("점심 시간", value="13:00", key="lunch_time")
        lunch_text = st.text_area(
            "점심 식사/양",
            placeholder="예: 떡갈비 한 주먹, 현미밥 반공기",
            height=100,
            key="lunch_text",
        )
    with c3:
        dinner_time = st.text_input("저녁 시간", value="19:00", key="dinner_time")
        dinner_text = st.text_area(
            "저녁 식사/양",
            placeholder="예: 샐러드 1접시, 두부 반모",
            height=100,
            key="dinner_text",
        )
    with c4:
        snack_time = st.text_input("간식/야식 시간", value="", key="snack_time")
        snack_text = st.text_area(
            "간식/야식",
            placeholder="예: 케이크 한 조각",
            height=100,
            key="snack_text",
        )

    meal_text = (
        f"아침({breakfast_time.strip()}): {breakfast_text.strip()}\n"
        f"점심({lunch_time.strip()}): {lunch_text.strip()}\n"
        f"저녁({dinner_time.strip()}): {dinner_text.strip()}"
    )
    if snack_text.strip():
        _snack_hour = None
        _sm = re.search(r"(\d{1,2})", (snack_time or "").strip())
        if _sm:
            _snack_hour = int(_sm.group(1))
        _snack_slot = "야식" if (_snack_hour is not None and (_snack_hour >= 21 or _snack_hour < 5)) else "간식"
        _snack_time = snack_time.strip() or ("22:00" if _snack_slot == "야식" else "16:00")
        meal_text += f"\n{_snack_slot}({_snack_time}): {snack_text.strip()}"

    c_ai, c_manual = st.columns(2)
    with c_ai:
        if st.button("AI(±검색) 분석 후 저장", width="stretch"):
            result = diet_analyze_tool(
                {
                    "date": log_date.isoformat(),
                    "meal_text": meal_text,
                }
            )
            macros = result.get("macros", {})
            st.success("식단 기록 저장 완료")
            st.rerun()
    with c_manual:
        with st.expander("하루 총 칼로리·탄단지 직접 입력", expanded=False):
            dm1, dm2 = st.columns(2)
            with dm1:
                m_kcal = st.number_input("총 kcal", min_value=0, value=0, step=10, key="manual_kcal")
                m_carb = st.number_input("탄수화물(g)", min_value=0, value=0, step=1, key="manual_carb")
                m_pro = st.number_input("단백질(g)", min_value=0, value=0, step=1, key="manual_pro")
            with dm2:
                m_fat = st.number_input("지방(g)", min_value=0, value=0, step=1, key="manual_fat")
                m_sugar = st.number_input("당류(g)", min_value=0, value=0, step=1, key="manual_sugar")
            if st.button("직접 입력만 저장", key="manual_save_diet"):
                macros_m = {
                    "kcal": float(m_kcal),
                    "carb_g": float(m_carb),
                    "protein_g": float(m_pro),
                    "fat_g": float(m_fat),
                    "sugar_g": float(m_sugar),
                }
                upsert_diet_log(log_date.isoformat(), meal_text, macros_m, "")
                st.success("직접 입력 저장 완료")
                st.rerun()

    _diet_head_l, _diet_head_m, _diet_head_r = st.columns([8, 3, 1], vertical_alignment="center")
    with _diet_head_l:
        st.markdown("#### 최근 식단 기록")
    with _diet_head_m:
        show_meal_columns = st.toggle("아침/점심/저녁 열 보기", value=False, key="show_meal_columns")
    with _diet_head_r:
        _del_diet_btn = st.button(
            "",
            key="diet_bulk_delete_btn",
            help="선택한 식단 기록 삭제",
            icon=":material/delete:",
            type="secondary",
        )
    _d_logs = load_data().get("diet_logs", [])
    diet_df = pd.DataFrame(diet_table_rows(_d_logs))
    _wrap_w = 24
    if not diet_df.empty:
        for col in ("아침", "점심", "저녁", "간식/야식"):
            if col in diet_df.columns:
                diet_df[col] = diet_df[col].apply(
                    lambda x, c=col: textwrap.fill(str(x), width=_wrap_w) if str(x).strip() else ""
                )
    if not diet_df.empty and not show_meal_columns:
        diet_df = diet_df.drop(columns=["아침", "점심", "저녁", "간식/야식"], errors="ignore")

    if not diet_df.empty:
        diet_df.insert(0, "선택", False)
        diet_df["_storage_i"] = range(len(_d_logs))
        diet_df = diet_df.sort_values("date", ascending=False).reset_index(drop=True)
        _meal_w = "medium"
        _diet_cfg: Dict[str, Any] = {
            "선택": st.column_config.CheckboxColumn("선택", default=False),
            "date": st.column_config.TextColumn("date", width="small"),
            "총칼로리": st.column_config.NumberColumn("총칼로리", format="%.0f", width="small"),
            "C": st.column_config.NumberColumn("C", format="%.1f", width="small"),
            "P": st.column_config.NumberColumn("P", format="%.1f", width="small"),
            "F": st.column_config.NumberColumn("F", format="%.1f", width="small"),
            "S": st.column_config.NumberColumn("S", format="%.1f", width="small"),
            "아침": st.column_config.TextColumn("아침", width=_meal_w),
            "점심": st.column_config.TextColumn("점심", width=_meal_w),
            "저녁": st.column_config.TextColumn("저녁", width=_meal_w),
            "간식/야식": st.column_config.TextColumn("간식/야식", width=_meal_w),
        }
        _d_order = ["선택", "date", "총칼로리", "C", "P", "F", "S", "아침", "점심", "저녁", "간식/야식"]
        _d_order = [c for c in _d_order if c in diet_df.columns]
        _d_cfg_use = {k: v for k, v in _diet_cfg.items() if k in diet_df.columns}
        _d_disabled = [c for c in diet_df.columns if c != "선택"]
        st.caption("왼쪽에서 삭제할 행을 선택한 뒤, 제목 오른쪽 휴지통을 누르세요.")
        edited_diet = st.data_editor(
            diet_df,
            width="stretch",
            height=360,
            column_order=_d_order,
            column_config=_d_cfg_use,
            disabled=_d_disabled,
            hide_index=True,
            key="diet_table_ed",
            num_rows="fixed",
        )
        if _del_diet_btn:
            _mask = edited_diet["선택"].fillna(False)
            _mask = _mask.astype(bool) if hasattr(_mask, "astype") else _mask
            _rm = edited_diet.loc[_mask, "_storage_i"].astype(int).tolist()
            if _rm:
                n = delete_diet_logs_by_indices(_rm)
                st.success(f"삭제했습니다 ({n}건)")
                st.rerun()
            else:
                st.warning("체크한 항목이 없습니다.")
    else:
        st.info("식단 기록이 없습니다.")


def _on_run_rest_change() -> None:
    if st.session_state.get("run_is_rest"):
        st.session_state["run_distance_km"] = 0.0
        st.session_state["run_duration_min"] = 0.0
        st.session_state["run_calories_kcal"] = 0.0
        st.session_state["run_cadence_spm"] = 0
        st.session_state["run_elevation_gain_m"] = 0.0
        st.session_state["run_rpe"] = 1
        st.session_state["run_pace"] = "휴식"
        st.session_state["run_memo"] = ""


with tab_run:
    st.subheader("러닝 기록 입력")
    st.caption("NRC 캡처는 Cursor 채팅에 붙여넣거나, 아래에 올려도 됩니다.")
    _nrc_file = st.file_uploader(
        "NRC 캡처 업로드",
        type=["png", "jpg", "jpeg", "webp"],
        key="nrc_shot",
    )
    if _nrc_file is not None:
        _nrc_norm = normalize_image_payload(_nrc_file.getvalue())
        if _nrc_norm and _nrc_norm.get("bytes"):
            st.image(bytes(_nrc_norm["bytes"]), width=240)
            if st.button("캡처에서 기록 추출", key="nrc_parse_btn"):
                with st.spinner("NRC 캡처를 읽는 중…"):
                    _nrc_parsed = parse_chat_image_to_log(
                        image_bytes=bytes(_nrc_norm["bytes"]),
                        image_mime="image/png",
                        user_note="NRC 러닝 기록",
                    )
                if _nrc_parsed.get("_error"):
                    st.error(f"추출 실패: {_nrc_parsed.get('_error')}")
                elif str(_nrc_parsed.get("kind", "")).lower() != "run":
                    st.warning("러닝 기록으로 보이지 않습니다. 채팅 탭에 이미지를 넣어 보세요.")
                else:
                    _nr = _nrc_parsed.get("run", {}) or {}
                    _nd = str(_nrc_parsed.get("date") or date.today().isoformat())
                    append_run_log(
                        log_date=_nd,
                        distance_km=float(_nr.get("distance_km", 0) or 0),
                        pace=str(_nr.get("pace") or ""),
                        duration_min=float(_nr.get("duration_min", 0) or 0),
                        calories_kcal=float(_nr.get("calories_kcal", 0) or 0),
                        cadence_spm=int(float(_nr.get("cadence_spm", 0) or 0)),
                        elevation_gain_m=float(_nr.get("elevation_gain_m", 0) or 0),
                        rpe=int(float(_nr.get("rpe", 0) or 0)),
                        memo=str(_nr.get("memo") or "NRC 캡처에서 추출"),
                    )
                    st.success(
                        f"저장: {_nd} · {float(_nr.get('distance_km', 0) or 0):.2f}km"
                    )
                    st.rerun()

    _run_defaults: Dict[str, Any] = {
        "run_distance_km": 5.0,
        "run_duration_min": 35.0,
        "run_calories_kcal": 350.0,
        "run_cadence_spm": 170,
        "run_elevation_gain_m": 30.0,
        "run_rpe": 5,
        "run_pace": "06:30 /km",
        "run_memo": "",
    }
    for _k, _v in _run_defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v
    if "run_is_rest" not in st.session_state:
        st.session_state.run_is_rest = False

    run_date_col, run_rest_col = st.columns([5, 1], vertical_alignment="center")
    with run_date_col:
        run_date = st.date_input("날짜", value=date.today(), key="run_date")
    with run_rest_col:
        st.checkbox(
            "오늘은 휴식일",
            key="run_is_rest",
            on_change=_on_run_rest_change,
        )
    is_rest_day = bool(st.session_state.get("run_is_rest", False))
    c1, c2, c3 = st.columns(3)
    with c1:
        distance_km = st.number_input(
            "거리(km)",
            min_value=0.0,
            step=0.1,
            key="run_distance_km",
            disabled=is_rest_day,
        )
    with c2:
        pace = st.text_input("평균 페이스", key="run_pace", disabled=is_rest_day)
    with c3:
        rpe = st.slider("피로도(RPE)", min_value=1, max_value=10, key="run_rpe", disabled=is_rest_day)
    c4, c5, c6 = st.columns(3)
    with c4:
        duration_min = st.number_input(
            "시간(분)",
            min_value=0.0,
            step=1.0,
            key="run_duration_min",
            disabled=is_rest_day,
        )
    with c5:
        calories_kcal = st.number_input(
            "칼로리(NRC)",
            min_value=0.0,
            step=10.0,
            key="run_calories_kcal",
            disabled=is_rest_day,
        )
    with c6:
        cadence_spm = st.number_input(
            "케이던스(spm)",
            min_value=0,
            step=1,
            key="run_cadence_spm",
            disabled=is_rest_day,
        )
    elevation_gain_m = st.number_input(
        "고도상승(m)",
        min_value=0.0,
        step=1.0,
        key="run_elevation_gain_m",
        disabled=is_rest_day,
    )
    memo = st.text_area(
        "메모",
        placeholder="예: 마지막 2km 힘들었음",
        height=90,
        key="run_memo",
        disabled=is_rest_day,
    )

    if st.button("러닝 기록 추가", width="stretch"):
        final_distance = 0.0 if is_rest_day else float(distance_km)
        final_pace = "휴식" if is_rest_day else str(pace)
        final_duration = 0.0 if is_rest_day else float(duration_min)
        final_kcal = 0.0 if is_rest_day else float(calories_kcal)
        final_cadence = 0 if is_rest_day else int(cadence_spm)
        final_elevation = 0.0 if is_rest_day else float(elevation_gain_m)
        final_rpe = 1 if is_rest_day else int(rpe)
        final_memo = (str(memo).strip() + " / " if str(memo).strip() else "") + ("휴식일" if is_rest_day else "")
        run_log_upsert_tool(
            {
                "date": run_date.isoformat(),
                "distance_km": final_distance,
                "pace": final_pace,
                "duration_min": final_duration,
                "calories_kcal": final_kcal,
                "cadence_spm": final_cadence,
                "elevation_gain_m": final_elevation,
                "rpe": final_rpe,
                "memo": final_memo,
            }
        )
        st.success("러닝 기록을 추가했습니다")
        st.rerun()

    st.caption("같은 날 여러 번 뛴 경우, 날짜를 같게 두고 저장 버튼으로 건마다 추가하면 됩니다.")

    _run_head_l, _run_head_r = st.columns([11, 1], vertical_alignment="center")
    with _run_head_l:
        st.markdown("#### 최근 러닝 기록")
    with _run_head_r:
        _del_run_btn = st.button(
            "",
            key="run_bulk_delete_btn",
            help="선택한 러닝 기록 삭제",
            icon=":material/delete:",
            type="secondary",
        )
    _r_logs = load_data().get("run_logs", [])
    run_df = pd.DataFrame(run_table_rows(_r_logs, phases=plan_phases))
    if not run_df.empty:
        run_df.insert(0, "선택", False)
        run_df["_storage_i"] = range(len(_r_logs))
        run_df = run_df.sort_values("date", ascending=False).reset_index(drop=True)
        _run_cfg: Dict[str, Any] = {
            "선택": st.column_config.CheckboxColumn("선택", default=False),
            "date": st.column_config.TextColumn("date", width="small"),
            "km": st.column_config.NumberColumn("km", format="%.1f", width="small"),
            "pace": st.column_config.TextColumn("pace", width="small"),
            "min": st.column_config.NumberColumn("분", format="%.0f", width="small"),
            "kcal": st.column_config.NumberColumn("kcal", format="%.0f", width="small"),
            "cadence": st.column_config.NumberColumn("spm", format="%d", width="small"),
            "피로도": st.column_config.NumberColumn("RPE", format="%d", width="small"),
            "memo": st.column_config.TextColumn("memo", width="medium"),
            "계획요약": st.column_config.TextColumn("계획요약", width="medium"),
            "일치": st.column_config.TextColumn("일치", width="small"),
            "일치설명": st.column_config.TextColumn("일치설명", width="large"),
            "updated_at": st.column_config.TextColumn("updated_at", width="small"),
        }
        _run_order = [
            "선택",
            "date",
            "km",
            "pace",
            "min",
            "kcal",
            "cadence",
            "피로도",
            "memo",
            "계획요약",
            "일치",
            "일치설명",
            "updated_at",
        ]
        _run_order = [c for c in _run_order if c in run_df.columns]
        _run_cfg_use = {k: v for k, v in _run_cfg.items() if k in run_df.columns}
        _run_disabled = ["선택", "계획요약", "일치", "일치설명", "updated_at", "_storage_i"]
        st.caption("왼쪽에서 삭제할 행을 선택한 뒤, 제목 오른쪽 휴지통을 누르세요.")
        edited_run = st.data_editor(
            run_df,
            width="stretch",
            height=400,
            column_order=_run_order,
            column_config=_run_cfg_use,
            disabled=_run_disabled,
            hide_index=True,
            key="run_table_ed",
            num_rows="fixed",
        )
        # 더블클릭 편집 후 포커스가 빠지면 자동 저장한다.
        _data_for_update = load_data()
        _logs_upd = list(_data_for_update.get("run_logs", []))
        _changed = 0
        for _, _row in edited_run.iterrows():
            try:
                _idx = int(_row.get("_storage_i"))
            except Exception:
                continue
            if _idx < 0 or _idx >= len(_logs_upd):
                continue
            _log = dict(_logs_upd[_idx])

            _new_date = str(_row.get("date", _log.get("date", ""))).strip()
            _new_km = float(_row.get("km", _log.get("distance_km", 0)) or 0)
            _new_pace = str(_row.get("pace", _log.get("pace", "")))
            _new_min = float(_row.get("min", _log.get("duration_min", 0)) or 0)
            _new_kcal = float(_row.get("kcal", _log.get("calories_kcal", 0)) or 0)
            _new_cad = int(float(_row.get("cadence", _log.get("cadence_spm", 0)) or 0))
            _new_rpe = int(float(_row.get("피로도", _log.get("rpe", 0)) or 0))
            _new_memo = str(_row.get("memo", _log.get("memo", "")))

            _dirty = (
                _new_date != str(_log.get("date", ""))
                or abs(_new_km - float(_log.get("distance_km", 0) or 0)) > 1e-9
                or _new_pace != str(_log.get("pace", ""))
                or abs(_new_min - float(_log.get("duration_min", 0) or 0)) > 1e-9
                or abs(_new_kcal - float(_log.get("calories_kcal", 0) or 0)) > 1e-9
                or _new_cad != int(_log.get("cadence_spm", 0) or 0)
                or _new_rpe != int(_log.get("rpe", 0) or 0)
                or _new_memo != str(_log.get("memo", ""))
            )
            if not _dirty:
                continue

            _log["date"] = _new_date
            _log["distance_km"] = _new_km
            _log["pace"] = _new_pace
            _log["duration_min"] = _new_min
            _log["calories_kcal"] = _new_kcal
            _log["cadence_spm"] = _new_cad
            _log["rpe"] = _new_rpe
            _log["memo"] = _new_memo
            _log["updated_at"] = date.today().isoformat()
            _logs_upd[_idx] = _log
            _changed += 1

        if _changed > 0:
            _data_for_update["run_logs"] = _logs_upd
            save_data(_data_for_update)
            st.toast(f"러닝 기록 자동 저장 ({_changed}건)")
            st.rerun()
        if _del_run_btn:
            _rmask = edited_run["선택"].fillna(False)
            _rmask = _rmask.astype(bool) if hasattr(_rmask, "astype") else _rmask
            _rr = edited_run.loc[_rmask, "_storage_i"].astype(int).tolist()
            if _rr:
                n = delete_run_logs_by_indices(_rr)
                st.success(f"삭제했습니다 ({n}건)")
                st.rerun()
            else:
                st.warning("체크한 항목이 없습니다.")
    else:
        st.info("러닝 기록이 없습니다.")

with tab_plan:
    st.markdown(
        """
        <style>
        div[class*="st-key-plan_edit_btn"] button,
        button[class*="st-key-plan_edit_btn"] {
            border-radius: 999px !important;
            width: 2.65rem !important;
            min-width: 2.65rem !important;
            max-width: 2.65rem !important;
            height: 2.65rem !important;
            min-height: 2.65rem !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[class*="st-key-plan_save_btn"] button,
        button[class*="st-key-plan_save_btn"] {
            border-radius: 999px !important;
            width: 2.65rem !important;
            min-width: 2.65rem !important;
            max-width: 2.65rem !important;
            height: 2.65rem !important;
            min-height: 2.65rem !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[class*="st-key-plan_edit_btn"],
        div[class*="st-key-plan_save_btn"] {
            display: flex !important;
            justify-content: flex-end !important;
            width: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "plan_training_edit" not in st.session_state:
        st.session_state.plan_training_edit = False

    _undo_hist = profile.get("custom_run_plan_md_undo_stack")
    if not isinstance(_undo_hist, list):
        _undo_hist = []

    _plan_row_l, _plan_row_m, _plan_row_r = st.columns([10, 1, 1], vertical_alignment="center")
    with _plan_row_l:
        st.subheader("현재 훈련 계획")
    with _plan_row_m:
        if not st.session_state.plan_training_edit:
            if st.button(
                "",
                key="plan_edit_btn",
                help="훈련 계획 수정",
                icon=":material/edit:",
                type="secondary",
            ):
                st.session_state.plan_training_edit = True
                st.rerun()
        else:
            if st.button(
                "",
                key="plan_save_btn",
                help="저장하고 보기 모드로",
                icon=":material/check:",
                type="primary",
            ):
                _data_save = load_data()
                _prof_save = dict(_data_save.get("profile", {}))
                _month_bodies: Dict[int, str] = {}
                for _mm in range(5, 12):
                    _mk = f"plan_edit_month_{_mm}"
                    if _mk in st.session_state:
                        _month_bodies[_mm] = str(st.session_state[_mk])
                _new_md = build_plan_markdown_from_month_bodies(_month_bodies)
                _prev_md = str(_prof_save.get("custom_run_plan_md") or "")
                if _new_md != _prev_md:
                    push_run_plan_undo(_prof_save, _prev_md)
                _prof_save["custom_run_plan_md"] = _new_md
                _data_save["profile"] = _prof_save
                save_data(_data_save)
                for _clear_m in range(5, 12):
                    st.session_state.pop(f"plan_edit_month_{_clear_m}", None)
                st.session_state.plan_training_edit = False
                st.toast("훈련 계획을 저장했습니다.")
                st.rerun()
    with _plan_row_r:
        if st.button(
            "실행 취소",
            key="plan_undo_btn",
            help="이전에 저장돼 있던 훈련 계획으로 되돌립니다 (저장할 때마다 최대 20단계).",
            disabled=len(_undo_hist) == 0,
            type="secondary",
        ):
            _du = load_data()
            _pu = dict(_du.get("profile", {}))
            _uh = _pu.get("custom_run_plan_md_undo_stack")
            if isinstance(_uh, list) and _uh:
                _pu["custom_run_plan_md"] = _uh.pop()
                _pu["custom_run_plan_md_undo_stack"] = _uh
                _du["profile"] = _pu
                save_data(_du)
                for _clear_m in range(5, 12):
                    st.session_state.pop(f"plan_edit_month_{_clear_m}", None)
                st.session_state.plan_training_edit = False
                st.toast("이전 저장본으로 되돌렸습니다.")
                st.rerun()

    _plan_md = str(profile.get("custom_run_plan_md") or "").strip()
    _normalized_plan_md = re.sub(
        r"(?m)^\s*\*\*\s*🗓️\s*(\d{1,2})\s*월\s*\*\*\s*$",
        r"🗓️ \1월",
        _plan_md,
    ).strip()
    if _normalized_plan_md != _plan_md:
        _plan_md = _normalized_plan_md
        _data_norm = load_data()
        _prof_norm = dict(_data_norm.get("profile", {}))
        _prof_norm["custom_run_plan_md"] = _plan_md
        _data_norm["profile"] = _prof_norm
        save_data(_data_norm)

    if st.session_state.plan_training_edit:
        _by_m_edit = extract_month_plan_sections(_plan_md) if _plan_md else {}
        _mtabs_e = st.tabs([f"{m}월" for m in range(5, 12)])
        for _ti, _tm in enumerate(range(5, 12)):
            with _mtabs_e[_ti]:
                _init_body = strip_leading_month_banner(
                    _by_m_edit.get(_tm, "") or "", _tm
                )
                st.text_area(
                    f"{_tm}월",
                    value=_init_body,
                    height=360,
                    key=f"plan_edit_month_{_tm}",
                    label_visibility="collapsed",
                    placeholder="이번 달만의 훈련 표·설명(마크다운). 다른 달과 독립입니다.",
                )
        st.caption(
            "같은 구간을 쓰던 달도 처음에는 동일한 글이 채워지며, 이후 각 탭에서 따로 고칠 수 있습니다. 저장하면 월별 블록으로 나뉘어 저장됩니다."
        )
    elif not _plan_md:
        st.info("아직 저장된 훈련 계획이 없습니다. 오른쪽 연필 버튼으로 추가·편집할 수 있습니다.")
    else:
        _by_m = extract_month_plan_sections(_plan_md)
        _mtabs = st.tabs([f"{m}월" for m in range(5, 12)])
        for _ti, _tm in enumerate(range(5, 12)):
            with _mtabs[_ti]:
                _sec = _by_m.get(_tm)
                if _sec:
                    st.markdown(_sec)
                else:
                    st.write("")

with tab_chat:
    st.markdown(
        """
        <style>
        .stChatMessage:has([data-testid="stChatMessageAvatarUser"]) {
            display: flex;
            flex-direction: row-reverse;
            align-items: flex-end;
            background-color: #f5f5f6 !important;
            border-radius: 14px !important;
            padding: 0.5rem 0.65rem !important;
            margin-bottom: 0.4rem !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
        }
        .stChatMessage:has([data-testid="stChatMessageAvatarUser"])
            [data-testid="stChatMessageContent"] * {
            text-align: right;
            color: #191919 !important;
        }
        .stChatMessage:not(:has([data-testid="stChatMessageAvatarUser"])) {
            background-color: #e6e7e9 !important;
            border-radius: 14px !important;
            padding: 0.5rem 0.65rem !important;
            margin-bottom: 0.4rem !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.07);
        }
        .stChatMessage:not(:has([data-testid="stChatMessageAvatarUser"]))
            [data-testid="stChatMessageContent"] * {
            color: #191919 !important;
        }
        /* 헤더 행: 대화 초기화를 열 안에서 우측 끝으로 */
        div[class*="st-key-coach_chat_clear"] {
            display: flex !important;
            justify-content: flex-end !important;
            width: 100% !important;
        }
        /* 전송 버튼 열: 원형 버튼을 칸 오른쪽에 붙임 */
        div[class*="st-key-coach_chat_send_plane"] {
            display: flex !important;
            justify-content: flex-end !important;
            width: 100% !important;
        }
        /* 채팅 전송: 동그란 비행기 버튼 */
        div[class*="st-key-coach_chat_send_plane"] button,
        button[class*="st-key-coach_chat_send_plane"] {
            border-radius: 999px !important;
            width: 2.65rem !important;
            min-width: 2.65rem !important;
            max-width: 2.65rem !important;
            height: 2.65rem !important;
            min-height: 2.65rem !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.15rem !important;
            line-height: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "coach_chat_messages" not in st.session_state:
        st.session_state.coach_chat_messages = []

    _hdr_l, _hdr_r = st.columns([12, 1], vertical_alignment="center")
    with _hdr_l:
        st.markdown("#### 코치와 대화")
    with _hdr_r:
        if st.button("대화 초기화", key="coach_chat_clear", type="secondary"):
            st.session_state.coach_chat_messages = []
            st.rerun()

    _chat_value = st.chat_input(
        "메시지를 입력하세요… (Ctrl+V 이미지 붙여넣기 가능)",
        key="coach_chat_input",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "webp"],
    )

    if _chat_value:
        _pt = ""
        _files: List[Any] = []
        try:
            _pt = str(getattr(_chat_value, "text", "") or "").strip()
        except Exception:
            _pt = ""
        try:
            _files = list(getattr(_chat_value, "files", []) or [])
        except Exception:
            _files = []

        _parts: List[str] = []
        if _pt:
            _parts.append(_pt)
        if _files:
            _parts.append("[이미지 첨부]")
        _user_msg = "\n".join(_parts).strip() or "(첨부만 전송)"

        _preview_images: List[bytes] = []
        for _f in _files:
            _norm = normalize_image_payload(_f.getvalue())
            if _norm and _norm.get("bytes"):
                _preview_images.append(bytes(_norm["bytes"]))
        st.session_state.coach_chat_messages.append(
            {"role": "user", "content": _user_msg, "images": _preview_images}
        )

        _assistant_notes: List[str] = []
        _image_saved_any = False
        for _img in _preview_images:
            with st.spinner("이미지에서 기록을 읽는 중…"):
                _parsed = parse_chat_image_to_log(
                    image_bytes=_img,
                    image_mime="image/png",
                    user_note=_pt,
                )
            if _parsed.get("_error"):
                _assistant_notes.append(f"이미지 파싱 실패: `{_parsed.get('_error')}`")
                continue
            _kind = str(_parsed.get("kind", "unknown")).lower()
            _log_date = str(_parsed.get("date") or date.today().isoformat())
            if _kind == "diet":
                _diet = _parsed.get("diet", {}) or {}
                _meal_text = str(_diet.get("meal_text") or "채팅 이미지 업로드 기록")
                _macros = {
                    "kcal": float(_diet.get("kcal", 0) or 0),
                    "carb_g": float(_diet.get("carb_g", 0) or 0),
                    "protein_g": float(_diet.get("protein_g", 0) or 0),
                    "fat_g": float(_diet.get("fat_g", 0) or 0),
                    "sugar_g": float(_diet.get("sugar_g", 0) or 0),
                }
                upsert_diet_log(
                    log_date=_log_date,
                    meal_text=_meal_text,
                    macros=_macros,
                    feedback="채팅 이미지에서 자동 추출",
                )
                _assistant_notes.append(
                    f"식단 저장: `{_log_date}`, `{_macros['kcal']:.0f} kcal`."
                )
                _image_saved_any = True
            elif _kind == "run":
                _run = _parsed.get("run", {}) or {}
                append_run_log(
                    log_date=_log_date,
                    distance_km=float(_run.get("distance_km", 0) or 0),
                    pace=str(_run.get("pace") or ""),
                    duration_min=float(_run.get("duration_min", 0) or 0),
                    calories_kcal=float(_run.get("calories_kcal", 0) or 0),
                    cadence_spm=int(float(_run.get("cadence_spm", 0) or 0)),
                    elevation_gain_m=float(_run.get("elevation_gain_m", 0) or 0),
                    rpe=int(float(_run.get("rpe", 0) or 0)),
                    memo=str(_run.get("memo") or "채팅 이미지에서 자동 추출"),
                )
                _assistant_notes.append(
                    f"러닝 저장: `{_log_date}`, `{float(_run.get('distance_km', 0) or 0):.2f} km`."
                )
                _image_saved_any = True
            else:
                _assistant_notes.append("이미지 유형 불명확: 식단/러닝으로 분류하지 못했어요.")

        _wants_text_diet_save = bool(
            re.search(r"(먹|섭취|식단|칼로리|kcal|탄수|단백|지방|당)", _pt, flags=re.IGNORECASE)
        )
        if _pt and (not _preview_images) and _wants_text_diet_save:
            _chat_data_for_text = load_data()
            _txt_res = analyze_meal_text_priority(
                meal_text=_pt,
                nutrition_targets=_chat_data_for_text.get("profile", {}).get("nutrition_targets", {}),
                recent_diet_logs=_chat_data_for_text.get("diet_logs", []),
            )
            _txt_macros = {
                "kcal": float(_txt_res.get("kcal", 0) or 0),
                "carb_g": float(_txt_res.get("carb_g", 0) or 0),
                "protein_g": float(_txt_res.get("protein_g", 0) or 0),
                "fat_g": float(_txt_res.get("fat_g", 0) or 0),
                "sugar_g": float(_txt_res.get("sugar_g", 0) or 0),
            }
            _log_date_txt = date.today().isoformat()
            upsert_diet_log(
                log_date=_log_date_txt,
                meal_text=_pt,
                macros=_txt_macros,
                feedback=str(_txt_res.get("notes") or "텍스트 식단 자동 계산"),
            )
            _assistant_notes.append(
                f"텍스트 식단 저장: `{_log_date_txt}`, `{_txt_macros['kcal']:.0f} kcal`."
            )

        if _pt and not _image_saved_any:
            _chat_hist = st.session_state.coach_chat_messages[:-1]
            _chat_data = load_data()
            with st.spinner("기록·플랜·검색을 참고해 답변 생성 중…"):
                _reply = unified_coach_chat(
                    _pt,
                    _chat_data.get("diet_logs", []),
                    _chat_data.get("run_logs", []),
                    _chat_data.get("profile", {}),
                    conversation_history=_chat_hist,
                )
            if _assistant_notes:
                _reply = "\n".join(_assistant_notes) + "\n\n" + _reply
            st.session_state.coach_chat_messages.append({"role": "assistant", "content": _reply})
        else:
            st.session_state.coach_chat_messages.append(
                {"role": "assistant", "content": "\n".join(_assistant_notes) or "처리 완료"}
            )
        st.rerun()

    st.caption(
        "저장된 식단·러닝 기록, 프로필의 훈련 플랜, 그리고 Tavily 웹 검색(키 설정 시)을 함께 참고합니다."
    )

    for _msg in reversed(st.session_state.coach_chat_messages):
        with st.chat_message(_msg["role"]):
            st.markdown(_msg["content"])
            _imgs = _msg.get("images") if isinstance(_msg, dict) else None
            if isinstance(_imgs, list) and _imgs:
                st.image(_imgs, width=180)

st.markdown("---")
show_profile = st.toggle("프로필 설정 보기", value=False)
if show_profile:
    st.caption("하단 설정은 로컬 `data/data.json`에 저장됩니다.")
    _goal_c1, _goal_c2 = st.columns(2, vertical_alignment="bottom")
    with _goal_c1:
        goal_race_date = st.date_input(
            "목표 대회일",
            value=date.fromisoformat(profile.get("goal_race_date", "2026-12-01")),
            key="footer_goal_date",
        )
    with _goal_c2:
        goal_time = st.text_input(
            "목표 풀코스 기록(HH:MM:SS)",
            value=profile.get("goal_marathon_time", "04:30:00"),
            key="footer_goal_time",
        )
    c1, c2 = st.columns(2)
    with c1:
        kcal = st.number_input(
            "하루 목표 kcal",
            min_value=0,
            value=int(nutrition_targets.get("kcal", 2000)),
            key="footer_kcal",
        )
        carb_g = st.number_input(
            "탄수화물(g)",
            min_value=0,
            value=int(nutrition_targets.get("carb_g", 250)),
            key="footer_carb",
        )
        protein_g = st.number_input(
            "단백질(g)",
            min_value=0,
            value=int(nutrition_targets.get("protein_g", 120)),
            key="footer_protein",
        )
    with c2:
        fat_g = st.number_input(
            "지방(g)",
            min_value=0,
            value=int(nutrition_targets.get("fat_g", 60)),
            key="footer_fat",
        )
        sugar_g = st.number_input(
            "당류(g)",
            min_value=0,
            value=int(nutrition_targets.get("sugar_g", 40)),
            key="footer_sugar",
        )
    if st.button("프로필 저장", width="stretch", key="footer_save"):
        data["profile"] = {
            "name": str(profile.get("name") or ""),
            "goal_race_date": goal_race_date.isoformat(),
            "goal_marathon_time": goal_time,
            "custom_run_plan_md": str(profile.get("custom_run_plan_md") or ""),
            "custom_run_plan_md_undo_stack": list(
                profile.get("custom_run_plan_md_undo_stack") or []
            ),
            "nutrition_targets": {
                "kcal": kcal,
                "carb_g": carb_g,
                "protein_g": protein_g,
                "fat_g": fat_g,
                "sugar_g": sugar_g,
            },
        }
        save_data(data)
        st.success("프로필 저장 완료")
        st.rerun()

