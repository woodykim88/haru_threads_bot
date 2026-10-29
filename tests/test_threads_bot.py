import pytest
from datetime import datetime, timezone

from scripts import due_check
from src import channel, commands, compose, history, notifier, persona, post, schedule, state, threads, token_refresh
from src.persona import PersonaPost
from src.threads import ThreadsClient, ThreadsConfig, ThreadsError
from tests.helpers import AT_1235, Resp, fake_llm

MODELS = compose.Models('w', 'f')
GOOD = '다람쥐 동기가 점심 당근을 두 개나 줬어 🥕\n너라면 ① 낮잠 ② 커피?'
SLOT = '2026-09-27T12:30'


# --- 채널 설정 ---

def test_channel_config_has_four_slots_and_prefix():
    assert len(channel.MOODS) == 4 and schedule.parse_times(channel.DEFAULT_TIMES) == schedule.parse_times(None)
    assert notifier.PREFIX == '[Threads 하루] ' and '/haru_stop' in commands.COMMANDS


# --- 캐릭터 글 검수 ---

def test_persona_issues_block_links_ads_and_human_claims():
    assert persona.issues(GOOD, needs_question=True) == []
    assert persona.issues('오늘 집에서 뒹굴뒹굴 🐰', needs_question=False) == []
    assert any('질문' in i for i in persona.issues('오늘 집에서 뒹굴뒹굴 🐰', needs_question=True))
    assert any('사람' in i for i in persona.issues('30대 여자인 나도 월요일엔 졸려?', needs_question=True))
    assert persona.issues('당근 회사 출근길… 월급날까지 버티자 🐰', needs_question=False) == []  # 토끼 세계 직장 이야기는 허용
    assert any('투자' in i for i in persona.issues('요즘 코인 수익률 봤어?', needs_question=True))
    assert any('집' in i for i in persona.issues('퇴근하고 굴에 누웠어', needs_question=False))
    assert persona.issues('주말엔 집에서 뒹굴뒹굴, 얼굴 팩도 했어', needs_question=False) == []
    assert any('광고' in i for i in persona.issues('이 당근 할인 링크 https://x.com #당근', needs_question=False))
    assert all(not persona.issues(t, needs_question=False) for t in persona.FALLBACKS)
    for hhmm, texts in persona.SLOT_FALLBACKS.items():  # 12:30·20:00 준비된 글도 형식(마지막 줄 질문)에 맞아야 한다
        assert all(not persona.issues(t, needs_question=True) and not persona.ending_issues(t) for t in texts), hhmm
    assert any('조건부' in i for i in persona.issues('리포스트하면 다음 편 올려 줄게?', needs_question=True))


def test_compose_uses_slot_mood_and_recent_posts():
    llm, client = fake_llm({'PersonaPost': [PersonaPost(text=GOOD)] * 2})
    past = (history.HistoryEntry('2026-09-27T09:00', 'PUBLISHED', seed=persona.KIND, caption='이불 밖은 위험해'),)
    draft = compose.compose(llm, MODELS, past, SLOT)
    assert draft.parts == (GOOD,) and draft.key == f'persona:{SLOT}' and not draft.rescued
    sent = client.requests[0]['input']
    assert channel.MOODS['12:30'] in sent and '주말이라' in sent and '이불 밖은 위험해' in sent  # 2026-09-27은 일요일


def test_compose_falls_back_to_prepared_post():
    bad = PersonaPost(text='30대 여자인 나 https://x.com')
    llm, _ = fake_llm({'PersonaPost': [bad, bad]})
    draft = compose.compose(llm, MODELS, (), SLOT)
    assert draft.rescued and draft.parts[0] in persona.SLOT_FALLBACKS['12:30'] and '?' in draft.parts[0]


# --- Threads API · 게시 ---

class Graph:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, params):
        self.calls.append((method, url, dict(params)))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(url)


OK_ROUTES = {'threads_publish': Resp(200, {'id': 'm1'}), '/threads': Resp(200, {'id': 'box'}),
             'm1': Resp(200, {'permalink': 'https://threads/p/1'})}
ENV = {'PUBLISH_TIMES': channel.DEFAULT_TIMES}
ENV_WITH_2000 = {'PUBLISH_TIMES': '09:00,12:30,16:00,20:00,23:30'}  # 20:00은 2026-10-11부터 기본에서 빠짐


def client(routes):
    graph = Graph(routes)
    return ThreadsClient(ThreadsConfig('u1', 'secret'), request=graph, sleep=lambda s: None), graph


