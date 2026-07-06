# AGENTS.md — 포인터 (내용 복사 금지)

이 저장소의 모든 규칙·현재 상태·함정 목록·검증 명령의 **정본은 이 폴더의 `CLAUDE.md`**다.

1. 작업 시작 전 `CLAUDE.md` 전체 + `git log --oneline -30`을 읽는다. 특히 "⚠️ 함정·금지 목록"은 위반 시 운영 사고다.
2. 코드 변경 후 CLAUDE.md §8의 검증 명령(`cd backend && pytest`)을 반드시 실행한다. git pre-commit 훅이 커밋 시 재검증하며, 실패 상태로는 커밋되지 않는다.
3. 완료 보고는 Gate Check 양식: 변경 파일 / 실행한 검증 / 신뢰도(🟢🟡🔴) / 미해결 사항.

전역 규칙: `C:\Users\hosic\.claude\CLAUDE.md`
