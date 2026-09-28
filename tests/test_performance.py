from datetime import datetime, timezone

from src import performance

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    user_id = 'u1'

    def __init__(self, posts, views):
        self.posts, self.views = posts, views

    def get(self, path, params=None):
        if path == 'u1/threads':
            return {'data': self.posts}
        pid = path.split('/')[0]
        return {'data': [{'name': 'views', 'values': [{'value': self.views[pid]}]},
                         {'name': 'likes', 'values': [{'value': 1}]}]}


def test_fetch_stats_skips_replies_and_old_posts():
    posts = [{'id': 'a', 'text': '새 글', 'timestamp': '2026-09-27T10:00:00+0000', 'is_reply': False},
             {'id': 'b', 'text': '답글', 'timestamp': '2026-09-27T10:00:00+0000', 'is_reply': True},
             {'id': 'c', 'text': '옛 글', 'timestamp': '2026-06-28T10:00:00+0000', 'is_reply': False}]
    stats = performance.fetch_stats(FakeClient(posts, {'a': 50}), NOW)
    assert [(s['id'], s['views'], s['likes']) for s in stats] == [('a', 50, 1)]


def test_build_brief_lists_top_and_bottom():
    stats = [{'text': f'글{i}', 'views': i * 10, 'likes': 0, 'replies': 0} for i in range(6)]
    brief = performance.build_brief(stats, '2026-09-28')
    assert '조회 50회' in brief.split('반응이 적었던')[0] and '조회 0회' in brief.split('반응이 적었던')[1]
    assert performance.build_brief(stats[:3], '2026-09-28') == ''
