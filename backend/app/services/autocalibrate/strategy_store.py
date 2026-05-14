"""
자가보정 전략 파라미터 버전 관리 저장소
========================================
정적 BID_STRATEGY 딕셔너리를 대체. 입찰가 산정 파라미터를
버전 관리되는 동적 저장소로 보관한다.

- active.json          : 현재 운영 중인 파라미터 버전 1개
- versions/{id}.json   : 모든 후보·채택·거부 버전 (append-only, 영구 보존)
- history.jsonl        : 버전 전이 로그 (채택/거부/롤백 이벤트)

calculator.py 는 이 저장소에서 active 파라미터를 동적 조회한다.
strategy_store 는 calculator 를 import 하지 않는다 (단방향 의존).
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# backend/app/services/autocalibrate/strategy_store.py → backend/data/strategy
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STRATEGY_DIR = _BACKEND_DIR / "data" / "strategy"

BOOTSTRAP_VERSION_ID = "v0_bootstrap"


@dataclass
class StrategyVersion:
    """전략 파라미터 한 버전 + 메타데이터."""

    version_id: str
    created_at: str
    params: dict  # {method: {bracket: [adjustment, margin]}}
    status: str = "active"  # active | archived | rejected
    parent_version: Optional[str] = None
    data_fingerprint: Optional[str] = None
    year_weights: Optional[dict] = None
    metrics: Optional[dict] = None
    notes: str = ""

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
    def commit(self, version: StrategyVersion) -> None: ...

    @abstractmethod
    def save_rejected(self, version: StrategyVersion) -> None: ...

    @abstractmethod
    def rollback(self, to_version_id: str) -> StrategyVersion: ...

    @abstractmethod
    def get(self, version_id: str) -> Optional[StrategyVersion]: ...

    @abstractmethod
    def list_versions(self) -> list[StrategyVersion]: ...


class FileStrategyStore(StrategyStore):
    """파일 기반 전략 저장소 (1단계 구현)."""

    def __init__(self, base_dir: Path = _STRATEGY_DIR):
        self.base = Path(base_dir)
        self.versions_dir = self.base / "versions"
        self.active_file = self.base / "active.json"
        self.history_file = self.base / "history.jsonl"
        self.base.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(exist_ok=True)

    # ── 내부 유틸 ────────────────────────────────────────────
    def _version_path(self, version_id: str) -> Path:
        return self.versions_dir / f"{version_id}.json"

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

    # ── 부트스트랩 ───────────────────────────────────────────
    def ensure_bootstrap(self, default_params: dict) -> None:
        """최초 1회: 현재 BID_STRATEGY 를 v0_bootstrap 으로 저장."""
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
    def commit(self, version: StrategyVersion) -> None:
        """후보를 active 로 채택. 이전 active 는 archived 로."""
        version.params = _normalize_params(version.params)
        version.status = "active"
        # 이전 active archived 처리
        if self.active_file.exists():
            prev = self.load_active()
            prev.status = "archived"
            self._write_json(self._version_path(prev.version_id), prev.to_dict())
        # 새 버전 저장
        self._write_json(self._version_path(version.version_id), version.to_dict())
        self._write_json(self.active_file, version.to_dict())
        self._log_event(
            "ADOPTED",
            version.version_id,
            {"parent": version.parent_version, "metrics": version.metrics},
        )

    def save_rejected(self, version: StrategyVersion) -> None:
        """후보 거부 — 기록만 하고 active 는 불변 (= 자동 롤백)."""
        version.params = _normalize_params(version.params)
        version.status = "rejected"
        self._write_json(self._version_path(version.version_id), version.to_dict())
        self._log_event(
            "REJECTED",
            version.version_id,
            {"parent": version.parent_version, "notes": version.notes},
        )

    def rollback(self, to_version_id: str) -> StrategyVersion:
        """과거 버전을 명시적으로 active 로 복원."""
        target = self.get(to_version_id)
        if target is None:
            raise ValueError(f"버전을 찾을 수 없습니다: {to_version_id}")
        if self.active_file.exists():
            prev = self.load_active()
            prev.status = "archived"
            self._write_json(self._version_path(prev.version_id), prev.to_dict())
        target.status = "active"
        self._write_json(self._version_path(target.version_id), target.to_dict())
        self._write_json(self.active_file, target.to_dict())
        self._log_event("ROLLBACK", target.version_id)
        return target


def _normalize_params(params: dict) -> dict:
    """파라미터를 JSON 친화 형태로 정규화 (튜플 → 리스트)."""
    out: dict = {}
    for method, brackets in params.items():
        out[method] = {}
        for bracket, val in brackets.items():
            out[method][bracket] = [float(val[0]), float(val[1])]
    return out


# 모듈 레벨 싱글톤 (calculator 가 공유)
_default_store: Optional[FileStrategyStore] = None


def get_default_store() -> FileStrategyStore:
    global _default_store
    if _default_store is None:
        _default_store = FileStrategyStore()
    return _default_store
