"""
관리자 API 공통 헬퍼
=====================
페이지네이션·정렬·필터 파싱 등 admin sub-router 들이 재사용.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import asc, desc
from sqlalchemy.orm import Query


def paginate(query: Query, page: int, size: int, sort_field, default_sort: str = "desc") -> dict:
    """ORM Query 에 정렬·offset·limit 적용 + 총 건수 포함 응답 dict.

    Args:
        query: SQLAlchemy Query (이미 필터까지 적용된 상태)
        page: 1-based 페이지 번호
        size: 페이지 크기
        sort_field: 정렬 기준 InstrumentedAttribute (예: User.id)
        default_sort: "asc" | "desc"

    Returns:
        { "items": [...], "total": N, "page": p, "size": s, "total_pages": N }
        items 는 raw ORM row 들. 호출자가 dict 변환 책임.
    """
    total = query.order_by(None).count()
    order_fn = desc if default_sort == "desc" else asc
    items = query.order_by(order_fn(sort_field)).offset((page - 1) * size).limit(size).all()
    total_pages = (total + size - 1) // size if size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": total_pages,
    }


def parse_sort(sort: Optional[str], allowed: dict, default_attr, default_dir: str = "desc"):
    """`-confirmed_at` 같은 정렬 query 를 ORM InstrumentedAttribute 로 변환.

    Args:
        sort: query string ("name" / "-created_at" / "amount" 등). None 이면 default.
        allowed: { "field_name": ORM_attr } 매핑 — 허용 목록 (보안: 임의 컬럼 정렬 차단)
        default_attr: 기본 정렬 ORM attribute
        default_dir: "asc" | "desc"

    Returns:
        (orm_attribute, direction_str) — direction 은 paginate 에 전달
    """
    if not sort:
        return default_attr, default_dir
    direction = "desc" if sort.startswith("-") else "asc"
    field_name = sort.lstrip("-+ ")
    return allowed.get(field_name, default_attr), direction
