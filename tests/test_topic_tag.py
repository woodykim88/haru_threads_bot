"""첫 글 토픽 태그 (2026-10-10): 첫 글에만 붙이고, 태그 때문에 거절되면 태그 없이 다시 만든다."""
from src import threads
from src.threads import ThreadsClient, ThreadsConfig


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def make(reject_tag=False):
    calls = []

    def request(method, url, params):
        calls.append(dict(params))
        if reject_tag and 'topic_tag' in params:
            return Resp(400, {'error': {'message': 'Invalid parameter', 'code': 100}})
        return Resp(200, {'id': 'box'})

    return ThreadsClient(ThreadsConfig('u1', 'secret'), request=request, sleep=lambda s: None), calls


def test_first_post_gets_topic_tag_and_reply_does_not(monkeypatch):
    monkeypatch.setattr(threads, '_topic_tag', lambda: '자취')
    client, calls = make()
    assert client.create_text('첫 글') == 'box' and client.create_text('답글', reply_to='m1') == 'box'
    assert calls[0]['topic_tag'] == '자취' and 'topic_tag' not in calls[1]


def test_rejected_topic_tag_falls_back_to_plain_post(monkeypatch):
    monkeypatch.setattr(threads, '_topic_tag', lambda: '자취')
    client, calls = make(reject_tag=True)
    assert client.create_text('첫 글') == 'box'
    assert 'topic_tag' in calls[0] and 'topic_tag' not in calls[1] and len(calls) == 2


def test_channel_topic_tag_is_valid():
    tag = threads._topic_tag()
    assert 1 <= len(tag) <= 50 and '.' not in tag and '&' not in tag
