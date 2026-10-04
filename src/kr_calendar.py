"""대한민국 휴무일(공휴일·대체공휴일·주말) 달력.

글이 "내일 월요일 출근"처럼 실제 달력과 어긋나지 않도록 날짜 맥락과 검수에 쓴다.
외부 패키지 없이 CI에서도 돌도록 표로 가지고 있다 (2026~2027, python-holidays 기준으로 대조).
표에 없는 해는 주말만 쉬는 날로 본다. 해가 바뀌기 전에 다음 해 표를 채울 것.
제헌절은 법정 공휴일이 아니라 뺐다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = '월화수목금토일'
HOLIDAYS: dict[date, str] = {
    date(2026, 1, 1): '신정', date(2026, 2, 16): '설날 연휴', date(2026, 2, 17): '설날', date(2026, 2, 18): '설날 연휴',
    date(2026, 3, 1): '삼일절', date(2026, 3, 2): '삼일절 대체공휴일', date(2026, 5, 1): '노동절',
    date(2026, 5, 5): '어린이날', date(2026, 5, 24): '부처님오신날', date(2026, 5, 25): '부처님오신날 대체공휴일',
    date(2026, 6, 3): '지방선거일', date(2026, 6, 6): '현충일', date(2026, 8, 15): '광복절',
    date(2026, 8, 17): '광복절 대체공휴일', date(2026, 9, 24): '추석 연휴', date(2026, 9, 25): '추석',
    date(2026, 9, 26): '추석 연휴', date(2026, 10, 3): '개천절', date(2026, 10, 5): '개천절 대체공휴일',
    date(2026, 10, 9): '한글날', date(2026, 12, 25): '크리스마스',
    date(2027, 1, 1): '신정', date(2027, 2, 6): '설날 연휴', date(2027, 2, 7): '설날', date(2027, 2, 8): '설날 연휴',
    date(2027, 2, 9): '설날 대체공휴일', date(2027, 3, 1): '삼일절', date(2027, 5, 1): '노동절',
    date(2027, 5, 3): '노동절 대체공휴일', date(2027, 5, 5): '어린이날', date(2027, 5, 13): '부처님오신날',
    date(2027, 6, 6): '현충일', date(2027, 8, 15): '광복절', date(2027, 8, 16): '광복절 대체공휴일',
    date(2027, 9, 14): '추석 연휴', date(2027, 9, 15): '추석', date(2027, 9, 16): '추석 연휴',
    date(2027, 10, 3): '개천절', date(2027, 10, 4): '개천절 대체공휴일', date(2027, 10, 9): '한글날',
    date(2027, 10, 11): '한글날 대체공휴일', date(2027, 12, 25): '크리스마스',
    date(2027, 12, 27): '크리스마스 대체공휴일',
}
# "내일(월요일) 출근"처럼 내일 일하러 간다는 말
_COMMUTE_TOMORROW = re.compile(r'(내일|월요일|낼)[^\n.!?]{0,12}(출근|회사 가|출근길)|(출근|회사 가)[^\n.!?]{0,8}(내일|월요일)')

_NEGATION = re.compile(r'안 ?(가|해|하|나)|없|쉬는|쉰|휴무|휴일|공휴일')


def day_off_name(day: date) -> str | None:
    """쉬는 날이면 이름(공휴일명·토요일·일요일), 평일이면 None."""
    name = HOLIDAYS.get(day)
    if name:
        return name
    if day.weekday() >= 5:
        return f'{WEEKDAYS[day.weekday()]}요일'
    return None


def is_day_off(day: date) -> bool:
    return day_off_name(day) is not None


def _label(day: date) -> str:
    return f'{day.month}월 {day.day}일 {WEEKDAYS[day.weekday()]}요일'


def describe(day: date) -> str:
    """프롬프트에 넣을 달력 사실. 오늘·내일이 쉬는 날인지 분명하게 적는다."""
    today, tomorrow = HOLIDAYS.get(day), day + timedelta(days=1)
    lines = []
    if today:
        lines.append(f'오늘은 {today}라서 쉬는 날 (평일이어도 회사에 안 가)')
    elif day.weekday() >= 5:
        lines.append(f'오늘은 {WEEKDAYS[day.weekday()]}요일이라 쉬는 날')
    next_name = day_off_name(tomorrow)
    if next_name and HOLIDAYS.get(tomorrow):
        lines.append(f'내일({_label(tomorrow)})은 {next_name}라서 쉬는 날: 내일 출근하지 않아. '
                     '"내일 출근", "월요일 출근 준비", 일요일 밤 출근 걱정 소재는 쓰지 마')
    elif next_name:
        lines.append(f'내일은 {next_name}이라 쉬는 날')
    else:
        lines.append(f'내일은 출근하는 평일({_label(tomorrow)})')
    return '\n'.join(lines)


def commute_issues(text: str, day: date) -> list[str]:
    """내일이 평일 공휴일(대체공휴일 포함)인데 내일 출근한다고 쓴 글을 잡는다. "출근 안 해"는 통과."""
    tomorrow = day + timedelta(days=1)
    if not (tomorrow in HOLIDAYS and tomorrow.weekday() < 5):
        return []
    for m in _COMMUTE_TOMORROW.finditer(text):
        if not _NEGATION.search(text[m.start():m.end() + 8]):
            return [f'내일({_label(tomorrow)})은 {HOLIDAYS[tomorrow]}라서 쉬는 날이야. 내일 출근한다는 내용은 빼고 다시 써.']
    return []
