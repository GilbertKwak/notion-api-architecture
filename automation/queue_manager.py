# ============================================================
# queue_manager.py
# Automation Queue 엔진
# 우선순위·재시도·감사 로그·의존성 그래프
# ============================================================

from __future__ import annotations
import heapq, time, json, uuid, logging, threading
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Callable, Any

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    CRITICAL = 0   # 즉시 (배너 갱신, 오류 복구)
    HIGH     = 1   # 높음 (세션 종료 sync)
    NORMAL   = 2   # 보통 (일일 KG 테이블)
    LOW      = 3   # 낮음 (링크, 정적 섹션)


@dataclass(order=True)
class QueueItem:
    priority:    int                           # Priority enum 값
    enqueued_at: float = field(compare=False)  # 입력 시각 (FIFO 동점 처리)
    item_id:     str   = field(compare=False)
    section_id:  str   = field(compare=False)
    page_id:     str   = field(compare=False)
    content:     str   = field(compare=False)
    depends_on:  list[str] = field(compare=False, default_factory=list)
    max_retries: int   = field(compare=False, default=3)
    retry_count: int   = field(compare=False, default=0)
    status:      str   = field(compare=False, default='pending')
    result:      dict  = field(compare=False, default_factory=dict)

    @property
    def priority_label(self) -> str:
        return Priority(self.priority).name


@dataclass
class AuditEntry:
    item_id:    str
    section_id: str
    page_id:    str
    status:     str
    duration_s: float
    attempt:    int
    error:      str = ''
    timestamp:  float = field(default_factory=time.time)


class AutomationQueue:
    """
    우선순위 큐 기반 Automation 실행 엔진.

    기능:
      - 우선순위 스케줄링 (CRITICAL→HIGH→NORMAL→LOW)
      - 의존성 그래프 (depends_on 해결 후 실행)
      - 자동 재시도 (지수 백오프)
      - 감사 로그 (전체 실행 추적)
      - 스레드 안전 (threading.Lock)
    """

    def __init__(self, executor: Callable[[QueueItem], dict]) -> None:
        self._heap: list[tuple] = []    # (priority, enqueued_at, QueueItem)
        self._executor = executor
        self._audit: list[AuditEntry] = []
        self._completed: set[str] = set()
        self._lock = threading.Lock()

    # ── 큐 조작 ─────────────────────────────────────────────

    def enqueue(self, section_id: str, page_id: str, content: str,
                priority: Priority = Priority.NORMAL,
                depends_on: list[str] | None = None,
                max_retries: int = 3) -> str:
        item = QueueItem(
            priority=int(priority),
            enqueued_at=time.time(),
            item_id=str(uuid.uuid4())[:8],
            section_id=section_id,
            page_id=page_id,
            content=content,
            depends_on=depends_on or [],
            max_retries=max_retries,
        )
        with self._lock:
            heapq.heappush(self._heap, (item.priority, item.enqueued_at, item))
        logger.debug('[Queue] enqueue section=%s priority=%s id=%s',
                     section_id, item.priority_label, item.item_id)
        return item.item_id

    def run_all(self) -> list[AuditEntry]:
        """큐 전체 소진 — 의존성·재시도 포함"""
        while self._heap:
            with self._lock:
                if not self._heap:
                    break
                _, _, item = heapq.heappop(self._heap)

            # 의존성 미해결 → 재큐잉
            if not self._deps_resolved(item):
                logger.debug('[Queue] 의존성 대기: %s → %s',
                             item.section_id, item.depends_on)
                time.sleep(0.5)
                with self._lock:
                    heapq.heappush(self._heap,
                                   (item.priority, item.enqueued_at, item))
                continue

            self._execute_item(item)
        return self._audit

    # ── 실행 ────────────────────────────────────────────────

    def _execute_item(self, item: QueueItem) -> None:
        start = time.time()
        attempt = item.retry_count + 1
        try:
            result = self._executor(item)
            duration = time.time() - start
            item.status = 'success'
            item.result = result
            self._completed.add(item.item_id)
            self._audit.append(AuditEntry(
                item_id=item.item_id,
                section_id=item.section_id,
                page_id=item.page_id,
                status='success',
                duration_s=round(duration, 3),
                attempt=attempt,
            ))
            logger.info('[Queue] ✅ %s 완료 (%.2fs, attempt=%d)',
                        item.section_id, duration, attempt)
        except Exception as e:
            duration = time.time() - start
            item.retry_count += 1
            if item.retry_count < item.max_retries:
                delay = 2 ** item.retry_count   # 지수 백오프
                logger.warning('[Queue] ⚠️ %s 실패 → %ds 후 재시도 (attempt=%d)',
                               item.section_id, delay, attempt)
                time.sleep(delay)
                with self._lock:
                    heapq.heappush(self._heap,
                                   (item.priority, item.enqueued_at, item))
            else:
                item.status = 'failed'
                self._audit.append(AuditEntry(
                    item_id=item.item_id,
                    section_id=item.section_id,
                    page_id=item.page_id,
                    status='failed',
                    duration_s=round(duration, 3),
                    attempt=attempt,
                    error=str(e),
                ))
                logger.error('[Queue] ❌ %s 최종 실패: %s', item.section_id, e)

    def _deps_resolved(self, item: QueueItem) -> bool:
        return all(dep in self._completed for dep in item.depends_on)

    # ── 보고 ────────────────────────────────────────────────

    def report(self) -> dict:
        total = len(self._audit)
        success = sum(1 for a in self._audit if a.status == 'success')
        failed  = total - success
        avg_dur = (sum(a.duration_s for a in self._audit) / total
                   if total else 0)
        return {
            'total': total, 'success': success, 'failed': failed,
            'success_rate': f'{success/total*100:.1f}%' if total else 'N/A',
            'avg_duration_s': round(avg_dur, 3),
            'audit': [asdict(a) for a in self._audit],
        }

    def export_audit(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.report(), f, ensure_ascii=False, indent=2)
        logger.info('[Queue] 감사 로그 저장: %s', path)
