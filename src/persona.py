"""캐릭터 글 한 편 만들기: 토끼 "하루"의 일상·공감 글 (첫 글 하나, 링크·광고 없음).

- 하루는 캐릭터라서 1인칭 일상 이야기를 해도 된다 (다른 채널의 1인칭 후기 금지와 다름). 대신 실제 사람인 척은 금지.
- 모든 글에 질문을 붙이면 기계적으로 보이므로 형식을 돌려 가며 쓴다 (질문형은 대략 절반).
- 검수에 두 번 떨어지면 준비된 캐릭터 글로 올린다 (회차를 건너뛰지 않음).
"""
from __future__ import annotations

import random
import re
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from src.channel import MOODS
from src.history import HistoryEntry
from src.llm import LLMClient, load_prompt

KIND = 'persona'
MIN_CHARS, MAX_CHARS = 8, 200
MAX_ATTEMPTS = 2
RECENT = 15
WEEKDAYS = '월화수목금토일'
SEASONS = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름',
           9: '가을', 10: '가을', 11: '가을'}
FORMATS = (
    ('혼잣말 일상: 지금 하루가 하고 있는 일을 짧게 (질문 없이)', False),
    ('공감 한 줄: "이거 나만 그래?" 류의 공감 포인트', True),
    ('가벼운 질문: 팔로워가 한 줄로 답할 수 있는 질문', True),
    ('밸런스 게임: A vs B 고르기', True),
    ('짧은 한 줄 감성: 기분·날씨·계절을 한 문장으로 (질문 없이)', False),
    ('시리즈 "오늘의 낮잠 점수": 오늘 낮잠(또는 잠)을 10점 만점으로 채점하고 한 줄 평 (질문 없이)', False),
    ('시리즈 "하루의 당근 일기": 오늘의 당근 이야기를 한두 줄 일기처럼 (질문 없이)', False),
)
# 요일 테마 (월=0). 공감 포인트를 요일마다 다르게.
WEEKDAY_THEMES = ('월요병, 다시 시작하는 한 주', '아직 화요일이라니', '한 주의 반, 수요일 고비', '금요일 전날의 설렘',
                  '불금 설렘, 주말 계획', '늘어지는 토요일, 늦잠', '일요일 오후의 아쉬움, 내일 걱정')
# 특별한 날 (MM-DD)
SPECIAL_DAYS = {'11-30': '하루 생일! 굴 친구들에게 축하받는 날', '12-24': '크리스마스 이브', '12-25': '크리스마스',
                '12-31': '한 해 마지막 날', '01-01': '새해 첫날', '02-14': '밸런타인데이', '10-31': '핼러윈'}
BANNED = ('http', 'www.', '#', '구매', '할인', '링크', '광고', '협찬', '쿠팡', '무조건', '100%')
# 실제 사람인 척하는 표현 (AI 표시를 하지 않는 대신 반드시 막는다)
HUMAN_CLAIMS = re.compile(
    r'사람이라서|인간이라서|사람인 나|인간인 나|20대 여자|여자 사람|여대생|남자친구|남친|여자친구|여친|'
    r'내 나이|살 먹은|회사 다니|출근길|퇴근길|대학교|학교 가|월급|알바하')
FALLBACKS = (
    '이불 밖은 위험해… 오늘도 5분만 더 🐰',
    '당근 하나면 기분 좋아지는 거, 나만 그래? 🥕',
    '낮잠 잤더니 벌써 저녁이야 ㅋㅋ 오늘 하루 어땠어?',
    '졸린데 폰 못 놓는 밤… 다들 아직 안 자? 🌙',
    '오늘도 굴에서 뒹굴뒹굴. 이런 날도 있어야지 🐰',
)


class PersonaPost(BaseModel):
    text: str = Field(description="하루의 Threads 글 한 개, 10~150자")


def context_line(now: datetime, slot_time: str) -> str:
    mood = MOODS.get(slot_time, '평범한 하루')
    special = SPECIAL_DAYS.get(f'{now:%m-%d}')
    return (f'지금: {now:%m월 %d일} {WEEKDAYS[now.weekday()]}요일 {slot_time}, {SEASONS[now.month]}\n이 시간 분위기: {mood}\n'
            f'요일 테마: {WEEKDAY_THEMES[now.weekday()]}' + (f'\n오늘은 특별한 날: {special}' if special else ''))


def issues(text: str, needs_question: bool) -> list[str]:
    found = []
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        found.append(f'{MIN_CHARS}~{MAX_CHARS}자로 쓰세요 (현재 {len(text)}자).')
    banned = [w for w in BANNED if w in text]
    if banned:
        found.append(f'링크·해시태그·광고 표현을 빼세요: {", ".join(banned)}')
    human = HUMAN_CLAIMS.search(text)
    if human:
        found.append(f'하루는 토끼 캐릭터야. 실제 사람처럼 보이는 표현("{human.group(0)}")을 빼세요.')
    if needs_question and '?' not in text:
        found.append('이번 형식은 질문이 필요해요. 물음표가 있는 가벼운 질문을 넣으세요.')
    return found


def compose_persona(llm: LLMClient, model: str, history: Sequence[HistoryEntry], slot: str) -> tuple[str, bool]:
    """(글, 준비된 글을 썼는지)를 반환합니다. slot은 '2026-09-27T12:30' 형식."""
    from src import schedule

    now = schedule.slot_datetime(slot)
    fmt, needs_question = random.Random(slot).choice(FORMATS)
    recent = [e.caption for e in history if e.seed == KIND and e.caption][-RECENT:]
    user_input = (f'{context_line(now, slot[-5:])}\n이번 형식: {fmt}\n'
                  '최근에 올린 글 (겹치지 않게):\n' + ('\n'.join(f'- {t}' for t in recent) or '(없음)'))
    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 검수에서 떨어졌어. 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        text = llm.parse(model, load_prompt('persona'), user_input + extra, PersonaPost).text.strip()
        feedback = issues(text, needs_question)
        if not feedback:
            print(f'[하루 글 통과] 시도 {attempt} ({fmt.split(":")[0]})')
            return text, False
        print(f'[하루 글 탈락] 시도 {attempt}: ' + ' / '.join(feedback))
    return random.Random(slot).choice(FALLBACKS), True