def deps(responses):
    c, graph = client(OK_ROUTES)
    return post.PostDeps(fake_llm(responses)[0]._backend, MODELS, c), graph


def test_run_post_publishes_single_post_once():
    d, graph = deps({'PersonaPost': [PersonaPost(text=GOOD)]})
    assert post.run_post(ENV, d, None, AT_1235).outcome == 'success'
    entry = history.find(history.load_history(), SLOT)
    assert entry.status == history.PUBLISHED and entry.seed == persona.KIND and entry.permalink == 'https://threads/p/1'
    creates = [p for m, u, p in graph.calls if u.endswith('/threads')]
    assert [p['text'] for p in creates] == [GOOD]
    assert post.run_post(ENV, d, None, AT_1235).outcome == 'skipped'


def test_run_post_marks_prepared_post():
    bad = PersonaPost(text='30대 여자인 나')
    d, _ = deps({'PersonaPost': [bad, bad]})
    assert post.run_post(ENV, d, None, AT_1235).outcome == 'success'
    assert post.RESCUED_NOTE in history.find(history.load_history(), SLOT).note


def test_run_post_respects_pause():
    d, graph = deps({})
    assert post.run_post({**ENV, 'PAUSED': 'true'}, d, None, AT_1235).outcome == 'skipped' and graph.calls == []


def test_threads_client_errors():
    c, _ = client({'/threads': Resp(400, {'error': {'message': 'bad token', 'code': 190}})})
    with pytest.raises(ThreadsError) as info:
        c.create_text('hi')
    assert info.value.fatal and 'secret' not in str(info.value)


def test_due_check_and_window():
    times = schedule.parse_times(channel.DEFAULT_TIMES)
    assert due_check.is_due(AT_1235, times, ())
    assert not due_check.is_due(AT_1235, times, (history.HistoryEntry(SLOT, history.PUBLISHED),))


def test_token_refresh_saves_without_printing(capsys):
    saved = {}
    r = token_refresh.run_refresh({'THREADS_ACCESS_TOKEN': 'old'}, None, refresh=lambda t: ('new-secret', 60 * 86400),
                                  set_secret=lambda n, v: saved.update({n: v}))
    assert r.outcome == 'success' and 'new-secret' not in capsys.readouterr().out


def test_refresh_token_api():
    graph = Graph({'refresh_access_token': Resp(200, {'access_token': 'n', 'expires_in': 100})})
    assert threads.refresh_token('o', request=graph) == ('n', 100)


def test_post_pending_publishes_saved_draft_once(tmp_path):
    path = tmp_path / 'pending.json'
    post.save_pending(compose.Draft('persona:x', GOOD, (GOOD,)), '2026-09-27T15:30', path)
    c, _ = client(OK_ROUTES)
    assert post.run_pending(c, None, AT_1235, path).outcome == 'success' and not path.exists()
    assert state.load_state().paused is False


# --- 그림 (20:00 슬롯) ---

import base64  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from src import image  # noqa: E402

R2_ENV = {'R2_ACCOUNT_ID': 'a', 'R2_ACCESS_KEY_ID': 'k', 'R2_SECRET_ACCESS_KEY': 's', 'R2_BUCKET': 'b',
          'R2_PUBLIC_BASE_URL': 'https://pub.example/'}
AT_2005 = AT_1235.replace(hour=11, minute=5)   # KST 20:05


class FakeImages:
    def __init__(self):
        self.calls = []

    def edit(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b'jpg').decode())], usage=None)


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def test_make_image_uses_reference_and_uploads():
    images, s3 = FakeImages(), FakeS3()
    url = image.make_image(R2_ENV, 'Haru eating a carrot', '2026-09-27T20:00', SimpleNamespace(images=images), s3)
    assert url.startswith('https://pub.example/threads-haru/2026/09/2026-09-27T2000-') and url.endswith('.jpg')
    assert images.calls[0]['model'] == 'gpt-image-2' and 'Haru eating a carrot' in images.calls[0]['prompt']
    assert s3.puts[0]['Body'] == b'jpg' and s3.puts[0]['ContentType'] == 'image/jpeg'
    with pytest.raises(image.ImageError):
        image.make_image({}, 'x', '2026-09-27T20:00')


