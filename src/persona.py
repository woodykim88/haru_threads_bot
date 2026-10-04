"""캐릭터 글 한 편 만들기: 토끼 "하루"의 일상·공감 글 (첫 글 하나, 링크·광고 없음).

- 하루는 캐릭터라서 1인칭 일상 이야기를 해도 된다 (다른 채널의 1인칭 후기 금지와 다름). 대신 실제 사람인 척은 금지.
- 모든 글에 질문을 붙이면 기계적으로 보이므로 형식을 돌려 가며 쓴다.
  2026-10-03부터 12:30(조연 점심 장면)·20:00("이거 나만 그래?" 저녁 장면)은 마지막 줄이 질문이어야 한다.
- 16:00·23:30 글에는 하루 걸러 공유 줄(태그·리포스트)을 코드가 붙인다 (with_share_line).
- 검수에 두 번 떨어지면 준비된 캐릭터 글로 올린다 (회차를 건너뛰지 않음).
"""
from __future__ import annotations

import random
import re
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from src import kr_calendar
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
# 형식: (설명, 질문 필요, 밸런스 게임 여부). 2026-09-28 사용자 피드백으로 시간대마다 역할을 나눴다.
BALANCE = ('밸런스 게임: 둘 다 달콤하거나 둘 다 괴로워서 진짜 고민되는 30대 딜레마(돈·연애·결혼·회사·명절). '
           '첫 줄에 상황 한 줄, 다음 줄에 "A. …" "B. …"를 따로 쓰고, 하루는 답을 고르지 말고 "친구들은?"으로 넘겨', True, True)
# 2026-10-03 성과 반영: 질문 있는 글 중앙값 126.5 vs 없는 글 83, "이거 나만 그래?" + 구체적 장면 + 질문과
# 조연 등장 회사 에피소드가 상위권. 12:30 참여 코너(빈칸·체크리스트·A/B)와 20:00 질문 없는 위로·일기는 하위권이라 바꿨다.
LUNCH_CAST = ('점심시간 조연 장면: 다람쥐 동기나 부엉이 부장이 나오는 점심시간의 짧은 장면 하나 (예: 다람쥐 동기의 속닥 소문, '
              '밥 먹으러 나가는 길에 부엉이 부장의 "잠깐 얘기 좀 할까?"). 주말이면 친구 토끼 봄이와의 브런치나 엄마 토끼 전화로. '
              '마지막 줄은 친구들이 한 줄로 답하기 쉬운 짧은 질문 하나', True, False)
LUNCH_FRIENDS = ('점심시간 조연 장면: 친구 토끼 봄이나 엄마 토끼한테 점심때 온 카톡·전화 한 장면 (예: 봄이의 신혼 자랑 사진, '
                 '엄마 토끼의 "좋은 토끼 없니?"). 마지막 줄은 친구들이 한 줄로 답하기 쉬운 짧은 질문 하나', True, False)
EVENING_SAME = ('"이거 나만 그래?" 퇴근 후 공감: 퇴근길이나 집에 와서의 콕 집히는 구체적 장면 하나 (예: 가방 멘 채로 침대에 눕기, '
                '저녁 메뉴 30분 고민하다 결국 라면). 마지막 줄은 "이거 나만 그래?"나 쉽게 답할 수 있는 한 줄 질문', True, False)
EVENING_ASK = ('저녁 공감 + 질문: 오늘 회사에서 들고 온 기분이 집에서 터지는 구체적 장면 하나 + 마지막 줄에 '
               '"다들 ~해?"처럼 한 줄로 답하기 쉬운 질문', True, False)
