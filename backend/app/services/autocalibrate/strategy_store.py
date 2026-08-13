"""
자가보정 전략 파라미터 버전 관리 저장소
========================================
정적 BID_STRATEGY 딕셔너리를 대체. 입찰가 산정 파라미터를
버전 관리되는 동적 저장소로 보관한다.

- active.json          : 현재 운영 중인 파라미터 버전 1개
- versions/{id}.json   : 모든 후보·채택·거부 버전 (append-only, 영구 보존)
- history.jsonl        : 후보 평가·거부 이벤트 로그

calculator.py 는 이 저장소에서 active 파라미터를 동적 조회한다.
strategy_store 는 calculator 를 import 하지 않는다 (단방향 의존).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# backend/app/services/autocalibrate/strategy_store.py → backend/data/strategy
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STRATEGY_DIR = _BACKEND_DIR / "data" / "strategy"

BOOTSTRAP_VERSION_ID = "v0_bootstrap"


class PromotionAuthorizationError(ValueError):
    """승격 gate 또는 사람 승인 증적이 없는 active 변경 시도."""


@dataclass
class StrategyVersion:
    """전략 파라미터 한 버전 + 메타데이터."""

    version_id: str
    created_at: str
    params: dict  # {method: {bracket: [adjustment, margin]}}
    status: str = "active"  # active | archived | candidate | rejected
    parent_version: Optional[str] = None
    data_fingerprint: Optional[str] = None
    data_manifest_hash: Optional[str] = None
    year_weights: Optional[dict] = None
    metrics: Optional[dict] = None
    notes: str = ""
    gate_decision: Optional[str] = None
    approval_id: Optional[str] = None
    candidate_id: Optional[str] = None
    gate_decision_id: Optional[str] = None
    code_sha: Optional[str] = None
    route: Optional[str] = None
    parameters_hash: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyVersion":
        # 알 수 없는 키는 무시 (스키마 진화 대비)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def make_version_id(prefix: str = "v") -> str:
    """타임스탬프 + 랜덤 해시 기반 버전 ID."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = hashlib.sha1(str(datetime.now().timestamp()).encode()).hexdigest()[:6]
    return f"{prefix}{ts}_{rand}"


class StrategyStore(ABC):
    """전략 저장소 인터페이스. 향후 DbStrategyStore 로 승격 가능."""

    @abstractmethod
    def load_active(self) -> StrategyVersion: ...

    @abstractmethod
    def save_candidate(self, version: StrategyVersion) -> None: ...

    @abstractmethod
    def save_rejected(self, version: StrategyVersion) -> None: ...

    @abstractmethod
    def get(self, version_id: str) -> Optional[StrategyVersion]: ...

    @abstractmethod
    def list_versions(self) -> list[StrategyVersion]: ...