def test_image_slot_posts_image_and_text_slot_does_not(monkeypatch):
    monkeypatch.setattr(channel, 'IMAGE_TIMES', ('20:00',))  # 2026-10-10부터 기본은 그림 없음. 켰을 때의 동작을 본다
    d, graph = deps({'PersonaPost': [PersonaPost(text=GOOD, scene='Haru at dinner')]})
    d = post.PostDeps(d.backend, d.models, d.client, make_image=lambda scene, slot: f'https://pub/{slot}.jpg')
    post.run_post(ENV_WITH_2000, d, None, AT_2005)
    creates = [p for m, u, p in graph.calls if u.endswith('/threads')]
    assert creates[0]['media_type'] == 'IMAGE' and creates[0]['image_url'] == 'https://pub/2026-09-27T20:00.jpg'
    assert history.find(history.load_history(), '2026-09-27T20:00').image_urls == ('https://pub/2026-09-27T20:00.jpg',)


def test_image_failure_falls_back_to_text():
    def broken(scene, slot):
        raise image.ImageError('boom')
    d, graph = deps({'PersonaPost': [PersonaPost(text=GOOD, scene='Haru')]})
    d = post.PostDeps(d.backend, d.models, d.client, make_image=broken)
    assert post.run_post(ENV_WITH_2000, d, None, AT_2005).outcome == 'success'
    assert [p['media_type'] for m, u, p in graph.calls if u.endswith('/threads')] == ['TEXT']


# --- 댓글 자동 답글 ---

from src import replies  # noqa: E402
from src.replies import ReplyDraft  # noqa: E402


class ReplyClient:
    user_id = 'u1'

    def __init__(self):
        self.created, self.published = [], []

    def get(self, path, params=None):
        if path == 'u1/threads':
            return {'data': [{'id': 'p1', 'text': '월요병 밸런스 게임', 'timestamp': '2026-09-28T01:00:00+0000',
                              'is_reply': False}]}
        return {'data': [
            {'id': 'c1', 'text': '프사 귀엽네요ㅎㅎ', 'username': 'fan1', 'timestamp': '2026-09-28T02:00:00+0000'},
            {'id': 'c2', 'text': 'AI 봇이죠?', 'username': 'fan2', 'timestamp': '2026-09-28T03:00:00+0000'},
            {'id': 'c3', 'text': '내 답글', 'username': 'rabbit.haru1130', 'timestamp': '2026-09-28T03:00:00+0000',
             'is_reply_owned_by_me': True},
        ]}

    def create_text(self, text, reply_to=''):
        self.created.append((text, reply_to))
        return 'box'

    def wait_before_publish(self):
        pass

    def publish(self, box):
        self.published.append(box)
        return 'm'


def test_replies_answer_new_comments_once_and_skip_identity_questions(tmp_path):
    path = tmp_path / 'replied.json'
    now = datetime(2026, 9, 28, 5, 0, tzinfo=timezone.utc)
    llm, _ = fake_llm({'ReplyDraft': [ReplyDraft(skip=False, reply='헤헤 고마워 친구 🥕'),
                                      ReplyDraft(skip=True, reason='정체 질문')]})
    client = ReplyClient()
    r = replies.run_replies(client, llm, 'f', None, now, path)
    assert r.outcome == 'success' and client.created == [('헤헤 고마워 친구 🥕', 'c1')]
    assert set(replies.load_replied(path)['ids']) == {'c1', 'c2'} and replies.load_replied(path)['days']['2026-09-28'] == 1
    llm2, openai2 = fake_llm({})
    replies.run_replies(client, llm2, 'f', None, now, path)
    assert openai2.requests == [] and len(client.created) == 1   # 같은 댓글에 두 번 답하지 않음


def test_replies_respect_daily_limit(tmp_path):
    path = tmp_path / 'replied.json'
    replies.save_replied({'ids': [], 'days': {'2026-09-28': replies.MAX_PER_DAY}}, path)
    llm, _ = fake_llm({})
    r = replies.run_replies(ReplyClient(), llm, 'f', None, datetime(2026, 9, 28, 5, 0, tzinfo=timezone.utc), path)
    assert r.outcome == 'skipped'


def test_reply_issues_block_human_claims_and_links():
    assert replies.reply_issues('헤헤 고마워 🥕') == []
    assert replies.reply_issues('30대 여자인 나도 그래 https://x.com')


