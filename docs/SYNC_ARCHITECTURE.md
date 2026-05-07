# Notion Sync Architecture

> **PRIORITY-5** | GitHub ↔ Notion 자동 동기화 전체 아키텍처
> ROI: 운영 overhead 완전 제거

---

## 전체 흐름

```
[트리거]
  push → session_logs/**  ──┐
  schedule 09:00 KST      ──┤──▶ preflight ──▶ sync (parallel) ──▶ audit
  workflow_dispatch        ──┘
```

---

## 파일 구조

```
notion-api-architecture/
├── .github/workflows/
│   └── notion-sync.yml          # 워크플로우 진입점
├── automation/
│   ├── metadata_manager.py      # Phase 2~4 공통 패턴 핵심
│   ├── notion_writer.py         # replace_content SOP 안전 레이어
│   ├── error_predictor.py       # 사전 검증·위험도 예측
│   ├── queue_manager.py         # 우선순위 큐 엔진
│   ├── preflight.py             # Actions Job: Pre-flight
│   ├── sync_runner.py           # Actions Job: 동기화 실행
│   └── audit_logger.py          # Actions Job: 감사 로그
├── config/
│   └── sync_config.yml          # 대상 페이지·정책 설정
├── session_logs/                # SESSION-C** 세션일지 (push 트리거)
├── audit_logs/                  # 자동 생성 감사 JSONL
├── reports/                     # 실행별 sync 리포트 JSON
└── docs/
    └── SYNC_ARCHITECTURE.md     # 본 문서
```

---

## GitHub Actions 3-Job 구조

| Job | 역할 | 핵심 동작 |
|-----|------|----------|
| `preflight` | 사전 검증 | NOTION_TOKEN 확인, 대상 페이지 결정, matrix 출력 |
| `sync` | 동기화 실행 | 페이지별 병렬 실행 (max 2), replace_content SOP 적용 |
| `audit` | 감사 로그 | 결과 집계 → audit_logs/*.jsonl 커밋 |

---

## Phase 2~4 공통 패턴 (metadata_manager.py)

```python
from automation.metadata_manager import (
    initialize_section_metadata,
    update_section_by_metadata,
    validate_metadata_integrity,
    error_predictor,
    parallel_section_update,
)

# 사전 검증 → 안전 실행 → S4 검증 자동화
token = os.environ["NOTION_TOKEN"]
meta  = initialize_section_metadata(PAGE_ID, token, "T-09 Mother Page")
check = error_predictor(PAGE_ID, proposed_updates, token)
if check["safe_to_proceed"]:
    results = parallel_section_update(PAGE_ID, proposed_updates, token)
```

---

## SESSION-C33 확정 원칙 내재화

| 작업 유형 | 메서드 | 파일 |
|-----------|--------|------|
| 갱신 배너 추가 | `replace_content` | notion_writer.py |
| 테이블 행 추가/변경 | `replace_content` | notion_writer.py |
| KG 수치 (평문 숫자만) | `update_content` | notion_writer.py |
| EW 트리거 테이블 갱신 | `replace_content` | notion_writer.py |

**앵커 정규화** (`_normalize_anchor`): fetch 반환 이스케이프(`\[`, `\|`, `\~`) → 실제 저장값 자동 변환

---

## Automation Queue 우선순위

| Level | 대상 | 예시 |
|-------|------|------|
| CRITICAL (0) | 즉시 실행 | 오류 복구, 배너 갱신 |
| HIGH (1) | 세션 종료 sync | 세션일지 push |
| NORMAL (2) | 일일 스케줄 | KG 테이블, EW 트리거 |
| LOW (3) | 정적 섹션 | 링크, SOP |

---

## GitHub Secret 설정

```
Settings → Secrets and variables → Actions → New repository secret
  Name:  NOTION_TOKEN
  Value: secret_xxxxxxxxxxxxxxxxxxxx
```

---

## 운영 명령

```bash
# 즉시 수동 실행
ghActions → notion-sync → Run workflow → sync_mode: incremental

# dry_run (검증만)
ghActions → notion-sync → Run workflow → sync_mode: dry_run

# 전체 재동기화
ghActions → notion-sync → Run workflow → sync_mode: full

# 로컬 테스트
NOTION_TOKEN=secret_xxx python automation/sync_runner.py
```