SLOT_FORMATS = {
    '09:00': (('한숨 공감 한 줄: 출근 전 아침의 콕 집히는 장면 하나 (질문 없이 짧게)', False, False),
              ('"이거 나만 그래?" 아침 공감: 출근 준비의 구체적 장면 + 짧은 질문', True, False)),
    '12:30': (LUNCH_CAST, LUNCH_CAST, LUNCH_FRIENDS),
    '16:00': (('회사 에피소드: 조연(부엉이 부장·다람쥐 동기 등)이 나오는 오늘의 짧은 사건 한 장면 + 하루의 속마음 (질문 없이)', False, False),
              ('시리즈 "오늘의 퇴사 충동 지수": 오늘 회사에서 있었던 구체적 사건으로 10점 만점 채점 + 한 줄 평 (질문 없이)', False, False)),
    '20:00': (EVENING_SAME, EVENING_ASK),
    '23:30': (('밤의 속마음: 연애·결혼·돈·인생 고민 하나를 구체적 장면으로 털어놓고 스스로 다독이기 (질문 없이)', False, False),
              ('밤의 속마음 + 질문: 연애·결혼·돈 고민 하나를 털어놓고 친구들에게 조심스럽게 묻기', True, False)),
}
# 마지막 줄이 질문이어야 하는 시각 (주말에도 같은 형식)
ENDS_WITH_QUESTION = ('12:30', '20:00')
# prompts/persona.md의 밸런스 게임 예시 (그대로 베끼면 탈락)
PROMPT_EXAMPLES = ('연봉 30% 인상', '3년 연애 금지', '3년 월급 동결', '10번 듣기')
WEEKEND_FORMATS = (BALANCE, ('"이거 나만 그래?" 주말 공감: 늦잠·약속·늘어짐 중 하나를 (내일 출근하는 날일 때만 일요일 밤 출근 걱정도 가능) 구체적 장면으로 + 짧은 질문', True, False), ('주말 공감: 늘어짐·약속 중 하나를 (내일 출근하는 날일 때만 일요일 밤 출근 걱정도 가능) 구체적 장면으로 (질문 없이)', False, False))
# 요일 테마 (월=0). 공감 포인트를 요일마다 다르게.
WEEKDAY_THEMES = ('월요병, 출근이 세상에서 제일 싫은 날', '아직 화요일이라니, 주말이 너무 멀다', '수요일 고비, 반은 왔다',
                  '목요일, 금요일만 보고 버티기', '불금, 칼퇴와 주말 계획', '늘어지는 토요일, 늦잠과 약속 사이',
                  '일요일 밤의 출근 공포, 내일 걱정')
# 특별한 날 (MM-DD)
SPECIAL_DAYS = {'11-30': '하루 생일! 친구들에게 축하받는 날', '12-24': '크리스마스 이브', '12-25': '크리스마스',
                '12-31': '한 해 마지막 날', '01-01': '새해 첫날', '02-14': '밸런타인데이', '10-31': '핼러윈'}
BANNED = ('http', 'www.', '#', '구매', '할인', '링크', '광고', '협찬', '쿠팡', '무조건', '100%')
# 실제 사람인 척하는 표현 (AI 표시를 하지 않는 대신 반드시 막는다)
# 2026-09-27 타깃 변경 뒤: 회사·연애·결혼·돈 고민은 "토끼 세계" 이야기로 허용하고, 사람 신상 주장만 막는다.
HUMAN_CLAIMS = re.compile(
    r'사람이라서|인간이라서|사람인 나|인간인 나|사람으로서|여자로서|여자인 나|여성으로서|'
    r'[2-5]0대 (여자|여성|남자)|여자 사람|여대생|직장인 여성|서울 사는|강남 사는')
# 2026-09-28 사용자 피드백: 하루가 사는 곳은 "굴" 대신 "집" (뒹굴·얼굴 같은 낱말은 괜찮음)
BURROW = re.compile(r'(^|[\s"\'(])굴(?=$|[\s.,!?~ㅋㅠ에로을이은의도만])')
MONEY_ADVICE = re.compile(r'주식 추천|종목|코인|비트코인|수익률|투자하세요|사세요|대출 받')
FALLBACKS = (
    '알람 다섯 번째… 당근 회사 오늘 쉬면 안 될까 🐰',
    '월급이 통장을 스쳐 갔어. 당근 하나로 버텨 보자 🥕',
    '오늘도 버틴 친구들, 진짜 수고했어. 다들 퇴근했어?',
    '잠은 안 오고 생각만 많은 밤… 다들 아직 안 자? 🌙',
    '칼퇴하고 집에 누우면 그게 행복이지 뭐 🐰',
)
# 시간대 형식에 맞춘 준비된 글 (마지막 줄이 질문). 없는 시각은 FALLBACKS.
SLOT_FALLBACKS = {
    '12:30': (
        '점심 먹는데 다람쥐 동기가 "오늘 부장님 기분 별로래" 속닥였어 🥕\n다들 점심때 제일 먼저 듣는 소문 뭐야?',
        '밥 먹으러 나가는데 부엉이 부장이 "잠깐 얘기 좀 할까?"…\n점심시간에 불리는 거 다들 겪어 봤지?',
        '점심 먹고 왔더니 다람쥐 동기가 간식을 책상에 두고 갔어 🐿️\n다들 회사에 이런 동기 있어?',
    ),
    '20:00': (
        '퇴근하고 집 오자마자 가방 멘 채로 침대에 누웠어 🐰\n이거 나만 그래?',
        '저녁 뭐 먹지 30분 고민하다 결국 당근 하나 먹었어 🥕\n다들 오늘 저녁 뭐 먹었어?',
        '집에 오니까 회사에서 참은 한숨이 한꺼번에 나와…\n다들 퇴근하면 제일 먼저 뭐 해?',
    ),
}
# 공유 부탁 줄: 16:00·23:30 글 끝에 코드가 붙인다 (AI가 빼먹지 않게). 조건부 부탁("~하면 ~해 줄게")은 금지.
# SHARE_EVERY=2 → 날짜 서수 + 시각 순번이 짝수인 글에만 붙여 하루 한 번, 두 시각을 번갈아 간다.
SHARE_SLOTS = ('16:00', '23:30')
SHARE_EVERY = 2
SHARE_LINES = (
    '공감되면 리포스트 🔁',
    '이거 완전 너다 싶은 친구 있으면 태그해 줘 🐰',
    '생각나는 친구 있으면 슬쩍 태그해 줘',
    '나랑 같은 친구들한테도 리포스트 🔁',
)
# 조건부 참여 유도("리포스트하면 ~", "좋아요 누르면 ~")는 Meta가 도달을 줄인다. AI 글에서도 막는다.
ENGAGEMENT_BAIT = re.compile(r'(리포스트|좋아요|팔로우|댓글|태그|공유)[^\n]{0,6}(하면|해 ?주면|누르면|달면|남기면)')


