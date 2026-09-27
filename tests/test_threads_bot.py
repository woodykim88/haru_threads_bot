import pytest

from scripts import due_check
from src import channel, commands, compose, history, notifier, persona, post, schedule, state, threads, token_refresh
from src.persona import PersonaPost
from src.threads import ThreadsClient, ThreadsConfig, ThreadsError
from tests.helpers import AT_1235, Resp, fake_llm

MODELS = compose.Models('w', 'f')
GOOD = '점심 당근 두 개 먹고 또 졸려… 이거 식곤증 맞지? 🥕'
SLOT = '2026-09-27T12:30'


# --- 채널 설정 ---

def test_channel_config_has_five_slots_and_prefix():
    assert len(channel.MOODS) == 5 and schedule.parse_times(channel.DEFAULT_TIMES) == schedule.parse_times(None)
    assert notifier.PREFIX == '[Threads 하루] ' and '/haru_stop' in commands.COMMANDS


# --- 캐릭터 글 검수 ---

def test_persona_issues_block_links_ads_and_human_claims():
    assert persona.issues(GOOD, needs_question=True) == []
    assert persona.issues('오늘 굴에서 뒹굴뒹굴 🐰', needs_question=False) == []
    assert any('질문' in i for i in persona.issues('오늘 굴에서 뒹굴뒹굴 🐰', needs_question=True))
    assert any('사람' in i for i in persona.issues('20대 여자인 나도 출근길엔 졸려?', needs_question=True))
    assert any('광고' in i for i in persona.issues('이 당근 할인 링크 https://x.com #당근', needs_question=False))
    assert all(not persona.issues(t, needs_question=False) for t in persona.FALLBACKS)


def test_compose_uses_slot_mood_and_recent_posts():
    llm, client = fake_llm({'PersonaPost': [PersonaPost(text=GOOD)] * 2})
    past = (history.HistoryEntry('2026-09-27T09:00', 'PUBLISHED', seed=persona.KIND, caption='이불 밖은 위험해'),)
    draft = compose.compose(llm, MODELS, past, SLOT)
    assert draft.parts == (GOOD,) and draft.key == f'persona:{SLOT}' and not draft.rescued
    sent = client.requests[0]['input']
    assert channel.MOODS['12:30'] in sent and '이불 밖은 위험해' in sent


def test_compose_falls_back_to_prepared_post():
    bad = PersonaPost(text='남친이랑 출근길 https://x.com')
    llm, _ = fake_llm({'PersonaPost': [bad, bad]})
    draft = compose.compose(llm, MODELS, (), SLOT)
    assert draft.rescued and draft.parts[0] in persona.FALLBACKS


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
    bad = PersonaPost(text='남친이랑 출근길')
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


def test_image_slot_posts_image_and_text_slot_does_not():
    d, graph = deps({'PersonaPost': [PersonaPost(text=GOOD, scene='Haru at dinner')]})
    d = post.PostDeps(d.backend, d.models, d.client, make_image=lambda scene, slot: f'https://pub/{slot}.jpg')
    post.run_post(ENV, d, None, AT_2005)
    creates = [p for m, u, p in graph.calls if u.endswith('/threads')]
    assert creates[0]['media_type'] == 'IMAGE' and creates[0]['image_url'] == 'https://pub/2026-09-27T20:00.jpg'
    assert history.find(history.load_history(), '2026-09-27T20:00').image_urls == ('https://pub/2026-09-27T20:00.jpg',)


def test_image_failure_falls_back_to_text():
    def broken(scene, slot):
        raise image.ImageError('boom')
    d, graph = deps({'PersonaPost': [PersonaPost(text=GOOD, scene='Haru')]})
    d = post.PostDeps(d.backend, d.models, d.client, make_image=broken)
    assert post.run_post(ENV, d, None, AT_2005).outcome == 'success'
    assert [p['media_type'] for m, u, p in graph.calls if u.endswith('/threads')] == ['TEXT']
