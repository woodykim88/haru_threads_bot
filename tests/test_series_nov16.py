"""2026-11-16 개편 (사용자 승인 "개선안 모두 반영"): 팔로워 25명·좋아요 거의 0 → 연재 집중·번호, 짧고 웃기게,
조연 한 명, 소재 반복 금지, 16:00 그림 A/B 1주 시험, 목요일 CalNote 회의 편."""
from src import channel, compose, persona, schedule
from src.history import HistoryEntry
from src.persona import PersonaPost
from tests.helpers import fake_llm

MODELS = compose.Models('w', 'f')


def _corner(day: str):
    key = f'{day}T16:00'
    found = persona.corner_for(schedule.slot_datetime(key), key)
    return found[0] if found else None


def _past(slot: str, caption: str) -> HistoryEntry:
    return HistoryEntry(slot=slot, status='PUBLISHED', title='t', seed=persona.KIND, caption=caption)


def test_weekly_series_focus_on_two_corners_plus_meeting():
    week = [_corner(f'2026-11-{d}') for d in range(16, 23)]  # 월~일
    assert week[:6] == [persona.SQUIRREL[0], persona.MOM_CALL[0], persona.SQUIRREL[0], persona.MEETING[0],
                        persona.MOM_CALL[0], persona.MOM_CALL[0]]
    assert week[6] is None  # 일요일은 주말 형식


def test_series_number_continues_from_history():
    past = (_past('2026-11-03T16:00', '엄마 토끼 전화 어록: "a" → 번역: b'),
            _past('2026-11-05T16:00', '엄마 토끼 전화 어록: "c" → 번역: d'),
            _past('2026-11-06T16:00', '다람쥐 동기 속보: e'))
    out = persona.number_series('엄마 토끼 전화 어록: "밥은 먹었니?" → 번역: 김장 와라', '엄마 토끼 전화 어록', past)
    assert out.startswith('엄마 토끼 전화 어록 #3: "밥은 먹었니?"')


def test_only_one_cast_member_per_post():
    assert persona.cast_issues('엄마 토끼가 전화했는데 다람쥐 동기도 카톡 했어')
    assert persona.cast_issues('엄마 토끼 전화 어록: "밥은?" → 번역: 김장 와라') == []


def test_post_must_not_end_with_sigh():
    assert persona.punchline_issues('봄이 신혼 사진 봤어\n나는 이불이랑 약속했지 ㅠㅠ')
    assert persona.punchline_issues('봄이 신혼 사진 봤어\n내 신혼집은 전기장판 위 1인용 ㅋㅋ') == []


def test_repeated_topic_within_14_days_is_rejected():
    past = (_past('2026-11-10T23:30', '봄이가 신혼집 사진을 보냈어'),)
    now = schedule.slot_datetime('2026-11-20T23:30')
    assert persona.repeat_issues('봄이가 신혼여행 다녀왔대', past, now)
    later = schedule.slot_datetime('2026-11-30T23:30')
    assert persona.repeat_issues('봄이가 신혼여행 다녀왔대', past, later) == []
    assert persona.repeat_issues('다람쥐 동기가 간식 줬어', past, now) == []


def test_posts_are_short():
    assert persona.MAX_CHARS <= 120


def test_meeting_day_adds_calnote_reply_with_tracked_link():
    key = '2026-11-19T16:00'  # 목요일
    text = '부엉이 부장 회의 생존기: 회의 40분째, 부장님 "한 가지만 더"가 벌써 다섯 번째 ㅋㅋ'
    llm, _ = fake_llm({'PersonaPost': [PersonaPost(text=text, scene='Haru in a meeting')]})
    draft = compose.compose(llm, MODELS, (), key)
    first, reply = draft.parts
    assert first.startswith('부엉이 부장 회의 생존기 #1') and 'http' not in first
    assert 'apps.apple.com' in reply and 'ct=threads_haru' in reply and 'CalNote' in reply


def test_other_days_have_no_reply():
    key = '2026-11-17T16:00'  # 화요일 어록
    text = '엄마 토끼 전화 어록: "밥은 먹었니?" → 번역: 이번 주말 김장 인력 구함 ㅋㅋ'
    llm, _ = fake_llm({'PersonaPost': [PersonaPost(text=text)]})
    assert len(compose.compose(llm, MODELS, (), key).parts) == 1


def test_image_ab_test_alternates_days_on_series_slot_for_one_week():
    days = [f'2026-11-{d}' for d in range(17, 24)]
    flags = [channel.wants_image(f'{d}T16:00') for d in days]
    assert 3 <= flags.count(True) <= 4 and flags[0] != flags[1]
    assert not channel.wants_image('2026-11-17T23:30') and not channel.wants_image('2026-11-18T23:30')
    assert not channel.wants_image('2026-11-25T16:00') and not channel.wants_image('2026-11-26T16:00')
