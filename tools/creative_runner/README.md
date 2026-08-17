# BidEasy 로컬 Higgsfield runner

인증된 운영자 Mac에서만 Higgsfield 작업을 수행하는 lease 기반 runner입니다. BidEasy 서버는 brief와 작업 상태만
관리하며 Higgsfield 쿠키·토큰·설정 파일을 받지 않습니다. runner 역시 서버가 지정한 로컬 경로나 임의 CLI 인자를
실행하지 않습니다.

## 설치

Python 3.12, `ffmpeg`/`ffprobe`, Higgsfield CLI **1.1.23**이 필요합니다.

```bash
npm install -g @higgsfield/cli@1.1.23
python3.12 -m venv tools/creative_runner/.venv
tools/creative_runner/.venv/bin/pip install -r tools/creative_runner/requirements.txt
higgsfield auth login
higgsfield workspace set <workspace-id>
```

`.env.example`의 이름만 참고해 값은 로컬 셸 또는 비밀 저장소에 설정합니다. 특히
`CREATIVE_RUNNER_TOKEN`은 커밋하지 않습니다. 서버에서는 current/previous 토큰을 함께 받아 무중단으로
회전할 수 있지만 runner는 현재 토큰 하나만 보유합니다.

`CREATIVE_BRAND_POLICY_PATH`는 기본적으로 `docs/CREATIVE_BRAND_KIT.json` 정본을 가리킵니다. runner는
시작할 때 금지 주장과 실제 UI·음성·사람 검수 규칙이 약화되지 않았는지 확인합니다. 원격에서 추출한 kit은
로고 누락과 잘못된 영문 tagline이 있어 정본으로 쓰지 않습니다. `HIGGSFIELD_BRAND_KIT_ID`는 향후 별도
승인된 DTC Ads 경로를 위한 선택값일 뿐, 현재 allowlist 명령에는 자동으로 전달되지 않습니다.
`CREATIVE_RUNNER_FONT_DIR`는 기본적으로 `frontend/assets/fonts`를 가리키며, 정본 Pretendard
Regular/Medium/Bold 세 파일이 모두 열리는지도 preflight에서 확인합니다.
`CREATIVE_BRAND_ASSET_ROOT`는 기본적으로 `infra/nginx/html`을 가리킵니다. 브랜드 정본에 기록한 로고와
다섯 source UI의 SHA-256을 preflight에서 재검산하며, manifest에 없는 source UI는 생성 작업 전에 거부합니다.
현재 구형 guide 화면 다섯 장은 해시 변조 감시 대상으로는 남아 있지만 모두 `campaign_approved=false`입니다.
새 공개 전기공사 화면을 마스킹·사람 검수하고 manifest에 승인 표시와 새 SHA-256을 넣기 전에는
Marketing Studio 이미지·영상 작업이 로컬 정책에서 거부됩니다.

```bash
tools/creative_runner/.venv/bin/python tools/creative_runner/run.py --preflight-only
tools/creative_runner/.venv/bin/python tools/creative_runner/run.py
```

`--once`는 대기 중 작업을 최대 한 건만 처리합니다. preflight는 유료 생성을 하지 않고 다음만 검사합니다.

- 실행 파일이 `higgsfield 1.1.23`인지
- 로컬 계정 세션이 유효한지
- 현재 workspace가 `HIGGSFIELD_WORKSPACE_ID`와 같은지

## 음성 전 프리비즈

`docs/CREATIVE_PREPRODUCTION_15S.json`에서 A/B 카피·15초 장면표·공개 공고 근거를 검증하고,
Higgsfield 호출 없이 provider용 무문자 보드와 사람 검수용 A/B 보드·무음 AAC 프리비즈를 만들 수 있습니다.

```bash
uv run --with-requirements tools/creative_runner/requirements-dev.txt \
  python tools/creative_runner/render_prevoice.py
```

출력은 `preproduction-output/`에만 남고 git에서 제외됩니다. 사람 검수용 결과는 실제 UI가 아닌 와이어프레임이며
`PREVIZ · 실제 UI/음성 교체 전 · 게시 금지` 표시를 제거하거나 게시 자산으로 등록하면 안 됩니다.
실제 전기공사 화면과 대표 음성이 모두 비공개 입력 경로에 올라온 뒤에만 영상 brief를 승인·queue합니다.

## 보안 경계

- CLI 실행은 `subprocess` argv만 사용하며 `shell=True`나 셸 문자열을 사용하지 않습니다.
- 허용 작업은 `gpt_image_2`, `marketing_studio_image`, `marketing_studio_video`, `reframe`,
  `brain_activity`뿐입니다. 작업별 파라미터 값도 닫힌 allowlist입니다.
- 입력은 `bideasy.kr`/`api.bideasy.kr`의 HTTPS URL만 받고 SHA-256·MIME·크기·magic bytes를 검증합니다.
  허용 호스트를 늘릴 때는 `CREATIVE_RUNNER_INPUT_HOSTS`에 정확한 hostname을 추가합니다.
- CLI 자식 프로세스에는 `CREATIVE_RUNNER_TOKEN`을 전달하지 않습니다. API에는 Higgsfield 인증정보를
  전송하지 않습니다.
