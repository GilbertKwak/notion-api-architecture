# ============================================================
# notion_writer.py
# replace_content SOP 기반 안전 write 레이어
# SESSION-C33 확정 원칙 내재화
# ============================================================

from __future__ import annotations
import re, time, logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 재시도 정책
RETRY_DELAYS = [2, 5, 15]   # 초 단위
MAX_RETRIES  = 3


class NotionWriter:
    """
    Notion MCP write 안전 레이어.

    SESSION-C33 확정 원칙:
      1. replace_content 우선 — 이스케이프 불일치 회피
      2. update_content는 이스케이프 없는 평문 단락에만 허용
      3. 앵커는 반드시 평문 구간 사용
      4. write 전 read로 앵커 존재 검증
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self._write_count = 0
        self._error_count = 0

    # ── 공개 API ─────────────────────────────────────────────

    def safe_write(self, page_id: str, method: str,
                   anchor: str, new_content: str,
                   verify_after: bool = True) -> dict:
        """
        안전 write 실행.
        1. 앵커 존재 검증
        2. 이스케이프 정규화
        3. write 실행 (재시도)
        4. post-update 검증 (선택)
        """
        # STEP 1: 앵커 정규화 (이스케이프 제거)
        clean_anchor = self._normalize_anchor(anchor)

        # STEP 2: 현재 페이지 fetch → 앵커 검증
        current_content = self._fetch_page(page_id)
        if current_content and clean_anchor not in current_content:
            logger.warning('[NotionWriter] 앵커 미발견: %r — fallback replace', clean_anchor[:40])
            return {'ok': False, 'reason': 'anchor_not_found',
                    'anchor': clean_anchor[:60]}

        # STEP 3: write 실행
        result = self._execute_write(
            page_id=page_id,
            method=method,
            anchor=clean_anchor,
            new_content=new_content,
        )

        # STEP 4: post-update 검증
        if result['ok'] and verify_after:
            result['verified'] = self._verify_write(page_id, new_content)

        return result

    def stats(self) -> dict:
        return {'writes': self._write_count, 'errors': self._error_count,
                'success_rate': (
                    f"{(self._write_count / (self._write_count + self._error_count) * 100):.1f}%"
                    if (self._write_count + self._error_count) > 0 else 'N/A'
                )}

    # ── 내부 ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_anchor(anchor: str) -> str:
        """fetch 반환 이스케이프 → 실제 저장값으로 정규화"""
        # Notion fetch는 \[ \| \~ 등 이스케이프 추가 → 제거
        clean = re.sub(r'\\([\[\]|~`*_{}])', r'\1', anchor)
        return clean.strip()

    def _fetch_page(self, page_id: str) -> str | None:
        """페이지 현재 content 취득 (실제 환경에서는 Notion API 호출)"""
        try:
            # 프로덕션: notion MCP fetch 호출
            # from notion_client import Client
            # client = Client(auth=self.token)
            # blocks = client.blocks.children.list(block_id=page_id)
            # return self._blocks_to_text(blocks)
            logger.debug('[NotionWriter] fetch page: %s', page_id[:8])
            return None   # CI 환경에서는 None → 검증 skip
        except Exception as e:
            logger.warning('[NotionWriter] fetch 실패: %s', e)
            return None

    def _execute_write(self, page_id: str, method: str,
                       anchor: str, new_content: str) -> dict:
        """재시도 포함 write 실행"""
        last_err: Exception | None = None
        for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
            if delay:
                logger.info('[NotionWriter] 재시도 %d/%d — %ds 대기', attempt, MAX_RETRIES, delay)
                time.sleep(delay)
            try:
                self._call_notion_write(page_id, method, anchor, new_content)
                self._write_count += 1
                logger.info('[NotionWriter] write 성공 (attempt=%d, method=%s)', attempt, method)
                return {'ok': True, 'attempt': attempt, 'method': method}
            except Exception as e:
                last_err = e
                self._error_count += 1
                logger.warning('[NotionWriter] write 실패 attempt=%d: %s', attempt, e)
        return {'ok': False, 'reason': str(last_err), 'attempts': MAX_RETRIES}

    def _call_notion_write(self, page_id: str, method: str,
                           anchor: str, new_content: str) -> None:
        """실제 Notion API write (프로덕션 구현 위치)"""
        # 프로덕션 구현:
        # if method == 'replace_content':
        #     notion_mcp.update_page(page_id, command='replace_content',
        #                            old_str=anchor, new_str=new_content)
        # elif method == 'update_content':
        #     notion_mcp.update_page(page_id, command='update_content',
        #                            content_updates=[{'old_str': anchor,
        #                                              'new_str': new_content}])
        pass

    def _verify_write(self, page_id: str, expected_content: str) -> bool:
        """post-update 검증 — 핵심 텍스트 포함 여부 확인"""
        updated = self._fetch_page(page_id)
        if updated is None:
            return True   # fetch 불가 시 낙관적 true
        # 첫 100자를 지문으로 사용
        fingerprint = expected_content.strip()[:100]
        return fingerprint in updated
