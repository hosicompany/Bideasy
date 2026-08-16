const API_BASE = 'https://api.bideasy.kr/api/v1';

const STATUS_META = {
  DRAFT: ['초안', 'status-draft'],
  BRIEF_APPROVED: ['브리프 승인', 'status-ready'],
  QUEUED: ['대기 중', 'status-running'],
  CLAIMED: ['Runner 연결', 'status-running'],
  GENERATING: ['생성 중', 'status-running'],
  PROCESSING: ['후처리 중', 'status-running'],
  REVIEW_REQUIRED: ['검수 필요', 'status-review'],
  APPROVED: ['승인됨', 'status-success'],
  PUBLISHED: ['게시됨', 'status-success'],
  AUTH_REQUIRED: ['Higgsfield 인증 필요', 'status-danger'],
  CHANGES_REQUESTED: ['변경 요청', 'status-stale'],
  STALE: ['정본 변경', 'status-stale'],
  FAILED: ['실패', 'status-danger'],
};

const RUNNING_STATUSES = new Set(['QUEUED', 'CLAIMED', 'GENERATING', 'PROCESSING']);
const state = {
  items: [],
  selected: null,
  storedInputs: [],
  dirty: false,
  busy: false,
  selectSequence: 0,
  loadSequence: 0,
};

let toastTimer = null;
const assetObjectUrls = new Set();
const inputAssetObjectUrls = new Set();

function el(id) { return document.getElementById(id); }

function getToken() {
  try {
    return localStorage.getItem('access_token') || localStorage.getItem('jwt') || null;
  } catch {
    return null;
  }
}

function clearToken() {
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('jwt');
  } catch {}
}

function detailMessage(detail, fallback) {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item && (item.msg || item.message || String(item))).join(' · ') || fallback;
  }
  if (detail && typeof detail === 'object') return detail.message || detail.msg || fallback;
  return fallback;
}

async function api(path, init = {}) {
  const token = getToken();
  if (!token) throw new Error('NO_TOKEN');
  const headers = new Headers(init.headers || {});
  headers.set('Authorization', 'Bearer ' + token);
  if (init.body != null && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(API_BASE + path, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (response.status === 403) throw new Error('FORBIDDEN');
  if (response.status === 204) return null;

  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (!response.ok) throw new Error(detailMessage(data && data.detail, `오류 ${response.status}`));
  return data;
}

async function authenticatedAssetUrl(outputId) {
  const token = getToken();
  if (!token) throw new Error('NO_TOKEN');
  const response = await fetch(
    `${API_BASE}/admin/creative-outputs/${encodeURIComponent(outputId)}/download`,
    { headers: { Authorization: 'Bearer ' + token } },
  );
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (response.status === 403) throw new Error('FORBIDDEN');
  if (!response.ok) throw new Error(`자산을 불러오지 못했어요 (${response.status})`);
  const objectUrl = URL.createObjectURL(await response.blob());
  assetObjectUrls.add(objectUrl);
  return objectUrl;
}

async function authenticatedInputAssetUrl(assetId) {
  const token = getToken();
  if (!token) throw new Error('NO_TOKEN');
  const response = await fetch(
    `${API_BASE}/admin/creative-inputs/${encodeURIComponent(assetId)}/download`,
    { headers: { Authorization: 'Bearer ' + token } },
  );
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (response.status === 403) throw new Error('FORBIDDEN');
  if (!response.ok) throw new Error(`입력 자산을 불러오지 못했어요 (${response.status})`);
  const objectUrl = URL.createObjectURL(await response.blob());
  inputAssetObjectUrls.add(objectUrl);
  return objectUrl;
}

function releaseAssetObjectUrls() {
  for (const objectUrl of assetObjectUrls) URL.revokeObjectURL(objectUrl);
  assetObjectUrls.clear();
}

function releaseInputAssetObjectUrls() {
  for (const objectUrl of inputAssetObjectUrls) URL.revokeObjectURL(objectUrl);
  inputAssetObjectUrls.clear();
}

function toast(message, type = 'info', duration = 3500) {
  const node = el('toast');
  if (toastTimer) window.clearTimeout(toastTimer);
  node.textContent = message;
  node.className = `toast show ${type}`;
  toastTimer = window.setTimeout(() => node.classList.remove('show'), duration);
}

function showGate(message) {
  el('gate').classList.remove('hidden');
  el('app').classList.add('hidden');
  el('gate-msg').textContent = message;
  el('gate-actions').classList.remove('hidden');
  const login = el('gate-actions').querySelector('a[href^="/login"]');
  if (login) login.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
}

async function guard() {
  if (!getToken()) {
    showGate('로그인이 필요해요. 운영자 계정으로 로그인해주세요.');
    return null;
  }
  try {
    const me = await api('/users/me');
    if (!me || !me.is_admin) {
      showGate('관리자 권한이 필요해요.');
      return null;
    }
    el('user-email').textContent = me.email || String(me.id || '관리자');
    el('gate').classList.add('hidden');
    el('app').classList.remove('hidden');
    return me;
  } catch (error) {
    if (error.message === 'UNAUTHORIZED' || error.message === 'NO_TOKEN') {
      showGate('세션이 만료됐어요. 다시 로그인해주세요.');
    } else if (error.message === 'FORBIDDEN') {
      showGate('관리자 권한이 필요해요.');
    } else {
      showGate('권한을 확인하지 못했어요. 잠시 뒤 다시 시도해주세요.');
    }
    return null;
  }
}

function unwrapItems(data) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== 'object') return [];
  if (Array.isArray(data.items)) return data.items;
  if (Array.isArray(data.creatives)) return data.creatives;
  if (Array.isArray(data.results)) return data.results;
  return [];
}

function unwrapCreative(data) {
  if (!data || typeof data !== 'object') return data;
  return data.creative || data.item || data.brief || data;
}

function creativeId(creative) {
  return creative && (creative.id ?? creative.creative_id);
}

function normalizedStatus(value) {
  return String(value || 'DRAFT').trim().toUpperCase();
}

