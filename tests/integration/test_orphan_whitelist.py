"""孤儿清理的三重白名单（C3-B §4.4 / EX-13）。

① 路径防穿越（最优先，``E1011``）→ ② 名字形态（``E1008``）→
③ 不在已知批次集合（``E2002``）→ ④ 逐个 ``delete_with_retry``，
删不掉的留在 ``failed`` 里。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX
from tests.helpers.ingest_state import make_ingested_batch

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.repositories.database import Database


def _orphan_file(buffer_dir: Path, name: str) -> Path:
    target = buffer_dir / name
    target.write_text("orphan", encoding="utf-8")
    return target


def test_path_traversal_rejected_e1011(client: TestClient, paths) -> None:
    """名字想爬出缓冲区目录：最优先报 E1011，且目录外的目标文件不许被碰。"""
    outside = paths.data_dir / ("a" * 32 + ".csv")
    outside.write_text("precious", encoding="utf-8")

    response = client.post(
        f"{API_PREFIX}/staging/orphans/cleanup", json={"names": ["../" + outside.name]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "E1011"
    assert outside.is_file(), "目录外的文件必须原样还在"


def test_bad_name_format_rejected_e1008(client: TestClient, paths) -> None:
    _orphan_file(paths.buffer_dir, "short.txt")

    response = client.post(f"{API_PREFIX}/staging/orphans/cleanup", json={"names": ["short.txt"]})

    assert response.status_code == 422
    assert response.json()["code"] == "E1008"
    assert (paths.buffer_dir / "short.txt").is_file(), "验证阶段不删任何文件"


def test_name_of_known_batch_rejected_e2002(client: TestClient, db: Database, paths) -> None:
    stored_name = "abcdef0123456789abcdef0123456789" + ".csv"
    _orphan_file(paths.buffer_dir, stored_name)
    with db.conn:
        make_ingested_batch(
            db.conn,
            batch_id="b" * 32,
            stored_name=stored_name,
            file_name="某批次.csv",
            pending_delete_flag=1,
        )

    response = client.post(
        f"{API_PREFIX}/staging/orphans/cleanup", json={"names": [stored_name]}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "E2002"
    assert (paths.buffer_dir / stored_name).is_file(), "被批次引用的文件不能当孤儿删"


def test_legal_orphan_is_removed(client: TestClient, paths) -> None:
    name = "0" * 32 + ".csv"
    _orphan_file(paths.buffer_dir, name)

    response = client.post(f"{API_PREFIX}/staging/orphans/cleanup", json={"names": [name]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["removed"] == [name]
    assert data["failed"] == []
    assert not (paths.buffer_dir / name).exists()


def test_failed_delete_stays_in_failed_list(
    client: TestClient, paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """删不掉的**不从清单里移除** —— 留在 failed 里等用户下次再试。"""
    name = "1" * 32 + ".csv"
    _orphan_file(paths.buffer_dir, name)
    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    response = client.post(f"{API_PREFIX}/staging/orphans/cleanup", json={"names": [name]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["removed"] == []
    assert data["failed"] == [{"name": name, "code": "E4003"}]
    assert (paths.buffer_dir / name).is_file()


def test_empty_names_rejected(client: TestClient) -> None:
    response = client.post(f"{API_PREFIX}/staging/orphans/cleanup", json={"names": []})

    assert response.status_code == 422
    assert response.json()["code"] in {"E1008", "E1010"}
