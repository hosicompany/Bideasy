# 입찰상식(K) 주간 초안 — 로컬 Claude 실행 브리프

> 2026-11-05 신설. 서버의 수요일 자동 초안(`content.weekly_knowledge_draft`, OpenRouter)을 끄고,
> 맥의 Paseo 예약 작업(Claude 구독)이 매주 수요일 07:00 KST 에 이 문서를 읽고 초안 **1편**을 만든다.
> 이 문서는 그 무인 작업의 지시서다. 사람이 읽어도 같은 절차로 재현할 수 있다.

## 0. 절대 규칙
- **업로드·발행·커밋·푸시를 하지 않는다.** 결과물은 로컬 폴더에만 둔다. 운영 반영은 대표 승인 뒤 대화 세션에서 한다.
- 질문하지 않는다(AskUserQuestion 금지). 막히면 막힌 이유를 결과 보고에 적고 끝낸다.
- 모든 문장은 한국어. 톤은 기존 글처럼 해요체(“사장님 눈높이”).
- 금지: `낙찰률`(→ 투찰률·하한율 등 정확한 용어), 낙찰가 예측·적중·보장·“안전 투찰” 같은 표현. 비판 맥락 인용만 예외.
- 숫자·제도 설명은 **공식 원문**(법제처 law.go.kr, 조달청, 행정안전부, 나라장터 안내)을 우선 근거로 쓰고, 못 찾으면 “확인 필요”로 쓰거나 뺀다. 2차 자료(블로그·보도)는 본문에 그렇게 밝힌다.

## 1. 이번 주 주제 고르기
대상 큐(번호순): **K21 → K22 → K23 → K24**. 주제 원본 = `backend/app/services/content_engine.py` 의 `TOPIC_SEEDS`(title·angle·keyword).

1. `https://bideasy.kr/sitemap-blog.xml` 에 `knowledge-kNN` 이 이미 있으면 발행된 것 → 건너뛴다.
2. `~/bideasy-drafts/knowledge-kNN/draft.md` 가 이미 있으면 이전 주에 만든 것 → 건너뛴다.
3. 남은 것 중 가장 작은 번호 1개를 고른다. 남은 게 없으면 “큐 소진 — 다음 주제 지시 필요”라고 보고하고 끝낸다.

시드 제목은 출발점일 뿐이다. 검색어(`keyword`)를 살리면서 더 정확하고 자연스러운 제목으로 고쳐도 된다.

## 2. 조사
- 주제의 핵심 사실 3~6개를 정하고, 각각 출처 URL 과 원문 문장을 확보한다(WebSearch·WebFetch, 첨부 PDF 는 내려받아 `pdftotext`).
- 조사 메모를 `~/bideasy-drafts/knowledge-kNN/sources.md` 에 남긴다(주장 · 출처 URL · 인용 · 확인 수준 🟢1차/🟡2차/🔴미확인).

## 3. 초안 작성 → `~/bideasy-drafts/knowledge-kNN/draft.md`
형식(기존 발행 글 `credit-rating-certificate-guide` 와 같은 구조):

```
---
title: (40자 안팎, 검색어 포함)
slug: knowledge-kNN
category: 입찰상식
summary: (120~160자, 무엇을 알게 되는지)
tags: 쉼표로 5~6개
---
도입 2~3문장(사장님이 겪는 상황) → "> **30초 요약** — …" → ## 본문 소제목 4~7개(표·번호 목록 활용)
→ ## 자주 묻는 질문(Q 2~3개) → ## 오늘의 결론(계산기 /calculator 등 내부 링크 1~2개) → **출처** 목록(빈 줄 뒤 "- ")
```
- 분량: 본문 2,500~4,500자.
- 굵게 표시 안에 따옴표를 넣지 않는다(`**'…'**` 는 렌더링이 깨진다).
- 이미지는 넣지 않는다(대표 이미지는 사람이 따로 판단).

## 4. 점검
```
backend/.venv/bin/python backend/scripts/blog_draft_check.py ~/bideasy-drafts/knowledge-kNN/draft.md
```
- `banned_terms` 가 FAIL 이면 고쳐서 다시 돌린다. `unsourced_numbers` WARN 은 출처를 본문에 밝히거나 숫자를 뺀다.
- 결과: 같은 폴더의 `checks.json`, `preview.html`.

## 5. 결과 보고(마지막 메시지)
다음을 한국어로 짧게:
1. 고른 주제(K번호)와 최종 제목
2. 파일 위치(`draft.md`, `preview.html`, `sources.md`)
3. 점검 결과 4종
4. 🟡·🔴 로 남은 사실(대표가 확인해야 할 것)
5. “승인하면 대화 세션에서 비공개 초안 업로드 → 발행” 안내
