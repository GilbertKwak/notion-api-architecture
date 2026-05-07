# ============================================================
# metadata_manager.py
# Phase 2~4 공통 패턴 — 섹션 메타데이터 관리
# ============================================================

from __future__ import annotations
import os, time, json, hashlib, concurrent.futures, logging
from dataclasses import dataclass, field, asdict
from typing import Any
from automation.notion_writer import NotionWriter

logger = logging.getLogger(__name__)


@dataclass
class SectionMeta:
    section_id: str          # 섹션 식별자 (예: 'banner', 'kg_table')
    label: str               # 사람이 읽는 이름
    anchor_start: str        # replace_content 앵커 (평문)
    anchor_end: str | None   # 섹션 끝 앵커 (None이면 다음 H2까지)
    method: str              # 'replace_content' | 'update_content'
    last_hash: str = ''      # 직전 content SHA256
    last_updated: float = 0.0
    write_count: int = 0
    error_count: int = 0
    tags: list[str] = field(default_factory=list)

    def content_changed(self, new_content: str) -> bool:
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()
        return new_hash != self.last_hash

    def record_success(self, content: str) -> None:
        self.last_hash = hashlib.sha256(content.encode()).hexdigest()
        self.last_updated = time.time()
        self.write_count += 1

    def record_error(self) -> None:
        self.error_count += 1


class MetadataManager:
    """
    T-09 Mother Page 기준 8개 섹션 메타데이터 초기화·관리.
    Phase 2~4 공통 패턴의 핵심 레이어.
    """

    # ── 기본 섹션 정의 (T-09 8섹션)
    DEFAULT_SECTIONS: list[dict] = [
        dict(section_id='banner',    label='갱신 배너',     method='replace_content',
             anchor_start='---\n# 📌',                  anchor_end='---\n# ',
             tags=['top', 'always_replace']),
        dict(section_id='overview',  label='라이브러리 개요', method='replace_content',
             anchor_start='# 📌 라이브러리 개요',          anchor_end='---\n# ',
             tags=['static']),
        dict(section_id='kg_table',  label='KG 현황 테이블', method='replace_content',
             anchor_start='## 📊 Knowledge Graph 현황',  anchor_end='---\n# ',
             tags=['table', 'daily']),
        dict(section_id='ew_table',  label='EW 트리거 테이블', method='replace_content',
             anchor_start='## ⚡ EW 트리거',              anchor_end='---\n# ',
             tags=['table', 'daily']),
        dict(section_id='session',   label='세션 히스토리',  method='replace_content',
             anchor_start='## 📝 세션 히스토리',           anchor_end='---\n# ',
             tags=['table', 'per_session']),
        dict(section_id='sop',       label='SOP 기준',      method='update_content',
             anchor_start='## 🔧 SOP',                   anchor_end='---\n# ',
             tags=['static', 'plain_text_only']),
        dict(section_id='actions',   label='후속 액션',     method='replace_content',
             anchor_start='## 🔴 후속 액션',               anchor_end='---\n# ',
             tags=['table', 'per_session']),
        dict(section_id='links',     label='관련 링크',     method='update_content',
             anchor_start='## 🔗 관련 링크',               anchor_end=None,
             tags=['static', 'plain_text_only']),
    ]

    def __init__(self, page_id: str, token: str, page_label: str = '') -> None:
        self.page_id = page_id
        self.page_label = page_label
        self.writer = NotionWriter(token)
        self._sections: dict[str, SectionMeta] = {}
        self._state_path = f'.metadata/{page_id[:8]}_meta.json'

    # ── 공개 API ────────────────────────────────────────────

    def initialize(self) -> dict[str, SectionMeta]:
        """섹션 메타데이터 초기화 (캐시 있으면 로드, 없으면 생성)"""
        self._load_state()
        for defn in self.DEFAULT_SECTIONS:
            sid = defn['section_id']
            if sid not in self._sections:
                self._sections[sid] = SectionMeta(**{k: defn[k] for k in SectionMeta.__dataclass_fields__
                                                      if k in defn})
        logger.info('[MetadataManager] %s: %d 섹션 초기화 완료', self.page_label, len(self._sections))
        self._save_state()
        return self._sections

    def update_section(self, section_id: str, new_content: str,
                       force: bool = False) -> dict:
        """단일 섹션 업데이트 (변경 감지 → 안전 write)"""
        meta = self._sections.get(section_id)
        if not meta:
            return {'ok': False, 'reason': f'unknown section: {section_id}'}

        if not force and not meta.content_changed(new_content):
            logger.debug('[%s] 변경 없음, skip', section_id)
            return {'ok': True, 'skipped': True, 'reason': 'no_change'}

        result = self.writer.safe_write(
            page_id=self.page_id,
            method=meta.method,
            anchor=meta.anchor_start,
            new_content=new_content,
        )
        if result['ok']:
            meta.record_success(new_content)
        else:
            meta.record_error()
        self._save_state()
        return result

    def get_section(self, section_id: str) -> SectionMeta | None:
        return self._sections.get(section_id)

    def summary(self) -> dict:
        return {
            'page_id': self.page_id,
            'page_label': self.page_label,
            'sections': {k: asdict(v) for k, v in self._sections.items()},
        }

    # ── 내부 ────────────────────────────────────────────────

    def _load_state(self) -> None:
        if os.path.exists(self._state_path):
            with open(self._state_path) as f:
                data = json.load(f)
            self._sections = {k: SectionMeta(**v) for k, v in data.items()}
            logger.debug('[MetadataManager] 캐시 로드: %s', self._state_path)

    def _save_state(self) -> None:
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        with open(self._state_path, 'w') as f:
            json.dump({k: asdict(v) for k, v in self._sections.items()}, f,
                      ensure_ascii=False, indent=2)


# ── 공개 함수 (Phase 2~4 공통 패턴 진입점) ──────────────────

def initialize_section_metadata(page_id: str, token: str,
                                page_label: str = '') -> MetadataManager:
    mgr = MetadataManager(page_id, token, page_label)
    mgr.initialize()
    return mgr


def update_section_by_metadata(mgr: MetadataManager, section_id: str,
                               new_content: str, force: bool = False) -> dict:
    return mgr.update_section(section_id, new_content, force)


def validate_metadata_integrity(mgr: MetadataManager) -> dict:
    """메타데이터 무결성 검증"""
    issues = []
    for sid, meta in mgr._sections.items():
        if meta.error_count > 3:
            issues.append({'section': sid, 'issue': 'high_error_count',
                           'count': meta.error_count})
        if meta.method == 'update_content' and 'plain_text_only' not in meta.tags:
            issues.append({'section': sid, 'issue': 'update_content_without_plain_text_tag'})
    return {'ok': len(issues) == 0, 'issues': issues}


def error_predictor(page_id: str, proposed_updates: dict,
                    token: str) -> dict[str, Any]:
    """
    사전 검증 — write 실행 전 위험도 예측.
    Returns: {'safe_to_proceed': bool, 'risk_level': str, 'warnings': list}
    """
    from automation.error_predictor import ErrorPredictor
    return ErrorPredictor(token).predict(page_id, proposed_updates)


def parallel_section_update(page_id: str, proposed_updates: dict,
                            token: str,
                            max_workers: int = 3) -> dict:
    """
    병렬 섹션 업데이트.
    proposed_updates: {section_id: new_content}
    """
    mgr = initialize_section_metadata(page_id, token)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(mgr.update_section, sid, content): sid
            for sid, content in proposed_updates.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            sid = futures[fut]
            try:
                results[sid] = fut.result()
            except Exception as e:
                results[sid] = {'ok': False, 'error': str(e)}
    return results