class FileStrategyStore(StrategyStore):
    """후보 전용 파일 저장소.

    이 구현은 부트스트랩 이후 ``active.json``을 변경하는 메서드를 의도적으로
    제공하지 않는다. 운영 승격은 별도 승인된 executor와 원자적 DB 경계가
    구현되기 전까지 fail-closed다.
    """

    def __init__(self, base_dir: Path = _STRATEGY_DIR):
        self.base = Path(base_dir)
        self.versions_dir = self.base / "versions"
        self.active_file = self.base / "active.json"
        self.history_file = self.base / "history.jsonl"
        self._thread_lock = threading.RLock()
        self.base.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(exist_ok=True)

    # ── 내부 유틸 ────────────────────────────────────────────
    def _version_path(self, version_id: str) -> Path:
        return self.versions_dir / f"{version_id}.json"

    def _write_json(self, path: Path, data: dict) -> None:
        """같은 디렉터리 임시파일을 fsync한 뒤 atomic replace한다."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    @contextmanager
    def _mutation_lock(self):
        """프로세스 내 + POSIX 프로세스 간 전략 변경 직렬화.

        운영은 Linux라 ``flock``이 프로세스 간 경쟁을 막는다. Windows 개발
        환경에서는 atomic replace와 프로세스 내 lock까지 적용된다.
        """
        with self._thread_lock:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - Windows 전용 경로
                fcntl = None
            lock_fd = None
            if fcntl is not None:
                # 디렉터리 자체를 잠가 런타임 lock 파일을 저장소에 남기지 않는다.
                lock_fd = os.open(self.base, os.O_RDONLY)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None and lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)

    def _log_event(self, event: str, version_id: str, detail: dict | None = None) -> None:
        entry = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "version_id": version_id,
        }
        if detail:
            entry["detail"] = detail
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ── 부트스트랩 ───────────────────────────────────────────
    def ensure_bootstrap(self, default_params: dict) -> None:
        """최초 1회: 현재 BID_STRATEGY 를 v0_bootstrap 으로 저장."""
        with self._mutation_lock():
            if self.active_file.exists():
                return
            version = StrategyVersion(
                version_id=BOOTSTRAP_VERSION_ID,
                created_at=datetime.now().isoformat(timespec="seconds"),
                params=_normalize_params(default_params),
                status="active",
                parent_version=None,
                notes="calculator.BID_STRATEGY 정적 딕셔너리 부트스트랩",
            )
            self._write_json(self._version_path(version.version_id), version.to_dict())
            self._write_json(self.active_file, version.to_dict())
            self._log_event("BOOTSTRAP", version.version_id)

    # ── 조회 ─────────────────────────────────────────────────
    def load_active(self) -> StrategyVersion:
        if not self.active_file.exists():
            raise FileNotFoundError(
                "active.json 이 없습니다. ensure_bootstrap() 을 먼저 호출하세요."
            )
        data = json.loads(self.active_file.read_text(encoding="utf-8"))
        return StrategyVersion.from_dict(data)

    def active_mtime(self) -> float:
        """active.json 의 수정 시각 (calculator 캐시 무효화용)."""
        return self.active_file.stat().st_mtime if self.active_file.exists() else 0.0

    def get(self, version_id: str) -> Optional[StrategyVersion]:
        path = self._version_path(version_id)
        if not path.exists():
            return None
        return StrategyVersion.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_versions(self) -> list[StrategyVersion]:
        out = []
        for path in sorted(self.versions_dir.glob("*.json")):
            out.append(
                StrategyVersion.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )
        return out

    # ── 변경 ─────────────────────────────────────────────────
    def save_candidate(self, version: StrategyVersion) -> None:
        """가드는 통과했지만 승격 승인이 없는 후보를 기록한다."""
        with self._mutation_lock():
            version.params = _normalize_params(version.params)
            version.status = "candidate"
            self._write_json(self._version_path(version.version_id), version.to_dict())
            self._log_event(
                "CANDIDATE_EVALUATED",
                version.version_id,
                {
                    "parent": version.parent_version,
                    "gate_decision": version.gate_decision,
                },
            )

    def save_rejected(self, version: StrategyVersion) -> None:
        """후보 거부 — 기록만 하고 active 는 불변 (= 자동 롤백)."""
        with self._mutation_lock():
            version.params = _normalize_params(version.params)
            version.status = "rejected"
            self._write_json(self._version_path(version.version_id), version.to_dict())
            self._log_event(
                "REJECTED",
                version.version_id,
                {"parent": version.parent_version, "notes": version.notes},
            )


def _normalize_params(params: dict) -> dict:
    """파라미터를 JSON 친화 형태로 정규화 (튜플 → 리스트)."""
    out: dict = {}
    for method, brackets in params.items():
        out[method] = {}
        for bracket, val in brackets.items():
            out[method][bracket] = [float(val[0]), float(val[1])]
    return out


def strategy_parameters_hash(params: dict) -> str:
    """전략 파라미터의 순서 독립 canonical SHA-256."""
    payload = json.dumps(
        _normalize_params(params),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# 모듈 레벨 싱글톤 (calculator 가 공유)
_default_store: Optional[FileStrategyStore] = None


def get_default_store() -> FileStrategyStore:
    global _default_store
    if _default_store is None:
        _default_store = FileStrategyStore()
    return _default_store
