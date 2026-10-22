"""C2B.3 预览行数：默认 20；``limit=1000`` 被截到 50；预览只读。

截断而不是报错，是因为预览是只读操作 —— 前端滑杆滑到 1000 时给 50 行比给 422 有用。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.fakes.fake_parser import FakeParser, make_row, make_rows
from tests.integration.conftest import StagingFlow

from account_dashboard.limits import PREVIEW_DEFAULT_LIMIT, PREVIEW_MAX_LIMIT


def make_big_parser(parser: FakeParser) -> FakeParser:
    parser._rows = make_rows(60)  # noqa: SLF001
    return parser


def test_default_limit_is_twenty(api: TestClient, parser: FakeParser, flow: StagingFlow) -> None:
    make_big_parser(parser)
    batch = flow.upload_ok()

    payload = api.get(f"/api/v1/staging/batches/{batch['id']}/preview").json()["data"]

    assert len(payload["rows"]) == PREVIEW_DEFAULT_LIMIT
    assert payload["limit"] == PREVIEW_DEFAULT_LIMIT
    assert payload["total_rows"] == 60
    assert payload["truncated"] is True


def test_limit_is_capped_at_fifty(api: TestClient, parser: FakeParser, flow: StagingFlow) -> None:
    make_big_parser(parser)
    batch = flow.upload_ok()

    payload = api.get(
        f"/api/v1/staging/batches/{batch['id']}/preview", params={"limit": 1000}
    ).json()["data"]

    assert len(payload["rows"]) == PREVIEW_MAX_LIMIT
    assert payload["limit"] == PREVIEW_MAX_LIMIT


def test_small_limit_is_honoured(api: TestClient, parser: FakeParser, flow: StagingFlow) -> None:
    make_big_parser(parser)
    batch = flow.upload_ok()

    payload = api.get(f"/api/v1/staging/batches/{batch['id']}/preview", params={"limit": 3}).json()[
        "data"
    ]

    assert len(payload["rows"]) == 3
    assert [row["row_no"] for row in payload["rows"]] == [1, 2, 3]


def test_preview_keeps_status(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()
    before = flow.detail(batch["id"])["status"]

    api.get(f"/api/v1/staging/batches/{batch['id']}/preview")

    assert flow.detail(batch["id"])["status"] == before


def test_preview_exposes_headers_and_cells(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    payload = api.get(f"/api/v1/staging/batches/{batch['id']}/preview").json()["data"]

    assert payload["headers"] == ["交易时间", "金额", "收/支"]
    assert len(payload["rows"][0]["cells"]) == len(payload["headers"])
    assert payload["columns"] == 3
    assert payload["rows"][0]["valid"] is True


def test_preview_flags_invalid_rows(api: TestClient, parser: FakeParser, flow: StagingFlow) -> None:
    parser._rows = [  # noqa: SLF001
        make_rows(1)[0],
        make_row(2, occurred_at=None, amount_cents=None),
    ]
    batch = flow.upload_ok()

    payload = api.get(f"/api/v1/staging/batches/{batch['id']}/preview").json()["data"]

    second = payload["rows"][1]
    assert second["valid"] is False
    assert {issue["code"] for issue in second["issues"]} == {"TIME_PARSE", "AMOUNT_PARSE"}