def test_balance_game_rules_and_slot_formats():
    good = '월급날 앞두고 고민 중…\nA. 월급 두 배 + 퇴근 후 연락 필수\nB. 월급 그대로 + 퇴근 뒤 잠수 가능\n친구들은?'
    assert persona.balance_issues(good) == []
    assert any('A. / B.' in i for i in persona.balance_issues('회의 10분 vs 퇴근 10분?'))
    assert any('고르지' in i for i in persona.balance_issues(good + '\n난 B'))
    assert any('예시' in i for i in persona.balance_issues('고민\nA. 연봉 30% 인상\nB. 그대로\n친구들은?'))
    monday = schedule.slot_datetime('2026-09-28T12:30')
    assert persona.pick_format(monday, '2026-09-28T12:30') in persona.SLOT_FORMATS['12:30']
    sunday = schedule.slot_datetime('2026-09-27T16:00')
    assert persona.pick_format(sunday, '2026-09-27T16:00') in persona.WEEKEND_FORMATS


# --- 2026-10-03 성과 반영: 12:30 조연 점심 장면, 20:00 "이거 나만 그래?" 저녁 장면, 16:00·23:30 공유 줄 ---

def test_lunch_and_evening_formats_end_with_question():
    for key in ('2026-10-05T12:30', '2026-10-04T12:30', '2026-10-05T20:00', '2026-10-04T20:00'):  # 월요일·일요일
        fmt, needs_question, is_balance = persona.pick_format(schedule.slot_datetime(key), key)
        assert fmt in [f[0] for f in persona.SLOT_FORMATS[key[-5:]]] and needs_question and not is_balance
    lunch = ' '.join(f[0] for f in persona.SLOT_FORMATS['12:30'])
    assert '다람쥐 동기' in lunch and '부엉이 부장' in lunch and not any(w in lunch for w in ('빈칸', '체크리스트', 'A.'))
    assert all('나만 그래' in f[0] or '질문' in f[0] for f in persona.SLOT_FORMATS['20:00'])
    assert channel.IMAGE_TIMES == ()  # 2026-10-10: 그림 글 조회수가 글만 올린 글의 1/3 이하라 끔
    assert persona.ending_issues('퇴근하고 바로 누웠어\n이거 나만 그래?') == []
    assert persona.ending_issues('이거 나만 그래?\n퇴근하고 바로 누웠어')


def test_evening_compose_retries_when_question_not_last():
    first = PersonaPost(text='다들 퇴근했어?\n난 집 오자마자 누웠어 🐰')
    good = PersonaPost(text='집 오자마자 가방 멘 채로 누웠어 🐰\n이거 나만 그래?')
    llm, client = fake_llm({'PersonaPost': [first, good]})
    draft = compose.compose(llm, MODELS, (), '2026-10-05T20:00')
    assert draft.parts == (good.text,) and not draft.rescued and len(client.requests) == 2


def test_share_line_rotates_daily_between_16_and_2330():
    days = [f'2026-10-{d:02d}' for d in range(3, 9)]
    for day in days:
        flags = [persona.wants_share_line(f'{day}T{t}') for t in persona.SHARE_SLOTS]
        assert flags.count(True) == 1  # 하루 한 번, 두 시각을 번갈아
    assert [persona.wants_share_line(f'{d}T16:00') for d in days[:4]] in ([True, False, True, False], [False, True, False, True])
    assert not any(persona.wants_share_line(f'2026-10-03T{t}') for t in ('09:00', '12:30', '20:00'))


def test_share_line_keeps_question_last_and_has_no_conditional_bait():
    key = next(f'2026-10-{d:02d}T23:30' for d in range(3, 10) if persona.wants_share_line(f'2026-10-{d:02d}T23:30'))
    out = persona.with_share_line('잠이 안 와…\n다들 아직 안 자?', key)
    lines = out.splitlines()
    assert lines[-1] == '다들 아직 안 자?' and lines[-2] in persona.SHARE_LINES
    flat = persona.with_share_line('부엉이 부장이 또 불렀어 🐰', key)
    assert flat.splitlines()[-1] in persona.SHARE_LINES
    assert all(not persona.ENGAGEMENT_BAIT.search(t) and not persona.issues(t, needs_question=False) for t in persona.SHARE_LINES)
    assert persona.strip_share_lines(out) == '잠이 안 와…\n다들 아직 안 자?'
    off = key.replace('T23:30', 'T16:00')
    assert persona.with_share_line('그냥 글', off) == '그냥 글'


def test_compose_appends_share_line_after_quality_check():
    key = next(f'2026-10-{d:02d}T16:00' for d in range(3, 10) if persona.wants_share_line(f'2026-10-{d:02d}T16:00'))
    text = '부엉이 부장이 "잠깐 얘기 좀 할까?" 하고 10분 동안 당근 얘기만 했어 🐰'
    corner = persona.corner_for(schedule.slot_datetime(key), key)
    text = f'{corner[0]}: {text}' if corner else text
    llm, _ = fake_llm({'PersonaPost': [PersonaPost(text=text)]})
    draft = compose.compose(llm, MODELS, (), key)
    assert draft.parts[0].startswith(text) and draft.parts[0].splitlines()[-1] in persona.SHARE_LINES
    assert draft.title == text[:40]