class PersonaPost(BaseModel):
    text: str = Field(description="하루의 Threads 글 한 개, 10~150자")
    scene: str = Field(default='', description='이 글에 어울리는 그림 장면을 영어 한두 문장으로 (토끼 하루가 무엇을 하는지, 배경·소품)')


def context_line(now: datetime, slot_time: str) -> str:
    mood = MOODS.get(slot_time, '평범한 하루')
    off = kr_calendar.is_day_off(now.date())
    if off:  # 주말·공휴일엔 회사 장면 대신 늘어짐·약속 (내일 출근이면 그 걱정도 가능)
        why = '주말' if now.weekday() >= 5 else '공휴일'
        mood = f'{why}이라 쉬는 날, 회사는 안 가 (이 시간대 원래 분위기는 참고만: {mood})'
    special = SPECIAL_DAYS.get(f'{now:%m-%d}')
    theme = '쉬는 날 (아래 달력 사실을 따라)' if off and now.weekday() < 5 else WEEKDAY_THEMES[now.weekday()]
    return (f'지금: {now:%m월 %d일} {WEEKDAYS[now.weekday()]}요일 {slot_time}, {SEASONS[now.month]}\n이 시간 분위기: {mood}\n'
            f'요일 테마: {theme}\n달력 사실(대한민국 공휴일 반영, 어기지 마): {kr_calendar.describe(now.date())}'
            + (f'\n오늘은 특별한 날: {special}' if special else ''))


def issues(text: str, needs_question: bool) -> list[str]:
    found = []
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        found.append(f'{MIN_CHARS}~{MAX_CHARS}자로 쓰세요 (현재 {len(text)}자).')
    banned = [w for w in BANNED if w in text]
    if banned:
        found.append(f'링크·해시태그·광고 표현을 빼세요: {", ".join(banned)}')
    advice = MONEY_ADVICE.search(text)
    if advice:
        found.append(f'투자·재테크 조언처럼 보이는 표현("{advice.group(0)}")은 빼고 공감으로만 쓰세요.')
    if BURROW.search(text):
        found.append('"굴" 대신 "집"이라고 쓰세요 (예: 퇴근하고 집에 누웠어).')
    human = HUMAN_CLAIMS.search(text)
    if human:
        found.append(f'하루는 토끼 캐릭터야. 실제 사람처럼 보이는 표현("{human.group(0)}")을 빼세요.')
    bait = ENGAGEMENT_BAIT.search(text)
    if bait:
        found.append(f'"{bait.group(0)}" 같은 조건부 참여 유도는 빼세요.')
    if needs_question and '?' not in text:
        found.append('이번 형식은 질문이 필요해요. 물음표가 있는 가벼운 질문을 넣으세요.')
    return found


