from datetime import date, datetime

from src import kr_calendar as cal
from src import persona
from src import schedule


def test_substitute_holiday_is_day_off():
    # 2026-10-03 개천절(토) → 10월 5일(월) 대체공휴일
    assert cal.day_off_name(date(2026, 10, 5)) == '개천절 대체공휴일'
    assert cal.is_day_off(date(2026, 10, 5))


def test_plain_weekday_and_weekend():
    assert not cal.is_day_off(date(2026, 10, 6))  # 화
    assert cal.day_off_name(date(2026, 10, 4)) == '일요일'
    assert cal.is_day_off(date(2026, 10, 3))


def test_chuseok_2026_run():
    assert [cal.is_day_off(date(2026, 9, d)) for d in (23, 24, 25, 26, 27, 28)] == [False, True, True, True, True, False]


def test_describe_sunday_before_substitute_monday():
    text = cal.describe(date(2026, 10, 4))
    assert '내일(10월 5일 월요일)은 개천절 대체공휴일' in text
    assert '출근하지 않아' in text


def test_describe_regular_sunday_keeps_work_tomorrow():
    assert '내일은 출근' in cal.describe(date(2026, 10, 11))


def test_describe_holiday_today_on_weekday():
    assert '오늘은 한글날' in cal.describe(date(2026, 10, 9))


def test_unknown_year_falls_back_to_weekend_only():
    assert not cal.is_day_off(date(2031, 1, 8))
    assert cal.is_day_off(date(2031, 1, 11))


def test_work_commute_claim_flagged_when_tomorrow_off():
    assert cal.commute_issues('내일 출근이면 오늘 일찍 쉬어야지', date(2026, 10, 4))
    assert cal.commute_issues('일요일 오후에 월요일 출근 준비', date(2026, 10, 4))
    assert not cal.commute_issues('내일 출근이면 오늘 일찍 쉬어야지', date(2026, 10, 11))
    assert not cal.commute_issues('월요일은 쉬는 날이라 출근 안 해서 좋아', date(2026, 10, 4))
    assert not cal.commute_issues('일요일 밤엔 월요일 출근이 걱정돼', date(2026, 10, 3))
    assert not cal.commute_issues('내일은 쉬는 날이라 늦잠 예약', date(2026, 10, 4))


def test_persona_context_mentions_substitute_holiday():
    now = schedule.slot_datetime('2026-10-04T16:00')
    assert '개천절 대체공휴일' in persona.context_line(now, '16:00')


def test_pick_format_treats_holiday_like_weekend():
    holiday = schedule.slot_datetime('2026-10-05T09:00')
    assert persona.pick_format(holiday, '2026-10-05T09:00') in persona.WEEKEND_FORMATS