- 429/5xx만 30초, 120초, 300초 간격으로 최대 세 번 재시도합니다. 대기 중에도 heartbeat를 보냅니다.
- timeout이나 오류 출력에서 기존 Higgsfield job ID가 발견되면 `generate get/wait`로 먼저 재결합합니다.
  ID를 확인할 수 없으면 과금 중복을 피하려고 새 생성을 시작하지 않고 실패로 보고합니다.
- 결과는 임시 디렉터리에서 처리한 뒤 multipart로 업로드합니다. 로컬 파일 경로는 서버에 저장하지 않습니다.

## 파생물 계약

- 이미지: `blog_hero_16_9` 1376×768, `static_4_5` 1080×1350, `static_1_1` 1080×1080의
  RGB PNG와 WebP(quality 82)를 생성합니다.
- `blog_hero_16_9`는 GPT Image 2의 텍스트 없는 배경으로만 만들며 source UI나 카피를 합성하지 않습니다.
- `static_4_5`/`static_1_1`에는 brief의 hook/body/CTA와 브랜드 정본의 endline·민간 서비스 고지를 Pillow
  PNG 레이어로 합성합니다. 실제 UI와 한글 카피는 생성 모델 입력으로 보내지 않습니다.
- 영상: Marketing Studio `mode=ugc`, `specific_mode=from_storyboard`, 1080p, 생성 음성 끔을 고정한 뒤
  `video_9_16` 1080×1920, `video_1_1` 1080×1080 또는 `video_16_9` 1280×720으로 결정적 후처리합니다. H.264/AAC, `yuv420p`, faststart MP4와 PNG
  poster를 만듭니다.
- Marketing Studio 영상 카피는 Pillow 투명 PNG로 먼저 렌더링하고 FFmpeg argv filter에서 0–2초 hook, 10–13초 비예측
  고지, 13–15초 endline·CTA·민간 서비스 고지를 시간 지정 합성합니다. `drawtext`와 셸은 쓰지 않습니다.
  Reframe은 이미 합성된 원본만 비율 변환하며 카피나 source UI를 중복 합성하지 않습니다.
- `voiceover` 입력은 생성형 음성에 넘기지 않고 FFmpeg에서 대표의 승인 음성으로 교체합니다.
- `source_ui` 이미지는 `composite_source_ui=true`일 때만 정규화된 `overlay_box=[x,y,w,h]` 위치에
  Pillow로 합성합니다. 한글·금액·공고번호를 모델에 다시 그리게 하지 않습니다.
- 보조 결과와 원본을 먼저 업로드하고 대표 PNG/MP4를 마지막에 `is_primary=true`로 올립니다. 이 마지막
  업로드만 서버 상태를 `REVIEW_REQUIRED`로 전환합니다.
- Marketing Studio/Reframe의 결정적 합성이 끝난 대표 MP4에만 Virality Predictor를 자동 실행하고, 보고서를
  같은 attempt의 보조 자산으로 대표 MP4보다 먼저 업로드합니다. Predictor job ID는 생성 job ID와 별도로
  heartbeat에 기록하므로 runner 재시작 시 기존 job을 `get/wait`하고 새 분석을 중복 생성하지 않습니다.
- Virality Predictor 결과는 JSON 보고서로만 업로드하며 자동 승인이나 게시를 유발하지 않습니다.
- 각 attempt 전후 로컬 `account status`의 숫자 credits만 읽어 `before`/`after`/`delta`를 결과 metadata에
  남깁니다. 값이 없으면 `null`과 안전한 warning만 기록하며 이메일·구독정보·원본 계정 응답은 보내지 않습니다.

## API 계약

모든 요청은 `Authorization: Bearer <CREATIVE_RUNNER_TOKEN>`을 사용합니다.

- `POST /claim` — `{runner_id, cli_version}`; 작업이 없으면 204
- `POST /{attempt_id}/heartbeat` — `{runner_id, status, higgsfield_job_id?, virality_job_id?}`
- `POST /{attempt_id}/output` — multipart `runner_id`, `file`, `kind`, `is_primary`, `metadata_json`, `sha256`
- `POST /{attempt_id}/fail` — `{runner_id, error, auth_required, retryable}`

claim snapshot에는 승인된 `hook`, `body_copy`, `cta_copy`, `brief_format`, 기존 `higgsfield_job_id`와
`virality_job_id`가 포함됩니다.
정적/Marketing Studio 영상은 정확히 한 개의 manifest source UI를 요구하고, 영상은 storyboard 이미지와 실제
voiceover도 각각 한 개씩 요구합니다. 기존 job ID가 있으면 runner는 `generate get/wait`로만 재결합합니다.

Virality Predictor 원본 응답은 공개 자산에 보존하지 않습니다. 알려진 명시 key만
`hook_peak_seconds`, `sustain_score`, `attention_overlaps_product`로 정규화하고, query/fragment 없는
Higgsfield HTTPS URL만 `report_url`로 남깁니다. 알 수 없는 값은 추정하지 않고 `null`로 남겨 사람 검수를
요구합니다.

CLI 로그인이나 workspace 선택이 풀리면 해당 작업은 `AUTH_REQUIRED`가 됩니다. 서버에서 자동 로그인하거나
Higgsfield 자격증명을 보관하는 우회 경로는 만들지 않습니다.