def ending_issues(text: str) -> list[str]:
    """마지막 줄이 한 줄 질문이어야 하는 시각(ENDS_WITH_QUESTION)용."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines or '?' not in lines[-1]:
        return ['마지막 줄을 친구들이 쉽게 답할 수 있는 한 줄 질문(물음표 포함)으로 끝내세요.']
    return []


def pick_format(now: datetime, slot: str) -> tuple[str, bool, bool]:
    """시간대 역할에 맞는 형식을 고릅니다. 주말은 회사 장면 대신 주말 형식 (12:30·20:00은 주말에도 같은 형식)."""
    options = SLOT_FORMATS.get(slot[-5:], SLOT_FORMATS['20:00'])
    if kr_calendar.is_day_off(now.date()) and slot[-5:] not in ENDS_WITH_QUESTION:
        options = WEEKEND_FORMATS
    return random.Random(slot).choice(options)


def balance_issues(text: str) -> list[str]:
    """밸런스 게임은 A/B가 한눈에 보이고, 하루가 답을 정하지 않아야 한다."""
    found = []
    if not (re.search(r'(^|\n)\s*A[.)]', text) and re.search(r'\n\s*B[.)]', text)):
        found.append('A. / B. 선택지를 줄을 나눠 쓰세요.')
    if any(example in text for example in PROMPT_EXAMPLES):
        found.append('프롬프트의 예시를 그대로 쓰지 말고 새 딜레마를 만드세요.')
    if re.search(r'(난|나는|하루는)\s*(무조건\s*)?(A|B|전자|후자)', text):
        found.append('하루가 답을 고르지 말고 친구들에게 넘기세요.')
    return found


FALLBACK_SCENE = 'Haru is curled up asleep in a straw blanket, hugging a carrot, in her cozy little home.'


def wants_share_line(slot: str) -> bool:
    """16:00·23:30 글 중 대략 절반에 공유 줄을 붙입니다 (날짜 기준 결정적 순환, SHARE_EVERY)."""
    hhmm = slot[-5:]
    if hhmm not in SHARE_SLOTS:
        return False
    from src import schedule
    return (schedule.slot_datetime(slot).toordinal() + SHARE_SLOTS.index(hhmm)) % SHARE_EVERY == 0


def with_share_line(text: str, slot: str) -> str:
    """공유 줄을 붙입니다. 마지막 줄이 질문이면 질문이 끝에 남도록 그 앞에 넣습니다."""
    if not wants_share_line(slot):
        return text
    share = random.Random(slot).choice(SHARE_LINES)
    lines = text.strip().splitlines()
    if len(lines) > 1 and '?' in lines[-1]:
        return '\n'.join([*lines[:-1], share, lines[-1]])
    return f'{text.strip()}\n\n{share}'


def strip_share_lines(text: str) -> str:
    return '\n'.join(line for line in text.splitlines() if line.strip() not in SHARE_LINES).strip()


def compose_persona(llm: LLMClient, model: str, history: Sequence[HistoryEntry], slot: str) -> tuple[str, bool, str]:
    """(글, 준비된 글을 썼는지, 그림 장면)을 반환합니다. slot은 '2026-09-27T12:30' 형식."""
    from src import schedule

    now = schedule.slot_datetime(slot)
    fmt, needs_question, is_balance = pick_format(now, slot)
    recent = [strip_share_lines(e.caption) for e in history if e.seed == KIND and e.caption][-RECENT:]
    user_input = (f'{context_line(now, slot[-5:])}\n이번 형식: {fmt}\n'
                  '최근에 올린 글 (겹치지 않게):\n' + ('\n'.join(f'- {t}' for t in recent) or '(없음)'))
    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        extra = ('\n\n이전 글이 검수에서 떨어졌어. 고쳐서 다시 써:\n' + '\n'.join(f'- {f}' for f in feedback)) if feedback else ''
        result = llm.parse(model, load_prompt('persona'), user_input + extra, PersonaPost)
        text = result.text.strip()
        feedback = (issues(text, needs_question) + kr_calendar.commute_issues(text, now.date()) + (balance_issues(text) if is_balance else [])
                    + (ending_issues(text) if slot[-5:] in ENDS_WITH_QUESTION else []))
        if not feedback:
            print(f'[하루 글 통과] 시도 {attempt} ({fmt.split(":")[0]})')
            return text, False, result.scene.strip() or FALLBACK_SCENE
        print(f'[하루 글 탈락] 시도 {attempt}: ' + ' / '.join(feedback))
    return random.Random(slot).choice(SLOT_FALLBACKS.get(slot[-5:], FALLBACKS)), True, FALLBACK_SCENE
