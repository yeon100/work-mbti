"""Parse user markdown running plan (weekly tables) and compare to logged runs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


_WEEKDAY_TO_IDX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# 제목에 "5월" 등이 없을 때(✔ 적응 단계 형식) 구간 순서로 월 매핑
_FALLBACK_PHASE_MONTHS: List[List[int]] = [[5], [6, 7], [8, 9], [10, 11]]


def _split_plan_markdown_chunks(md: str) -> List[str]:
    md = md.strip()
    if not md:
        return []
    if re.search(r"\*\*🗓️|🗓️", md):
        parts = re.split(r"(?=\*\*🗓️|🗓️)", md)
    elif re.search(r"(?:^|\n)\s*✔\s", md):
        parts = re.split(r"(?=(?:^|\n)\s*✔\s)", md)
    else:
        return [md]
    return [p.strip() for p in parts if p and p.strip()]


def _chunk_title_line(lines: List[str]) -> str:
    for ln in lines[:12]:
        s = ln.strip()
        if s and not s.startswith("|"):
            return re.sub(r"\*+", "", s).replace("🗓️", "").strip()
    return ""


def _resolve_months_for_chunk(chunk_index: int, title_line: str) -> List[int]:
    m = _parse_months_from_title(title_line)
    if m:
        return m
    if chunk_index < len(_FALLBACK_PHASE_MONTHS):
        return list(_FALLBACK_PHASE_MONTHS[chunk_index])
    return []


@dataclass
class DayRule:
    content: str
    distance_raw: str
    pace_raw: str
    is_rest: bool
    is_optional: bool
    km_ranges: List[Tuple[float, float]]  # OR match if multiple


@dataclass
class Phase:
    title: str
    months: List[int]
    by_weekday: Dict[int, DayRule]  # 0=Mon .. 6=Sun


def _parse_months_from_title(title: str) -> List[int]:
    t = title.strip()
    # 괄호 안 문구(예: 10월까지만)는 월 구간 판별에서 제외 → 폴백 월 매핑이 깨지지 않게 함
    t = re.sub(r"\([^)]*\)", "", t)
    m = re.search(r"(\d{1,2})\s*~\s*(\d{1,2})\s*월", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b:
            return list(range(a, b + 1))
    m = re.findall(r"(\d{1,2})\s*월", t)
    if m:
        return sorted({int(x) for x in m})
    return []


def _split_md_row(line: str) -> List[str]:
    s = line.strip()
    if not s.startswith("|"):
        return []
    parts = [p.strip() for p in s.strip("|").split("|")]
    return parts


def _is_separator_row(cells: List[str]) -> bool:
    if not cells:
        return True
    joined = "".join(cells)
    return bool(re.fullmatch(r"[\s\-:|]+", joined))


def _parse_km_ranges(dist: str) -> Tuple[bool, List[Tuple[float, float]]]:
    """Returns (is_explicit_rest, ranges). Empty ranges + not rest => unknown."""
    d = (dist or "").strip()
    if not d or d in ("-", "—", "–", "휴식"):
        return True, []
    if "휴식" in d and not re.search(r"\d", d):
        return True, []
    ranges: List[Tuple[float, float]] = []
    for a, b in re.findall(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)", d):
        lo, hi = float(a), float(b)
        ranges.append((min(lo, hi), max(lo, hi)))
    if not ranges:
        m = re.search(r"(\d+(?:\.\d+)?)\s*km", d, re.I)
        if m:
            v = float(m.group(1))
            return False, [(v, v)]
    return False, ranges


def _row_to_rule(cells: List[str]) -> Optional[DayRule]:
    if len(cells) < 3:
        return None
    wday = cells[0].strip()
    content = cells[1].strip() if len(cells) > 1 else ""
    dist = cells[2].strip() if len(cells) > 2 else ""
    pace = cells[3].strip() if len(cells) > 3 else ""
    opt = "선택" in content
    rest_kw = "휴식" in content or dist.strip() in ("-", "—", "–", "")
    is_rest, ranges = _parse_km_ranges(dist)
    if rest_kw and not ranges:
        is_rest = True
    return DayRule(
        content=content,
        distance_raw=dist,
        pace_raw=pace,
        is_rest=is_rest,
        is_optional=opt,
        km_ranges=ranges,
    )


def _weekday_keys_from_cell(first_cell: str) -> List[int]:
    s = first_cell.strip()
    if "토/일" in s or "토·일" in s:
        return [5, 6]
    if s in _WEEKDAY_TO_IDX:
        return [_WEEKDAY_TO_IDX[s]]
    # "월요일" 등
    for k, idx in _WEEKDAY_TO_IDX.items():
        if s.startswith(k):
            return [idx]
    return []


# 월 타이틀 줄: `# **🗓️ 5월**`, `** 🗓️ 5월 **`, 전각 별 등 허용
_MONTH_BANNER_LINE = re.compile(
    r"^\s*(?:#{1,6}\s+)?"
    r"(?:(?:\*|＊){1,2}\s*)?"
    r"🗓️\s*(\d{1,2})\s*월\s*"
    r"(?:(?:\*|＊){1,2})?\s*$",
)


def strip_leading_month_banner(md: str, month: int) -> str:
    """첫 줄(들)이 해당 월의 `🗓️ N월` 배너면 제거. 중복 헤더·저장 시 이중 접두 모두 방지."""
    s = (md or "").strip()
    while s:
        lines = s.splitlines()
        if not lines:
            break
        first = lines[0].strip()
        mm = _MONTH_BANNER_LINE.match(first)
        if mm and int(mm.group(1)) == month:
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
            s = "\n".join(lines).strip()
            continue
        break
    return s


def extract_month_plan_sections(md: str) -> Dict[int, str]:
    """플랜 마크다운에서 월(숫자) → 해당 구간 원문 청크. 탭 표시용."""
    if not md or not md.strip():
        return {}
    out: Dict[int, str] = {}
    raw_chunks = _split_plan_markdown_chunks(md)
    for ci, chunk in enumerate(raw_chunks):
        lines = chunk.splitlines()
        title_line = _chunk_title_line(lines)
        months = _resolve_months_for_chunk(ci, title_line)
        if not months:
            continue
        for m in months:
            if m not in out:
                # 탭/편집기에는 본문만(배너 제거). 저장 시 또 붙는 `**🗓️ N월**`와 겹치지 않게 함.
                out[m] = strip_leading_month_banner(chunk, m)
    return out


def build_plan_markdown_from_month_bodies(month_bodies: Dict[int, str]) -> str:
    """5~11월 각각 독립 편집본을 `🗓️ N월` 블록으로 이어 붙인다."""
    parts: List[str] = []
    for m in range(5, 12):
        raw = strip_leading_month_banner(str(month_bodies.get(m) or ""), m)
        if not raw:
            continue
        parts.append(f"🗓️ {m}월\n\n{raw}")
    return "\n\n".join(parts)


def parse_custom_plan_markdown(md: str) -> List[Phase]:
    if not md or not md.strip():
        return []
    raw_chunks = _split_plan_markdown_chunks(md)
    phases: List[Phase] = []
    for ci, chunk in enumerate(raw_chunks):
        lines = chunk.splitlines()
        title_line = _chunk_title_line(lines)
        months = _resolve_months_for_chunk(ci, title_line)
        if not months:
            continue
        by_weekday: Dict[int, DayRule] = {}
        in_table = False
        header_seen = False
        for ln in lines:
            cells = _split_md_row(ln)
            if not cells:
                continue
            if len(cells) >= 3 and "요일" in cells[0]:
                in_table = True
                header_seen = True
                continue
            if not in_table or not header_seen:
                continue
            if _is_separator_row(cells):
                continue
            keys = _weekday_keys_from_cell(cells[0])
            if not keys:
                continue
            rule = _row_to_rule(cells)
            if not rule:
                continue
            for k in keys:
                by_weekday[k] = rule
        if by_weekday:
            phases.append(Phase(title=title_line or "플랜", months=months, by_weekday=by_weekday))
    return phases


def _phase_for_date(phases: List[Phase], d: date) -> Optional[Phase]:
    m = d.month
    for ph in phases:
        if m in ph.months:
            return ph
    return None


def _km_matches(rule: DayRule, actual_km: float) -> bool:
    if rule.is_rest:
        return actual_km <= 0.5
    if rule.is_optional and actual_km <= 0.5:
        return True
    if not rule.km_ranges:
        return True
    for lo, hi in rule.km_ranges:
        if lo - 0.51 <= actual_km <= hi + 0.51:
            return True
    return False


def planned_summary_for_date(phases: List[Phase], d: date) -> str:
    ph = _phase_for_date(phases, d)
    if not ph:
        return ""
    wd = d.weekday()
    rule = ph.by_weekday.get(wd)
    if not rule:
        return ""
    bits = [rule.content or "", rule.distance_raw or "", rule.pace_raw or ""]
    return " · ".join(b for b in bits if b).strip()


def match_run_to_plan(phases: List[Phase], d: date, distance_km: float, memo: str = "") -> Tuple[str, str]:
    """Returns (icon, detail). icon: O / X / —"""
    ph = _phase_for_date(phases, d)
    if not ph:
        return "—", "플랜 없음"
    wd = d.weekday()
    rule = ph.by_weekday.get(wd)
    if not rule:
        return "—", "요일 매칭 없음"
    memo_l = (memo or "").lower()
    rest_flag = distance_km <= 0.5 or "휴식" in memo_l
    if rule.is_rest:
        ok = rest_flag or distance_km <= 0.5
        return ("O" if ok else "X"), ("휴식 예정" if ok else f"휴식인데 {distance_km}km")
    ok = _km_matches(rule, distance_km)
    detail = f"계획:{rule.distance_raw or rule.content} / 실제:{distance_km}km"
    return ("O" if ok else "X"), detail


def load_phases_from_profile(profile: Dict[str, Any]) -> List[Phase]:
    md = str(profile.get("custom_run_plan_md") or "").strip()
    return parse_custom_plan_markdown(md)
