"""관리자 입력 업로드의 브리프 선택 경계 회귀 계약."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CREATIVES_JS = ROOT / "infra" / "nginx" / "html" / "admin" / "creatives.js"


def _function(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


def test_uploaded_manifest_cannot_be_inserted_into_a_new_selection():
    source = CREATIVES_JS.read_text(encoding="utf-8")
    upload = _function(
        source,
        "async function uploadCreativeInput()",
        "function setStatusNode",
    )

    assert "const uploadCreativeId = String(id);" in upload
    assert "const uploadSelectionSequence = state.selectSequence;" in upload
    guard = re.compile(
        r"uploadSelectionSequence === state\.selectSequence\s*"
        r"&& String\(creativeId\(state\.selected\)\) === uploadCreativeId"
    )
    assert len(guard.findall(upload)) == 2

    first_guard = upload.index("const selectionStillMatches")
    assert first_guard < upload.index("state.storedInputs =")
    assert first_guard < upload.index("insertInputManifest(uploadedAsset.manifest")
    assert "해당 브리프를 다시 열어 입력 목록에서 연결해주세요." in upload
    for forbidden_transition in (
        "saveCreative(",
        "approveCreative(",
        "queueCreative(",
        "publishCreative(",
        "/approve",
        "/queue",
        "/mark-published",
    ):
        assert forbidden_transition not in upload


def test_input_upload_busy_state_guards_brief_navigation():
    source = CREATIVES_JS.read_text(encoding="utf-8")
    actions = _function(source, "function renderActions()", "function collectForm()")
    select = _function(source, "async function selectCreative", "async function loadCreatives")
    create = _function(source, "function newCreative()", "function renderActions()")
    bindings = _function(source, "function bindEvents()", "async function init()")

    assert "button.disabled = state.busy;" in actions
    assert "['btn-new', 'btn-empty-new', 'btn-reload']" in actions
    assert "if (state.busy && !options.force)" in select
    assert "if (state.busy)" in create
    assert "state.selectSequence += 1;" in create
    reload_binding = bindings[bindings.index("el('btn-reload')") :]
    assert "if (state.busy)" in reload_binding
