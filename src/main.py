"""Threads @rabbit.haru1130 (토끼 캐릭터 하루) 자동 게시 진입점.

작업(--job):
    post           슬롯 시각이 되면 캐릭터 글을 만들어 바로 게시 (하루 5번)
    preview        게시하지 않고 글만 만들어 output/preview.txt에 저장 (--slot 으로 시간대 지정, 여러 개 가능)
    refresh-token  Threads 장기 토큰 갱신 (주 1회)
    post-pending   미리 보여 준 글(data/pending.json)을 그대로 게시 (--save-pending으로 만든 것)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src import channel, compose, history, image, notifier, post, providers, runlog, schedule, token_refresh, usage
from src.guard import RunResult
from src.llm import LLMClient, LLMError
from src.threads import ThreadsClient, ThreadsConfigError, ThreadsError, load_threads_config

ROOT = Path(__file__).resolve().parent.parent
JOBS = ('post', 'preview', 'refresh-token', 'post-pending')
PREVIEW_PATH = ROOT / 'output' / 'preview.txt'
KNOWN_ERRORS = (providers.ProviderConfigError, ThreadsConfigError, ThreadsError, schedule.ScheduleError,
                compose.PipelineError, LLMError)


def run_preview(env: Mapping[str, str], ai: providers.AISettings, slots: Sequence[str], pending_slot: str) -> RunResult:
    """slots: 'HH:MM' 목록 (비우면 오늘의 모든 시간대). 오늘 날짜로 글을 만든다."""
    llm = LLMClient(providers.build_text_backend(ai.text_provider, env))
    today = datetime.now(schedule.KST).strftime('%Y-%m-%d')
    models = compose.Models(ai.writer_model, ai.fast_model)
    past, texts = history.load_history(), []
    for hhmm in slots or list(channel.MOODS):
        draft = compose.compose(llm, models, past, f'{today}T{hhmm}')
        texts.append(f'[{hhmm}]{" (준비된 글)" if draft.rescued else ""}\n{draft.text}')
        past = (*past, history.HistoryEntry(f'{today}T{hhmm}', 'PREVIEW', seed=draft.kind, caption=draft.text))
        if pending_slot:
            post.save_pending(draft, pending_slot)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_text('\n\n'.join(texts), encoding='utf-8')
    print('[미리보기]\n' + '\n\n'.join(texts))
    return RunResult('success', f'미리보기 {len(texts)}개', llm_calls=llm.calls)


def run_job(job: str, env: Mapping[str, str], ai: providers.AISettings | None,
            telegram: notifier.TelegramConfig | None, slots: Sequence[str] = (), pending_slot: str = '') -> RunResult:
    if job == 'preview':
        return run_preview(env, ai, slots, pending_slot)
    if job == 'refresh-token':
        return token_refresh.run_refresh(env, telegram)
    if job == 'post-pending':
        return post.run_pending(ThreadsClient(load_threads_config(env)), telegram, datetime.now(timezone.utc))
    deps = post.PostDeps(
        backend=providers.build_text_backend(ai.text_provider, env),
        models=compose.Models(ai.writer_model, ai.fast_model),
        client=ThreadsClient(load_threads_config(env)),
        make_image=lambda scene, slot: image.make_image(env, scene, slot),
    )
    return post.run_post(env, deps, telegram, datetime.now(timezone.utc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Threads @{channel.HANDLE} 자동 게시')
    parser.add_argument('--job', choices=JOBS, default='preview')
    parser.add_argument('--slot', action='append', default=[], help='preview: 시간대 HH:MM (여러 번 가능)')
    parser.add_argument('--save-pending', default='', help='preview: 이 슬롯 키로 data/pending.json에 저장')
    args = parser.parse_args(argv)

    load_dotenv(ROOT / '.env')
    env = os.environ
    telegram = notifier.load_telegram_config(env)
    started = datetime.now(schedule.KST)
    ai: providers.AISettings | None = None
    try:
        if args.job in ('post', 'preview'):
            ai = providers.load_ai_settings(env)
        result = run_job(args.job, env, ai, telegram, args.slot, args.save_pending)
    except KNOWN_ERRORS as e:
        result = RunResult('failed', str(e))
    except Exception as e:  # noqa: BLE001 - 무인 실행이므로 예상 못한 오류도 로그를 남기고 반드시 알린다
        traceback.print_exc()
        result = RunResult('failed', f'예상하지 못한 오류 {e.__class__.__name__}: {e}')

    print(f'[결과] {result.outcome}: {result.message}')
    if result.outcome == 'failed' and args.job != 'preview':
        notifier.notify(telegram, f'❌ {args.job} 작업 실패\n원인: {result.message}')
    if env.get('GITHUB_ACTIONS') == 'true':
        runlog.append_run(runlog.RunRecord(
            usage=usage.snapshot(),
            started_at=started.isoformat(timespec='seconds'),
            finished_at=datetime.now(schedule.KST).isoformat(timespec='seconds'),
            mode=args.job, outcome=result.outcome, message=result.message,
            text_provider=ai.text_provider if ai else '', writer_model=ai.writer_model if ai else '',
            llm_calls=result.llm_calls, posts=result.posts, **runlog.github_context(env),
        ))
    return 1 if result.outcome == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