function statusMeta(value) {
  const status = normalizedStatus(value);
  return STATUS_META[status] || [status, 'status-draft'];
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

function compactText(value, max = 90) {
  const text = String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

const INPUT_ROLE_LABELS = {
  source_ui: '실제 제품 화면',
  storyboard: '스토리보드',
  voiceover: '대표 실제 음성',
  reference: '참고 자산',
};

function privateInputId(url) {
  try {
    const parsed = new URL(String(url || ''), new URL(API_BASE).origin);
    if (parsed.origin !== new URL(API_BASE).origin || parsed.search || parsed.hash) return null;
    const match = parsed.pathname.match(/^\/api\/v1\/creative-runner\/inputs\/([1-9][0-9]*)\/download$/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function renderInputFiles(files, uploadedAsset = null) {
  releaseInputAssetObjectUrls();
  const container = el('input-assets');
  container.replaceChildren();
  const items = Array.isArray(files) ? files : [];
  const stored = Array.isArray(state.storedInputs) ? state.storedInputs : [];
  const storedKeys = new Set(stored.map((asset) => `${asset.role}:${asset.sha256}`));
  const displayItems = [
    ...stored,
    ...items
      .filter((item) => !storedKeys.has(`${item.role}:${item.sha256}`))
      .map((manifest) => ({ manifest, ...manifest })),
  ];
  const status = el('input-upload-status');
  if (!displayItems.length) {
    status.textContent = creativeId(state.selected) == null
      ? '브리프를 먼저 저장하면 입력 파일을 연결할 수 있어요.'
      : '아직 연결된 입력 파일이 없어요. 업로드 뒤 브리프를 저장해주세요.';
    return;
  }
  status.textContent = `비공개 저장 ${stored.length}개 · 현재 생성 설정 연결 ${items.length}개예요. 연결 변경은 브리프를 저장해야 큐 스냅샷에 반영돼요.`;

  for (const asset of displayItems) {
    const item = asset.manifest || asset;
    const isConnected = items.some(
      (entry) => entry && entry.role === item.role && entry.sha256 === item.sha256,
    );
    const card = document.createElement('article');
    card.className = 'input-asset-card';
    const preview = document.createElement('div');
    preview.className = 'input-asset-preview';
    preview.textContent = '인증된 미리보기를 불러오는 중이에요.';
    const roleNode = document.createElement('div');
    roleNode.className = 'input-asset-role';
    roleNode.textContent = INPUT_ROLE_LABELS[item.role] || String(item.role || '입력 자산');
    const metadata = document.createElement('div');
    metadata.className = 'input-asset-meta';
    const matchingUpload = asset.id ? asset
      : (uploadedAsset && uploadedAsset.sha256 === item.sha256 ? uploadedAsset : null);
    metadata.textContent = [
      item.mime_type,
      matchingUpload && matchingUpload.width && matchingUpload.height
        ? `${matchingUpload.width}×${matchingUpload.height}` : '',
      matchingUpload && matchingUpload.duration_ms
        ? `${(Number(matchingUpload.duration_ms) / 1000).toFixed(1)}초` : '',
      matchingUpload ? formatBytes(matchingUpload.size_bytes) : '',
      item.sha256 ? `SHA ${compactText(item.sha256, 18)}` : '',
    ].filter(Boolean).join(' · ');
    const actions = document.createElement('div');
    actions.className = 'input-asset-actions';
    const connect = document.createElement('button');
    connect.type = 'button';
    connect.className = isConnected ? 'input-connected' : 'btn btn-outline';
    connect.textContent = isConnected ? '생성 설정에 연결됨' : '이 입력 다시 연결';
    connect.disabled = isConnected || state.busy
      || RUNNING_STATUSES.has(normalizedStatus(state.selected && state.selected.status));
    if (!isConnected && asset.manifest) {
      connect.dataset.reconnectable = 'true';
      connect.addEventListener('click', () => {
        try {
          insertInputManifest(asset.manifest, asset);
          toast('비공개 입력을 다시 연결했어요. 브리프를 저장해주세요.', 'success');
        } catch (error) {
          toast(error.message || '입력을 다시 연결하지 못했어요.', 'error');
        }
      });
    } else if (!isConnected) {
      connect.disabled = true;
      connect.textContent = '기존 외부 입력';
    }
    actions.appendChild(connect);
    card.append(preview, roleNode, metadata, actions);
    container.appendChild(card);

    const assetId = privateInputId(item.url);
    if (!assetId) {
      preview.textContent = '기존 외부 입력 자산이에요.';
      continue;
    }
    authenticatedInputAssetUrl(assetId).then((objectUrl) => {
      if (!card.isConnected) {
        URL.revokeObjectURL(objectUrl);
        inputAssetObjectUrls.delete(objectUrl);
        return;
      }
      const mime = String(item.mime_type || '').toLowerCase();
      if (mime.startsWith('image/')) {
        const image = document.createElement('img');
        image.src = objectUrl;
        image.alt = `${roleNode.textContent} 비공개 미리보기`;
        preview.replaceChildren(image);
      } else if (mime.startsWith('video/')) {
        const video = document.createElement('video');
        video.src = objectUrl;
        video.controls = true;
        video.preload = 'metadata';
        preview.replaceChildren(video);
      } else if (mime.startsWith('audio/')) {
        const audio = document.createElement('audio');
        audio.src = objectUrl;
        audio.controls = true;
        audio.preload = 'metadata';
        preview.replaceChildren(audio);
      } else {
        preview.textContent = '미리보기를 제공하지 않는 형식이에요.';
      }
    }).catch((error) => {
      preview.textContent = error.message === 'UNAUTHORIZED'
        ? '세션이 만료되어 미리보기를 불러오지 못했어요.'
        : '비공개 미리보기를 불러오지 못했어요.';
    });
  }
}

function updateInputAccept() {
  const role = value('f-input-role');
  const accepts = {
    source_ui: 'image/png,image/jpeg,image/webp,video/mp4',
    storyboard: 'image/png,image/jpeg,image/webp',
    voiceover: 'audio/mpeg,audio/wav,.mp3,.wav',
    reference: 'image/png,image/jpeg,image/webp,video/mp4,audio/mpeg,audio/wav,.mp3,.wav',
  };
  el('f-input-file').accept = accepts[role] || accepts.reference;
  el('f-input-file').value = '';
}

function insertInputManifest(manifest, uploadedAsset) {
  let generationSpec;
  try {
    generationSpec = JSON.parse(value('f-generation-spec'));
  } catch {
    throw new Error('입력 자산을 연결하기 전에 생성 설정 JSON을 먼저 고쳐주세요.');
  }
  if (!generationSpec || Array.isArray(generationSpec) || typeof generationSpec !== 'object') {
    throw new Error('생성 설정은 JSON 객체여야 해요.');
  }
  const current = Array.isArray(generationSpec.input_files) ? generationSpec.input_files : [];
  generationSpec.input_files = manifest.role === 'reference'
    ? [...current, manifest]
    : [...current.filter((item) => item && item.role !== manifest.role), manifest];
  setValue('f-generation-spec', JSON.stringify(generationSpec, null, 2));
  setDirty(true);
  renderInputFiles(generationSpec.input_files, uploadedAsset);
}

async function uploadCreativeInput() {
  const file = el('f-input-file').files && el('f-input-file').files[0];
  if (!file) {
    toast('업로드할 파일을 선택해주세요.', 'error');
    return;
  }
  const current = state.selected;
  if (!current || creativeId(current) == null) {
    el('input-upload-status').textContent = '새 브리프를 먼저 저장한 뒤 입력 파일을 업로드해주세요.';
    toast('브리프를 먼저 저장해주세요.', 'error');
    return;
  }
  if (state.dirty) {
    el('input-upload-status').textContent = '브리프의 변경 내용을 먼저 저장한 뒤 입력 파일을 업로드해주세요.';
    toast('저장되지 않은 브리프 변경이 있어요.', 'error');
    return;
  }
  try {
    const spec = JSON.parse(value('f-generation-spec'));
    if (!spec || Array.isArray(spec) || typeof spec !== 'object') throw new Error();
    if (spec.input_files != null && !Array.isArray(spec.input_files)) throw new Error();
  } catch {
    toast('생성 설정 JSON을 먼저 고쳐주세요.', 'error');
    return;
  }
  const id = creativeId(current);
  if (id == null) return;
  const uploadCreativeId = String(id);
  const uploadSelectionSequence = state.selectSequence;
  const role = value('f-input-role');
  const form = new FormData();
  form.append('role', role);
  form.append('file', file, file.name);
  let uploadedAsset = null;
  await withBusy(async () => {
    try {
      el('input-upload-status').textContent = '파일 내용과 메타데이터를 검증해 비공개 저장 중이에요.';
      uploadedAsset = await api(`/admin/creatives/${encodeURIComponent(id)}/inputs`, {
        method: 'POST',
        body: form,
      });
      if (!uploadedAsset || !uploadedAsset.manifest) throw new Error('업로드 응답에 입력 manifest가 없어요.');
      const selectionStillMatches = uploadSelectionSequence === state.selectSequence
        && String(creativeId(state.selected)) === uploadCreativeId;
      if (!selectionStillMatches) {
        el('f-input-file').value = '';
        const recoveryMessage = `파일 #${uploadedAsset.id}은 브리프 #${uploadCreativeId}에 비공개 보관됐어요. 해당 브리프를 다시 열어 입력 목록에서 연결해주세요.`;
        el('input-upload-status').textContent = recoveryMessage;
        toast(recoveryMessage, 'info', 8000);
        return;
      }
      state.storedInputs = [
        uploadedAsset,
        ...state.storedInputs.filter((asset) => asset.id !== uploadedAsset.id),
      ];
      insertInputManifest(uploadedAsset.manifest, uploadedAsset);
      el('f-input-file').value = '';
      toast('비공개 입력을 연결했어요. 브리프를 저장하면 반영돼요.', 'success');
    } catch (error) {
      handleActionError(error, '입력 파일을 업로드하지 못했어요.');
      if (uploadedAsset && uploadedAsset.id) {
        const selectionStillMatches = uploadSelectionSequence === state.selectSequence
          && String(creativeId(state.selected)) === uploadCreativeId;
        if (!selectionStillMatches) {
          const recoveryMessage = `파일 #${uploadedAsset.id}은 브리프 #${uploadCreativeId}에 비공개 보관됐어요. 해당 브리프를 다시 열어 입력 목록에서 연결해주세요.`;
          el('input-upload-status').textContent = recoveryMessage;
          toast(recoveryMessage, 'info', 8000);
          return;
        }
        state.storedInputs = [
          uploadedAsset,
          ...state.storedInputs.filter((asset) => asset.id !== uploadedAsset.id),
        ];
        renderInputFiles((state.selected && state.selected.generation_spec_json || {}).input_files || []);
        el('input-upload-status').textContent = `파일 #${uploadedAsset.id}은 비공개 보관됐지만 생성 설정 연결에 실패했어요. 새로 올리지 말고 운영자에게 확인해주세요.`;
      } else {
        renderInputFiles((state.selected && state.selected.generation_spec_json || {}).input_files || []);
      }
    }
  });
}

function setStatusNode(node, status) {
  const [label, className] = statusMeta(status);
  node.textContent = label;
  node.className = `creative-status ${className}`;
}

function renderList() {
  const container = el('creative-list');
  const statusFilter = el('filter-status').value;
  const search = el('filter-search').value.trim().toLocaleLowerCase('ko-KR');
  const filtered = state.items.filter((item) => {
    if (statusFilter && normalizedStatus(item.status) !== statusFilter) return false;
    if (!search) return true;
    const haystack = [item.campaign_key, item.concept_key, item.variant, item.hook, item.channel]
      .map((value) => String(value || '').toLocaleLowerCase('ko-KR')).join(' ');
    return haystack.includes(search);
  });

  el('creative-count').textContent = String(filtered.length);
  container.replaceChildren();
  if (!filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'list-state';
    empty.textContent = state.items.length ? '조건에 맞는 브리프가 없어요.' : '아직 브리프가 없어요. 새 브리프로 시작해주세요.';
    container.appendChild(empty);
    return;
  }

  const selectedId = String(creativeId(state.selected) ?? '');
  for (const item of filtered) {
    const id = creativeId(item);
    if (id == null) continue;
    const [label, className] = statusMeta(item.status);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'creative-list-item' + (String(id) === selectedId ? ' active' : '');
    button.dataset.creativeId = String(id);
    button.disabled = state.busy;

    const top = document.createElement('div');
    top.className = 'list-item-top';
    const badge = document.createElement('span');
    badge.className = `creative-status ${className}`;
    badge.textContent = label;
    const version = document.createElement('span');
    version.className = 'list-item-meta';
    version.textContent = `v${item.version || 1}`;
    top.append(badge, version);

    const hook = document.createElement('div');
    hook.className = 'list-item-hook';
    hook.textContent = compactText(item.hook || item.concept_key || '제목 없는 브리프');

    const meta = document.createElement('div');
    meta.className = 'list-item-meta';
    meta.textContent = [item.campaign_key, item.channel, item.format].filter(Boolean).join(' · ') || `ID ${id}`;
    button.append(top, hook, meta);
    container.appendChild(button);
  }
}

function value(id) { return el(id).value.trim(); }
function setValue(id, data) { el(id).value = data == null ? '' : String(data); }
function setSelectValue(id, data, fallback) {
  const select = el(id);
  const wanted = String(data || fallback || '');
  if (wanted && !Array.from(select.options).some((option) => option.value === wanted)) {
    const option = document.createElement('option');
    option.value = wanted;
    option.textContent = wanted;
    select.appendChild(option);
  }
  select.value = wanted;
}

function prettyJson(value) {
  if (value == null || value === '') return '';
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
  }
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function setDirty(isDirty) {
  state.dirty = isDirty;
  const meta = el('editor-meta');
  const current = state.selected;
  const base = current
    ? `최근 수정 ${formatDate(current.updated_at || current.created_at)} · v${current.version || 1}`
    : '실제 UI와 정확한 메시지를 기준으로 작성해요.';
  meta.textContent = isDirty ? `${base} · 저장되지 않은 변경이 있어요` : base;
  renderActions();
}

function clearForm() {
  setValue('f-source-type', 'campaign');
  setValue('f-source-ref', '');
  setValue('f-source-hash', '');
  setValue('f-campaign', 'message_validation_202608');
  setValue('f-concept', 'mechanism');
  setValue('f-variant', 'A');
  setValue('f-channel', 'youtube');
  setValue('f-format', 'video_9_16');
  setValue('f-hook', '나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.');
  setValue('f-body', '보고 있는 공고 화면에서 참가조건·계산 기준·주의 조항을 확인하세요. 낙찰가는 예측하지 않습니다.');
  setValue('f-cta', '이 공고 확인하기');
  setValue('f-landing', '/calculator');
  setValue('f-utm-source', 'youtube');
  setValue('f-utm-medium', 'organic');
  setValue('f-utm-campaign', 'pm_202608_mechanism_a_v1');
  setValue('f-generation-spec', JSON.stringify({
    job_type: 'marketing_studio_video',
    prompt: 'Calm abstract blue motion background for Korean public-procurement software. Clean editorial composition, no text, no numbers, no logo, no watermark, and no interface reconstruction.',
    params: {
      specific_mode: 'from_storyboard',
      aspect_ratio: '9:16',
      resolution: '1080p',
      generate_audio: false,
      composite_source_ui: true,
    },
    input_files: [],
  }, null, 2));
  el('json-error').classList.add('hidden');
  el('json-error').textContent = '';
  el('approval-note').value = '';
  el('approval-override').value = '';
  el('review-note').value = '';
  el('review-panel').classList.add('hidden');
  el('f-input-file').value = '';
  renderInputFiles([]);
}

function fillForm(creative) {
  state.selected = creative;
  setSelectValue('f-source-type', creative.source_type, 'campaign');
  setValue('f-source-ref', creative.source_ref_id);
  setValue('f-source-hash', creative.source_hash);
  setValue('f-campaign', creative.campaign_key);
  setValue('f-concept', creative.concept_key);
  setValue('f-variant', creative.variant);
  setSelectValue('f-channel', creative.channel, 'youtube');
  setSelectValue('f-format', creative.format, 'video_9_16');
  setValue('f-hook', creative.hook);
  setValue('f-body', creative.body_copy);
  setValue('f-cta', creative.cta_copy);
  setValue('f-landing', creative.landing_path);
  setValue('f-utm-source', creative.utm_source);
  setValue('f-utm-medium', creative.utm_medium);
  setValue('f-utm-campaign', creative.utm_campaign);
  setValue('f-generation-spec', prettyJson(creative.generation_spec_json));
  el('json-error').classList.add('hidden');
  el('json-error').textContent = '';
  el('approval-note').value = '';
  el('approval-override').value = '';
  el('review-note').value = '';
  el('review-panel').classList.add('hidden');

  const id = creativeId(creative);
  el('creative-id').textContent = `creative_id ${id}`;
  el('editor-title').textContent = compactText(creative.hook || creative.concept_key || '크리에이티브 브리프', 120);
  setStatusNode(el('status-badge'), creative.status);
  setDirty(false);
  renderActions();
  renderAttempts(creative.attempts || creative.creative_attempts || []);
  renderInputFiles((creative.generation_spec_json || {}).input_files || []);
  renderList();
}

function showEditor() {
  el('empty-state').classList.add('hidden');
  el('editor').classList.remove('hidden');
}

function newCreative() {
  if (state.busy) {
    toast('진행 중인 작업이 끝난 뒤 새 브리프로 이동해주세요.', 'info');
    return;
  }
  if (state.dirty && !window.confirm('저장하지 않은 변경이 있어요. 새 브리프로 이동할까요?')) return;
  state.selectSequence += 1;
  state.selected = null;
  state.storedInputs = [];
  clearForm();
  el('creative-id').textContent = '저장 전';
  el('editor-title').textContent = '새 크리에이티브 브리프';
  setStatusNode(el('status-badge'), 'DRAFT');
  setDirty(false);
  renderActions();
  renderAttempts([]);
  renderList();
  showEditor();
  el('source-notice').classList.add('hidden');
  history.replaceState(null, '', '/admin-creatives');
  el('f-hook').focus();
}

function renderActions() {
  const creative = state.selected;
  const status = normalizedStatus(creative && creative.status);
  const saved = creativeId(creative) != null;
  const workflowLocked = saved && RUNNING_STATUSES.has(status);
  for (const field of el('creative-form').querySelectorAll('input, textarea, select')) {
    field.disabled = state.busy || workflowLocked;
  }
  for (const field of [el('f-input-role'), el('f-input-file'), el('btn-input-upload')]) {
    field.disabled = state.busy || workflowLocked;
  }
  for (const button of el('input-assets').querySelectorAll('[data-reconnectable="true"]')) {
    button.disabled = state.busy || workflowLocked;
  }
  for (const button of el('creative-list').querySelectorAll('[data-creative-id]')) {
    button.disabled = state.busy;
  }
  for (const id of ['btn-new', 'btn-empty-new', 'btn-reload']) {
    el(id).disabled = state.busy;
  }

  el('btn-save').classList.toggle('hidden', workflowLocked);
  el('btn-save').disabled = state.busy;
  el('btn-approve').classList.add('hidden');
  el('btn-queue').classList.add('hidden');
  el('btn-publish').classList.add('hidden');
  el('btn-request-changes').classList.add('hidden');
  el('approval-panel').classList.add('hidden');

  if (!saved || state.busy || state.dirty) return;
  if (['DRAFT', 'STALE', 'CHANGES_REQUESTED'].includes(status)) {
    el('btn-approve').textContent = status === 'CHANGES_REQUESTED' ? '수정 브리프 승인' : '브리프 승인';
    el('btn-approve').classList.remove('hidden');
  }
  if (status === 'REVIEW_REQUIRED') {
    el('approval-panel').classList.remove('hidden');
    el('btn-request-changes').classList.remove('hidden');
  }
  if (['BRIEF_APPROVED', 'FAILED', 'AUTH_REQUIRED'].includes(status)) {
    el('btn-queue').textContent = status === 'BRIEF_APPROVED' ? 'Higgsfield 생성 대기열' : '새 시도로 다시 생성';
    el('btn-queue').classList.remove('hidden');
  }
  if (['FAILED', 'AUTH_REQUIRED'].includes(status)) el('btn-request-changes').classList.remove('hidden');
  if (status === 'APPROVED') {
    el('btn-publish').classList.remove('hidden');
    el('btn-request-changes').classList.remove('hidden');
  }
}

function collectForm() {
  const required = [
    ['f-campaign', '캠페인 키'], ['f-concept', '콘셉트 키'], ['f-hook', '첫 훅'],
    ['f-cta', 'CTA'], ['f-landing', '랜딩 경로'],
  ];
  for (const [id, label] of required) {
    if (!value(id)) {
      el(id).focus();
      throw new Error(`${label}를 입력해주세요.`);
    }
  }
  const landing = value('f-landing');
  const pathParts = landing.split(/[?#]/, 1)[0].split('/');
  if (!landing.startsWith('/') || landing.startsWith('//') || landing.includes('\\')
      || pathParts.includes('..') || /[\u0000-\u001f]/.test(landing)) {
    el('f-landing').focus();
    throw new Error('랜딩 경로는 같은 사이트의 / 경로만 사용할 수 있어요.');
  }

  const keyPattern = /^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$/;
  for (const id of ['f-campaign', 'f-concept']) {
    if (!keyPattern.test(value(id))) {
      el(id).focus();
      throw new Error('캠페인·콘셉트 키에는 영문, 숫자, _, ., :, -만 사용할 수 있어요.');
    }
  }
  const sourceHash = value('f-source-hash').toLowerCase();
  if (sourceHash && !/^[0-9a-f]{64}$/.test(sourceHash)) {
    el('f-source-hash').focus();
    throw new Error('출처 해시는 64자 SHA-256 형식이어야 해요.');
  }

  let generationSpec = {};
  const rawSpec = value('f-generation-spec');
  if (rawSpec) {
    try {
      generationSpec = JSON.parse(rawSpec);
    } catch {
      el('json-error').textContent = 'JSON 형식을 확인해주세요.';
      el('json-error').classList.remove('hidden');
      el('f-generation-spec').focus();
      throw new Error('Higgsfield 생성 설정의 JSON 형식이 올바르지 않아요.');
    }
    if (!generationSpec || Array.isArray(generationSpec) || typeof generationSpec !== 'object') {
      el('json-error').textContent = '생성 설정은 JSON 객체여야 해요.';
      el('json-error').classList.remove('hidden');
      throw new Error('Higgsfield 생성 설정은 JSON 객체로 입력해주세요.');
    }
    const jobTypes = new Set(['gpt_image_2', 'marketing_studio_image', 'marketing_studio_video', 'reframe', 'brain_activity']);
    if (!jobTypes.has(generationSpec.job_type)) {
      el('json-error').textContent = '지원하는 job_type을 선택해주세요.';
      el('json-error').classList.remove('hidden');
      throw new Error('Higgsfield 생성 설정의 job_type을 확인해주세요.');
    }
    if (generationSpec.input_files != null && !Array.isArray(generationSpec.input_files)) {
      el('json-error').textContent = 'input_files는 배열이어야 해요.';
      el('json-error').classList.remove('hidden');
      throw new Error('Higgsfield 생성 설정의 input_files를 확인해주세요.');
    }
  }
  el('json-error').classList.add('hidden');

  return {
    source_type: value('f-source-type') || 'manual',
    source_ref_id: value('f-source-ref') || null,
    source_hash: sourceHash || null,
    campaign_key: value('f-campaign'),
    concept_key: value('f-concept'),
    variant: value('f-variant') || 'A',
    channel: value('f-channel'),
    format: value('f-format'),
    hook: value('f-hook'),
    body_copy: value('f-body'),
    cta_copy: value('f-cta'),
    landing_path: landing,
    utm_source: value('f-utm-source') || null,
    utm_medium: value('f-utm-medium') || null,
    utm_campaign: value('f-utm-campaign') || null,
    generation_spec_json: generationSpec,
  };
}

async function withBusy(work) {
  if (state.busy) return null;
  state.busy = true;
  renderActions();
  try {
    return await work();
  } finally {
    state.busy = false;
    renderActions();
  }
}

async function saveCreative(options = {}) {
  let body;
  try { body = collectForm(); } catch (error) {
    toast(error.message, 'error');
    return null;
  }
  const id = creativeId(state.selected);
  const currentStatus = normalizedStatus(state.selected && state.selected.status);
  if (id != null && state.dirty && ['REVIEW_REQUIRED', 'APPROVED', 'PUBLISHED'].includes(currentStatus)
      && !window.confirm('이 브리프를 수정하면 현재 승인 상태가 해제되고 다시 생성·검수해야 해요. 저장할까요?')) {
    return null;
  }
  return withBusy(async () => {
    try {
      const data = await api(id == null ? '/admin/creatives' : `/admin/creatives/${encodeURIComponent(id)}`, {
        method: id == null ? 'POST' : 'PUT',
        body: JSON.stringify(body),
      });
      const creative = unwrapCreative(data);
      if (!creative || creativeId(creative) == null) throw new Error('저장 응답에 creative_id가 없어요.');
      state.selected = creative;
      setDirty(false);
      const savedId = creativeId(creative);
      history.replaceState(null, '', `/admin-creatives?creative_id=${encodeURIComponent(savedId)}`);
      await loadCreatives(savedId, creative);
      if (!options.quiet) toast('브리프를 저장했어요.', 'success');
      return creative;
    } catch (error) {
      handleActionError(error, '브리프를 저장하지 못했어요.');
      return null;
    }
  });
}

function handleActionError(error, fallback) {
  if (error.message === 'UNAUTHORIZED' || error.message === 'NO_TOKEN') {
    showGate('세션이 만료됐어요. 다시 로그인해주세요.');
    return;
  }
  if (error.message === 'FORBIDDEN') {
    showGate('관리자 권한이 필요해요.');
    return;
  }
  toast(error.message || fallback, 'error', 5000);
}

function isCreativeBrief(value) {
  return Boolean(value && typeof value === 'object' && creativeId(value) != null
    && typeof value.campaign_key === 'string' && typeof value.hook === 'string');
}

async function postAction(action, options = {}) {
  let current = state.selected;
  if (!current) return;
  if (state.dirty) {
    current = await saveCreative({ quiet: true });
    if (!current) return;
  }
  const id = creativeId(current);
  if (id == null) return;
  if (options.confirm && !window.confirm(options.confirm)) return;

  await withBusy(async () => {
    try {
      const init = { method: 'POST' };
      if (options.body) init.body = JSON.stringify(options.body);
      const data = await api(`/admin/creatives/${encodeURIComponent(id)}/${action}`, init);
      const creative = unwrapCreative(data);
      if (isCreativeBrief(creative)) state.selected = creative;
      await loadCreatives(id, isCreativeBrief(creative) ? creative : null);
      toast(options.success || '처리했어요.', 'success');
    } catch (error) {
      handleActionError(error, options.failure || '처리하지 못했어요.');
    }
  });
}

async function approveCreative() {
  const status = normalizedStatus(state.selected && state.selected.status);
  const isReview = status === 'REVIEW_REQUIRED';
  await postAction('approve', {
    body: isReview ? {
      note: value('approval-note') || null,
      override_reason: value('approval-override') || null,
    } : {},
    confirm: isReview
      ? '실제 UI, 한글·숫자, 개인정보 마스킹을 확인했나요? 결과물을 승인할까요?'
      : '이 브리프를 승인할까요? 승인 뒤 Higgsfield 생성 대기열에 넣을 수 있어요.',
    success: isReview ? '결과물을 승인했어요.' : '브리프를 승인했어요.',
  });
}

async function queueCreative() {
  await postAction('queue', {
    confirm: '인증된 운영자 Mac의 로컬 runner에서 생성할까요?',
    success: '생성 대기열에 넣었어요.',
  });
}

async function publishCreative() {
  await postAction('mark-published', {
    body: {},
    confirm: '외부 채널 게시와 URL 확인을 마쳤나요? 게시 완료로 표시할까요?',
    success: '게시 완료로 표시했어요.',
  });
}

async function submitChanges() {
  const reason = value('review-note');
  if (!reason) {
    el('review-note').focus();
    toast('변경 이유를 입력해주세요.', 'error');
    return;
  }
  await postAction('request-changes', {
    body: { reason },
    success: '변경 요청을 남겼어요. 새 시도로 다시 생성할 수 있어요.',
  });
  el('review-note').value = '';
  el('review-panel').classList.add('hidden');
}

function limitedJson(value, limit = 10000) {
  const formatted = prettyJson(value);
  return formatted.length > limit ? formatted.slice(0, limit) + '\n…(이후 내용 생략)' : formatted;
}

function renderOutput(output) {
  const card = document.createElement('article');
  card.className = 'output-card';
  const preview = document.createElement('div');
  preview.className = 'output-preview';
  const kind = String(output.kind || 'output');
  const mime = String(output.mime_type || output.mime || '').toLowerCase();
  const isVideo = mime.startsWith('video/') || kind === 'mp4';
  const isImage = mime.startsWith('image/')
    || ['original', 'final_png', 'webp', 'poster', 'thumbnail'].includes(kind);
  preview.textContent = (isVideo || isImage) ? '인증된 미리보기를 불러오는 중이에요.'
    : (kind === 'virality_report' ? 'Virality 분석 리포트' : '미리보기를 제공하지 않는 파일이에요.');

  const body = document.createElement('div');
  body.className = 'output-body';
  const kindBadge = document.createElement('span');
  kindBadge.className = 'output-kind';
  kindBadge.textContent = kind + (output.is_primary ? ' · 대표' : '');
  const meta = document.createElement('p');
  const dimensions = output.width && output.height ? `${output.width}×${output.height}` : '';
  const duration = output.duration_seconds != null
    ? `${output.duration_seconds}초`
    : (output.duration_ms != null ? `${(Number(output.duration_ms) / 1000).toFixed(1)}초` : '');
  meta.textContent = [output.mime_type || output.mime, dimensions, duration, formatBytes(output.size_bytes)]
    .filter(Boolean).join(' · ') || '세부 정보 없음';
  body.append(kindBadge, meta);

  if (output.sha256) {
    const hash = document.createElement('p');
    hash.textContent = `SHA-256 ${compactText(output.sha256, 24)}`;
    body.appendChild(hash);
  }

  const reviews = [
    ['사람 검수', output.review_json],
    ['Virality', output.virality_json],
  ].filter((entry) => entry[1]);
  for (const [reviewLabel, reviewData] of reviews) {
    const review = document.createElement('div');
    review.className = 'review-summary';
    review.textContent = `${reviewLabel}\n${limitedJson(reviewData, 4000)}`;
    body.appendChild(review);
  }

  const actions = document.createElement('div');
  actions.className = 'output-actions';
  const open = document.createElement('a');
  open.className = 'btn btn-outline';
  open.setAttribute('aria-disabled', 'true');
  open.textContent = '인증 확인 중…';
  actions.appendChild(open);
  body.appendChild(actions);
  card.append(preview, body);

  if (output.id != null) {
    authenticatedAssetUrl(output.id).then((url) => {
      if (!card.isConnected) {
        URL.revokeObjectURL(url);
        assetObjectUrls.delete(url);
        return;
      }
      if (isVideo) {
        const video = document.createElement('video');
        video.src = url;
        video.controls = true;
        video.preload = 'metadata';
        preview.replaceChildren(video);
      } else if (isImage) {
        const image = document.createElement('img');
        image.src = url;
        image.alt = `${kind} 결과물 미리보기`;
        image.loading = 'lazy';
        preview.replaceChildren(image);
      }
      open.href = url;
      open.target = '_blank';
      open.rel = 'noopener noreferrer';
      open.removeAttribute('aria-disabled');
      open.textContent = '원본 열기 ↗';
    }).catch((error) => {
      preview.textContent = error.message === 'UNAUTHORIZED'
        ? '세션이 만료되어 미리보기를 불러오지 못했어요.'
        : '미리보기를 불러오지 못했어요.';
      open.textContent = '원본을 열 수 없어요';
    });
  } else {
    preview.textContent = '자산 식별자가 없어 미리보기를 불러올 수 없어요.';
    open.textContent = '원본을 열 수 없어요';
  }
  return card;
}

function renderAttempt(attempt, fallbackNumber) {
  const article = document.createElement('article');
  article.className = 'attempt';
  const head = document.createElement('div');
  head.className = 'attempt-head';
  const left = document.createElement('div');
  const title = document.createElement('div');
  title.className = 'attempt-title';
  const heading = document.createElement('h3');
  heading.textContent = `시도 #${attempt.attempt_no || fallbackNumber}`;
  const badge = document.createElement('span');
  const [label, className] = statusMeta(attempt.status);
  badge.className = `attempt-status ${className}`;
  badge.textContent = label;
  title.append(heading, badge);

  const meta = document.createElement('p');
  meta.className = 'attempt-meta';
  meta.textContent = [
    attempt.job_type,
    attempt.cli_version && `CLI ${attempt.cli_version}`,
    attempt.runner_id && `runner ${attempt.runner_id}`,
    formatDate(attempt.started_at || attempt.created_at),
  ].filter(Boolean).join(' · ');
  left.append(title, meta);
  head.appendChild(left);
  article.appendChild(head);

  const error = attempt.error_message || attempt.error || attempt.failure_reason;
  if (error) {
    const errorBox = document.createElement('div');
    errorBox.className = 'attempt-error';
    errorBox.textContent = compactText(error, 3000);
    article.appendChild(errorBox);
  }

  const technical = {
    higgsfield_job_id: attempt.higgsfield_job_id || null,
    lease_expires_at: attempt.lease_expires_at || null,
    prompt: attempt.prompt || null,
    params: attempt.params_json || null,
    input_files: attempt.input_files_json || null,
    input_hash: attempt.input_hash || attempt.inputs_hash || null,
    started_at: attempt.started_at || null,
    completed_at: attempt.completed_at || null,
  };
  if (Object.values(technical).some((item) => item != null && item !== '')) {
    const details = document.createElement('details');
    details.className = 'attempt-detail';
    const summary = document.createElement('summary');
    summary.textContent = '생성 요청 상세 보기';
    const pre = document.createElement('pre');
    pre.textContent = limitedJson(technical);
    details.append(summary, pre);
    article.appendChild(details);
  }

  const outputs = Array.isArray(attempt.outputs) ? attempt.outputs : [];
  if (outputs.length) {
    const grid = document.createElement('div');
    grid.className = 'outputs-grid';
    for (const output of outputs) grid.appendChild(renderOutput(output));
    article.appendChild(grid);
  }
  return article;
}

function renderAttempts(attempts) {
  const container = el('attempts');
  releaseAssetObjectUrls();
  container.replaceChildren();
  if (!Array.isArray(attempts) || !attempts.length) {
    const empty = document.createElement('div');
    empty.className = 'list-state';
    empty.textContent = '아직 생성 시도가 없어요. 브리프를 승인한 뒤 대기열에 넣어주세요.';
    container.appendChild(empty);
    return;
  }
  const ordered = attempts.slice().sort((a, b) => Number(b.attempt_no || 0) - Number(a.attempt_no || 0));
  ordered.forEach((attempt, index) => container.appendChild(renderAttempt(attempt, ordered.length - index)));
}

async function selectCreative(id, options = {}) {
  if (state.busy && !options.force) {
    toast('진행 중인 작업이 끝난 뒤 다른 브리프로 이동해주세요.', 'info');
    return;
  }
  if (state.dirty && !options.force && !window.confirm('저장하지 않은 변경이 있어요. 다른 브리프로 이동할까요?')) return;
  const sequence = ++state.selectSequence;
  try {
    const [data, storedInputs] = await Promise.all([
      api(`/admin/creatives/${encodeURIComponent(id)}`),
      api(`/admin/creatives/${encodeURIComponent(id)}/inputs`),
    ]);
    if (sequence !== state.selectSequence) return;
    const creative = unwrapCreative(data);
    if (!creative || creativeId(creative) == null) throw new Error('브리프 응답을 읽지 못했어요.');
    state.storedInputs = Array.isArray(storedInputs) ? storedInputs : [];
    fillForm(creative);
    showEditor();
    history.replaceState(null, '', `/admin-creatives?creative_id=${encodeURIComponent(creativeId(creative))}`);
  } catch (error) {
    if (sequence !== state.selectSequence) return;
    handleActionError(error, '브리프를 불러오지 못했어요.');
  }
}

async function loadCreatives(preferredId, fallbackCreative) {
  const sequence = ++state.loadSequence;
  const list = el('creative-list');
  if (!state.items.length) {
    list.replaceChildren();
    const loading = document.createElement('div');
    loading.className = 'list-state';
    loading.textContent = '불러오는 중이에요.';
    list.appendChild(loading);
  }
  try {
    const data = await api('/admin/creatives');
    if (sequence !== state.loadSequence) return;
    state.items = unwrapItems(data);
    renderList();
    const id = preferredId ?? creativeId(state.selected);
    if (id != null) {
      const inList = state.items.find((item) => String(creativeId(item)) === String(id));
      if (fallbackCreative) fillForm({ ...(inList || {}), ...fallbackCreative });
      await selectCreative(id, { force: true });
    }
  } catch (error) {
    if (sequence !== state.loadSequence) return;
    handleActionError(error, '목록을 불러오지 못했어요.');
    list.replaceChildren();
    const failed = document.createElement('div');
    failed.className = 'list-state';
    failed.textContent = error.message || '목록을 불러오지 못했어요.';
    list.appendChild(failed);
  }
}

function showSourceNotice(message, isError = false) {
  const notice = el('source-notice');
  notice.textContent = message;
  notice.classList.remove('hidden');
  notice.classList.toggle('error', isError);
}

async function createFromBlog(postId) {
  if (!/^\d+$/.test(String(postId))) {
    showSourceNotice('블로그 글 ID가 올바르지 않아요. 블로그 관리에서 다시 열어주세요.', true);
    return false;
  }
  showSourceNotice(`블로그 글 #${postId}의 정본으로 브리프를 준비하고 있어요.`);
  try {
    const data = await api(`/admin/creatives/from-blog/${encodeURIComponent(postId)}`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    const creative = unwrapCreative(data);
    const id = creativeId(creative);
    if (id == null) throw new Error('생성 응답에 creative_id가 없어요.');
    showSourceNotice(`블로그 글 #${postId}에서 브리프를 만들었어요. 메시지와 생성 설정을 확인해주세요.`);
    history.replaceState(null, '', `/admin-creatives?creative_id=${encodeURIComponent(id)}`);
    await loadCreatives(id, creative);
    toast('블로그 정본으로 브리프를 준비했어요.', 'success');
    return true;
  } catch (error) {
    showSourceNotice(error.message || '블로그 정본을 불러오지 못했어요.', true);
    handleActionError(error, '블로그 정본을 불러오지 못했어요.');
    return false;
  }
}

function bindEvents() {
  el('btn-new').addEventListener('click', newCreative);
  el('btn-empty-new').addEventListener('click', newCreative);
  el('btn-reload').addEventListener('click', () => {
    if (state.busy) {
      toast('진행 중인 작업이 끝난 뒤 새로고침해주세요.', 'info');
      return;
    }
    if (state.dirty && !window.confirm('저장하지 않은 변경을 버리고 새로고침할까요?')) return;
    loadCreatives(creativeId(state.selected));
  });
  el('btn-save').addEventListener('click', () => saveCreative());
  el('btn-approve').addEventListener('click', approveCreative);
  el('btn-review-approve').addEventListener('click', approveCreative);
  el('btn-queue').addEventListener('click', queueCreative);
  el('btn-publish').addEventListener('click', publishCreative);
  el('btn-input-upload').addEventListener('click', uploadCreativeInput);
  el('f-input-role').addEventListener('change', updateInputAccept);
  el('btn-request-changes').addEventListener('click', () => {
    el('review-panel').classList.remove('hidden');
    el('review-note').focus();
  });
  el('btn-close-review').addEventListener('click', () => el('review-panel').classList.add('hidden'));
  el('btn-submit-changes').addEventListener('click', submitChanges);
  el('filter-status').addEventListener('change', renderList);
  el('filter-search').addEventListener('input', renderList);
  el('creative-list').addEventListener('click', (event) => {
    const item = event.target.closest('[data-creative-id]');
    if (item) selectCreative(item.dataset.creativeId);
  });
  el('creative-form').addEventListener('submit', (event) => {
    event.preventDefault();
    saveCreative();
  });
  el('creative-form').addEventListener('input', () => setDirty(true));
  window.addEventListener('beforeunload', (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
}

async function init() {
  bindEvents();
  updateInputAccept();
  const me = await guard();
  if (!me) return;

  const params = new URLSearchParams(location.search);
  const blogId = params.get('blog_id');
  const id = params.get('creative_id');
  if (blogId) {
    const created = await createFromBlog(blogId);
    if (!created) await loadCreatives();
    return;
  }
  await loadCreatives(id || undefined);
}

init();
