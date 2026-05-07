# ============================================================
# error_predictor.py
# 사전 검증·오류 예측 엔진
# write 실행 전 위험도 평가 → safe_to_proceed 판단
# ============================================================

from __future__ import annotations
import re, logging
from typing import Any

logger = logging.getLogger(__name__)

# 위험 패턴 — update_content 사용 불가 구간
DANGER_PATTERNS = [
    (re.compile(r'\\[\[\]|~]'),         'escape_mismatch',    'CRITICAL'),
    (re.compile(r'^\|.*\|', re.M),      'table_row',          'HIGH'),
    (re.compile(r'^>.+', re.M),         'callout_blockquote', 'HIGH'),
    (re.compile(r'\*\*.*?\*\*'),        'bold_inline',        'MEDIUM'),
    (re.compile(r'`[^`]+`'),            'inline_code',        'MEDIUM'),
    (re.compile(r'\[.+?\]\(.+?\)'),    'link',               'MEDIUM'),
]


class ErrorPredictor:
    """
    write 실행 전 위험도 예측기.

    판정 기준:
      CRITICAL → safe_to_proceed = False
      HIGH (2+) → safe_to_proceed = False
      MEDIUM    → 경고만 (진행 허용)
    """

    def __init__(self, token: str) -> None:
        self.token = token

    def predict(self, page_id: str,
                proposed_updates: dict[str, str]) -> dict[str, Any]:
        """
        proposed_updates: {section_id: new_content}
        Returns: {
            'safe_to_proceed': bool,
            'risk_level': 'SAFE'|'MEDIUM'|'HIGH'|'CRITICAL',
            'warnings': list,
            'per_section': dict,
        }
        """
        warnings: list[dict] = []
        per_section: dict[str, dict] = {}
        max_level = 'SAFE'
        level_order = ['SAFE', 'MEDIUM', 'HIGH', 'CRITICAL']

        for section_id, content in proposed_updates.items():
            risks = self._analyze_content(section_id, content)
            per_section[section_id] = risks
            for r in risks['findings']:
                warnings.append({'section': section_id, **r})
                if level_order.index(r['level']) > level_order.index(max_level):
                    max_level = r['level']

        safe = max_level not in ('CRITICAL', 'HIGH')

        result = {
            'safe_to_proceed': safe,
            'risk_level': max_level,
            'warnings': warnings,
            'per_section': per_section,
            'recommendation': self._recommend(max_level, per_section),
        }
        logger.info('[ErrorPredictor] page=%s risk=%s safe=%s warnings=%d',
                    page_id[:8], max_level, safe, len(warnings))
        return result

    # ── 내부 ─────────────────────────────────────────────────

    @staticmethod
    def _analyze_content(section_id: str, content: str) -> dict:
        findings = []
        for pattern, name, level in DANGER_PATTERNS:
            if pattern.search(content):
                findings.append({
                    'pattern': name,
                    'level': level,
                    'description': ErrorPredictor._describe(name),
                })
        return {
            'section_id': section_id,
            'findings': findings,
            'safe': all(f['level'] not in ('CRITICAL', 'HIGH') for f in findings),
        }

    @staticmethod
    def _describe(name: str) -> str:
        desc = {
            'escape_mismatch':    'fetch 반환 이스케이프 ≠ 저장값 → update_content 매칭 실패',
            'table_row':          '테이블 행 — replace_content(전체 테이블 교체) 필수',
            'callout_blockquote': 'Callout/blockquote — rich_text 배열 구조, update_content 불가',
            'bold_inline':        'Bold 마크다운 — 이스케이프 위험, replace_content 권장',
            'inline_code':        '인라인 코드 — 이스케이프 위험, replace_content 권장',
            'link':               '링크 — 이스케이프 위험, replace_content 권장',
        }
        return desc.get(name, name)

    @staticmethod
    def _recommend(risk_level: str, per_section: dict) -> str:
        if risk_level == 'SAFE':
            return 'update_content 또는 replace_content 모두 사용 가능'
        if risk_level == 'MEDIUM':
            return 'replace_content 권장 (MEDIUM 위험 패턴 감지)'
        high_sections = [s for s, v in per_section.items()
                         if any(f['level'] in ('HIGH', 'CRITICAL')
                                for f in v['findings'])]
        return (f'replace_content 필수 — 위험 섹션: {high_sections}. '
                f'update_content 사용 금지')
