from typing import Any, Dict, List, Optional

from src.gemini_client import call_gemini_json, call_gemini_text
from src.tavily_search import snippets_for_diet_query, snippets_for_meal, snippets_for_running_query


def analyze_meal_with_ai(
    meal_text: str,
    nutrition_targets: Dict[str, float],
    recent_diet_logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    recent_summary = recent_diet_logs[-7:]
    web_block = ""
    ctx = snippets_for_meal(meal_text)
    if ctx:
        web_block = f"""
[인터넷 검색 요약 — 수치 추정 시 우선 반영]
아래 스니펫은 검색 결과이며, 하루 전체 합산 kcal·탄단지·당과 일치하도록 보정하세요.
{ctx}
"""
    prompt = f"""
당신은 식단 코치입니다. 아래 식단 텍스트를 바탕으로 탄수화물/단백질/지방/당/칼로리를 추정하세요.
인터넷 검색 요약이 있으면 그 근거를 우선하고, 부족한 부분만 합리적으로 보완하세요.

[오늘 식단 입력]
{meal_text}
{web_block}
[목표]
{nutrition_targets}

[최근 7일 식단 기록]
{recent_summary}

반드시 아래 JSON만 반환:
{{
  "kcal": number,
  "carb_g": number,
  "protein_g": number,
  "fat_g": number,
  "sugar_g": number
}}
"""
    result = call_gemini_json(prompt)
    if result and not result.get("_error"):
        return result

    return {
        "kcal": 0,
        "carb_g": 0,
        "protein_g": 0,
        "fat_g": 0,
        "sugar_g": 0,
    }


def unified_coach_chat(
    question: str,
    diet_logs: List[Dict[str, Any]],
    run_logs: List[Dict[str, Any]],
    profile: Dict[str, Any],
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """식단·러닝·플랜·Tavily(키 있을 때)를 한 번에 참고해 답한다."""
    q = (question or "").strip()
    if not q:
        return "메시지를 입력해 주세요."

    recent_d = sorted(diet_logs, key=lambda x: str(x.get("date", "")))[-21:]
    dlines: List[str] = []
    for d in recent_d:
        m = d.get("macros", {}) or {}
        meal_snip = str(d.get("meal_text", "") or "").replace("\n", " ")[:200]
        dlines.append(
            f"- {d.get('date')}: kcal {m.get('kcal')}, C/P/F/S "
            f"{m.get('carb_g')}/{m.get('protein_g')}/{m.get('fat_g')}/{m.get('sugar_g')}, {meal_snip}"
        )
    diet_block = "\n".join(dlines) if dlines else "(식단 기록 없음)"

    recent_r = sorted(run_logs, key=lambda x: str(x.get("date", "")))[-50:]
    rlines: List[str] = []
    for r in recent_r:
        memo = str(r.get("memo", "") or "")[:100]
        rlines.append(
            f"- {r.get('date')}: {r.get('distance_km')}km, {r.get('pace')}, "
            f"{r.get('duration_min')}분, RPE {r.get('rpe')}, {memo}"
        )
    run_block = "\n".join(rlines) if rlines else "(러닝 기록 없음)"

    nt = profile.get("nutrition_targets", {}) or {}
    prof_bits = [
        f"대회일: {profile.get('goal_race_date', '')}",
        f"목표 기록: {profile.get('goal_marathon_time', '')}",
        f"목표 섭취: {nt}",
    ]
    prof_block = "\n".join(prof_bits)

    plan_md = str(profile.get("custom_run_plan_md") or "").strip()
    if len(plan_md) > 2800:
        plan_excerpt = plan_md[:2800] + "\n…(이하 생략)"
    else:
        plan_excerpt = plan_md or "(저장된 훈련 플랜 텍스트 없음)"

    dctx = snippets_for_diet_query(q)
    rctx = snippets_for_running_query(q)
    web_parts: List[str] = []
    if dctx:
        web_parts.append("[웹검색·영양·식단 관련]\n" + dctx)
    if rctx:
        web_parts.append("[웹검색·러닝·마라톤 관련]\n" + rctx)
    web_block = "\n\n".join(web_parts)
    if web_block:
        web_block = "\n" + web_block + "\n"

    hist = conversation_history or []
    hist = hist[-12:]
    hist_lines: List[str] = []
    for turn in hist:
        role = turn.get("role", "")
        content = str(turn.get("content", ""))[:800]
        if role == "user":
            hist_lines.append(f"사용자: {content}")
        elif role == "assistant":
            hist_lines.append(f"코치: {content}")
    hist_block = "\n".join(hist_lines) if hist_lines else "(이전 대화 없음)"

    prompt = f"""
당신은 마라톤 러너를 돕는 통합 코치(식단·훈련)입니다. 사용자 메시지에 한국어로 자연스럽게 답하세요.

반드시 활용할 수 있는 자료:
- [저장된 식단 기록]: 날짜·매크로·식단 텍스트를 인용해 말할 수 있으면 구체적으로 인용하세요.
- [저장된 러닝 기록]: 거리·페이스·RPE·메모를 인용하세요.
- [훈련 플랜(마크다운 발췌)]: 주간 패턴·휴식일·거리대를 질문과 연결해 말할 수 있으면 활용하세요.
- 웹 검색 스니펫이 있으면 보조 근거로만 쓰고, 출처가 불명확하면 단정하지 마세요.

이전 대화 맥락(있으면 이어서 답하세요):
{hist_block}

[프로필]
{prof_block}

[저장된 식단 기록 (최근 일부)]
{diet_block}

[저장된 러닝 기록 (최근 일부)]
{run_block}

[훈련 플랜 발췌]
{plan_excerpt}
{web_block}
[사용자 메시지]
{q}

규칙: 의학적 진단·처방은 하지 마세요. 6~18문장 정도, 대화체로 짧은 문단으로 나누어 써도 됩니다.
"""
    return call_gemini_text(prompt, max_tokens=3200)