# --- 2026-10-11 반응 개선: 대사 훅, 요일 코너, 선택형 질문 ---

def test_flat_opening_is_rejected_but_dialogue_opening_passes():
    assert persona.opening_issues('오후 4시에 산책 나가려다 말았어')
    assert persona.opening_issues('목요일 아침, 현관문 앞에서 한참 서 있었어') 
    assert persona.opening_issues('다람쥐 동기가 "수요일이면 반은 끝난 거지?" 했어') == []
    assert persona.opening_issues('월요일 아침이라니') and persona.opening_issues('밤 11시 반인데 안 자')


def test_weekday_16_has_corner_and_weekend_does_not():
    names = {persona.corner_for(schedule.slot_datetime(f'2026-10-{d:02d}T16:00'), f'2026-10-{d:02d}T16:00')[0] for d in range(12, 17)}
    assert len(names) == 4  # 2026-10-30부터 엄마 토끼가 화·목 두 번
    assert '부엉이 부장 어록' not in names
    assert persona.corner_for(schedule.slot_datetime('2026-10-10T16:00'), '2026-10-10T16:00') is None  # 토요일
    assert persona.corner_for(schedule.slot_datetime('2026-10-05T12:30'), '2026-10-05T12:30') is None


def test_corner_post_must_start_with_corner_name():
    key = '2026-10-13T16:00'  # 화요일 → 엄마 토끼 전화 어록
    bad = PersonaPost(text='엄마 토끼가 "좋은 토끼 없니?" 했어 🐰')
    good = PersonaPost(text='엄마 토끼 전화 어록: "좋은 토끼 없니?" → 번역: 김장 도와줄 토끼 구함 🐰')
    llm, client = fake_llm({'PersonaPost': [bad, good]})
    draft = compose.compose(llm, MODELS, (), key)
    assert draft.parts[0].startswith('엄마 토끼 전화 어록') and not draft.rescued and len(client.requests) == 2
    assert '엄마 토끼 전화 어록' in client.requests[0]['input']


def test_lunch_requires_choice_question():
    assert persona.choice_issues('다람쥐 동기가 간식을 줬어\n너라면 ① 먹는다 ② 아낀다?') == []
    assert persona.choice_issues('다람쥐 동기가 간식을 줬어\n다들 어떻게 해?')
    flat = PersonaPost(text='다람쥐 동기가 간식을 줬어 🥕\n다들 어떻게 해?')
    good = PersonaPost(text='다람쥐 동기가 간식을 줬어 🥕\n너라면 ① 먹는다 ② 아낀다?')
    llm, client = fake_llm({'PersonaPost': [flat, good]})
    draft = compose.compose(llm, MODELS, (), '2026-10-05T12:30')
    assert draft.parts == (good.text,) and len(client.requests) == 2


def test_outreach_inbox_parsing_and_drafts(tmp_path):
    from src import outreach
    inbox = tmp_path / 'inbox.md'
    inbox.write_text('# 제목\n> 안내\n\n---\n월요일 출근길 최악\n---\n퇴사하고 싶다\n---\n', encoding='utf-8')
    assert outreach.read_inbox(inbox) == ['월요일 출근길 최악', '퇴사하고 싶다']
    assert outreach.read_inbox(tmp_path / 'none.md') == []
    drafts = outreach.CommentDrafts(skip=False, comments=['월요일 출근은 토끼도 귀가 처져 🐰', '30대 여자인 나도 그래', 'https://x.com 놀러 와', 'ㅋ'])
    assert outreach.usable(drafts.comments) == ['월요일 출근은 토끼도 귀가 처져 🐰']
    llm, _ = fake_llm({'CommentDrafts': [drafts, outreach.CommentDrafts(skip=True)]})
    out = tmp_path / 'out.md'
    result = outreach.run_outreach(llm, 'm', inbox, out)
    assert result.outcome == 'success' and '- 월요일 출근은 토끼도 귀가 처져' in out.read_text(encoding='utf-8')
    assert '댓글을 달지 않는' in out.read_text(encoding='utf-8')
    assert outreach.run_outreach(llm, 'm', tmp_path / 'empty.md', out).outcome == 'skipped'
