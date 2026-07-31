#!/usr/bin/python3
from __future__ import annotations

from typing import Any

import pytest

import openapi
from openapi import OpenApiBase
from resp_schema import ResponseResult


class FakeHttpBase:
    response = ResponseResult(code=0, message="", data={})
    calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> ResponseResult:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


@pytest.fixture(autouse=True)
def fake_http(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeHttpBase.calls = []
    FakeHttpBase.response = ResponseResult(code=0, message="", data={})
    monkeypatch.setattr(openapi, "HttpBase", FakeHttpBase)


@pytest.mark.asyncio
async def test_generate_access_token() -> None:
    FakeHttpBase.response = ResponseResult(
        code=200,
        message="",
        data={
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        },
    )
    api = OpenApiBase("https://example.test", "app-id", "app-secret")

    result = await api.generate_access_token()

    assert result.access_token == "access"
    assert FakeHttpBase.calls == [
        {
            "method": "POST",
            "url": (
                "https://example.test"
                "/api/auth-server/oauth/access-token"
            ),
            "params": {
                "appId": "app-id",
                "appSecret": "app-secret",
            },
        }
    ]


@pytest.mark.asyncio
async def test_generate_access_token_rejects_error() -> None:
    FakeHttpBase.response = ResponseResult(
        code=401,
        message="invalid credentials",
        data={},
    )
    api = OpenApiBase("https://example.test", "app-id", "app-secret")

    with pytest.raises(ValueError, match="invalid credentials"):
        await api.generate_access_token()


@pytest.mark.asyncio
async def test_refresh_token() -> None:
    FakeHttpBase.response = ResponseResult(
        code=200,
        message="",
        data={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    api = OpenApiBase("https://example.test", "app-id", "app-secret")

    result = await api.refresh_token("old-refresh")

    assert result.refresh_token == "new-refresh"
    assert FakeHttpBase.calls[0]["params"] == {
        "appId": "app-id",
        "refreshToken": "old-refresh",
    }


@pytest.mark.asyncio
async def test_post_request_adds_signature_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openapi.SignBase,
        "generate_sign",
        staticmethod(lambda app_id, params: "signed-value"),
    )
    FakeHttpBase.response = ResponseResult(
        code=0,
        message="",
        data={"ok": True},
    )
    api = OpenApiBase(
        "https://example.test",
        "1234567890abcdef",
        "app-secret",
    )

    result = await api.request(
        "access-token",
        "/resource",
        "POST",
        req_params={"page": 1},
        req_body={"name": "demo"},
    )

    call = FakeHttpBase.calls[0]
    assert result.data == {"ok": True}
    assert call["url"] == "https://example.test/resource"
    assert call["json"] == {"name": "demo"}
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["params"]["page"] == 1
    assert call["params"]["app_key"] == "1234567890abcdef"
    assert call["params"]["access_token"] == "access-token"
    assert call["params"]["sign"] == "signed-value"
    assert call["params"]["timestamp"].isdigit()


@pytest.mark.asyncio
async def test_get_request_keeps_custom_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openapi.SignBase,
        "generate_sign",
        staticmethod(lambda app_id, params: "signed-value"),
    )
    api = OpenApiBase(
        "https://example.test",
        "1234567890abcdef",
        "app-secret",
    )

    await api.request(
        "access-token",
        "/resource",
        "GET",
        headers={"X-Test": "yes"},
    )

    call = FakeHttpBase.calls[0]
    assert call["headers"] == {"X-Test": "yes"}
    assert call["json"] is None
