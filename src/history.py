"""슬롯별 발행 이력(data/history.json). 중복 주제 방지와 중복 게시 방지(멱등성)에 쓴다.

한 슬롯("2026-09-27T20:00")에 항목은 하나뿐이고, 상태가 PREPARED → PUBLISHED(또는 SKIPPED/FAILED)로 바뀐다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent.parent / 'data' / 'history.json'

PREPARED = 'PREPARED'
PUBLISHED = 'PUBLISHED'
SKIPPED = 'SKIPPED'
FAILED = 'FAILED'
FINAL_STATUSES = (PUBLISHED, SKIPPED)


@dataclass(frozen=True)
class HistoryEntry:
    slot: str
    status: str
    title: str = ''
    seed: str = ''
    theme: str = ''
    doc_id: str = ''
    source_url: str = ''
    image_urls: tuple[str, ...] = ()
    caption: str = ''
    media_id: str = ''
    permalink: str = ''
    note: str = ''
    updated_at: str = ''


def load_history(path: Path | None = None) -> tuple[HistoryEntry, ...]:
    path = path or DEFAULT_HISTORY_PATH
    if not path.exists():
        return ()
    rows = json.loads(path.read_text(encoding='utf-8'))
    return tuple(HistoryEntry(**{**row, 'image_urls': tuple(row.get('image_urls', ()))}) for row in rows)


def save_history(history: tuple[HistoryEntry, ...], path: Path | None = None) -> None:
    path = path or DEFAULT_HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{**asdict(e), 'image_urls': list(e.image_urls)} for e in history]
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def upsert(history: tuple[HistoryEntry, ...], entry: HistoryEntry) -> tuple[HistoryEntry, ...]:
    """같은 슬롯이 있으면 교체하고, 없으면 뒤에 붙인 새 튜플을 반환합니다."""
    if any(e.slot == entry.slot for e in history):
        return tuple(entry if e.slot == entry.slot else e for e in history)
    return (*history, entry)


def find(history: tuple[HistoryEntry, ...], slot: str) -> HistoryEntry | None:
    return next((e for e in history if e.slot == slot), None)


def with_status(entry: HistoryEntry, status: str, **changes: str) -> HistoryEntry:
    return replace(entry, status=status, **changes)


def prepared_slots(history: tuple[HistoryEntry, ...]) -> set[str]:
    """이미 준비했거나 끝난 슬롯 (다시 만들지 않음)."""
    return {e.slot for e in history if e.status in (PREPARED, *FINAL_STATUSES)}


def recent_titled(history: tuple[HistoryEntry, ...], limit: int = 30) -> tuple[HistoryEntry, ...]:
    """주제 중복 비교용: 제목이 있는 최근 항목."""
    return tuple(e for e in history if e.title)[-limit:]


def consecutive_failures(history: tuple[HistoryEntry, ...]) -> int:
    """가장 최근부터 거슬러 올라가며 연속으로 게시에 실패한 슬롯 수."""
    count = 0
    for e in sorted(history, key=lambda e: e.slot, reverse=True):
        if e.status == FAILED:
            count += 1
        elif e.status in FINAL_STATUSES:
            break
    return count
