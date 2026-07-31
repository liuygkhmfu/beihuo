#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""封装 Openapi的 http请求"""
import aiohttp
import orjson
from typing import Optional
from resp_schema import ResponseResult


class HttpBase(object):

    def __init__(self, default_timeout=30):
        self.default_timeout = default_timeout

    async def request(self, method: str, req_url: str,
                      params: Optional[dict] = None,
                      json: Optional[dict] = None,
                      headers: Optional[dict] = None,
                      **kwargs) -> ResponseResult:
        timeout = kwargs.pop('timeout', self.default_timeout)
        # 需要保持与加密算法一致的请求数据传递
        data = orjson.dumps(json, option=orjson.OPT_SORT_KEYS) if json else None
        async with aiohttp.ClientSession() as aio_session:
            async with aio_session.request(method=method, url=req_url, params=params, data=data,
                                           timeout=timeout, headers=headers, **kwargs) as resp:
                if resp.status != 200:
                    raise ValueError(f"Response error, status code: {resp.status}, body: {await resp.text()}")
                resp_json = await resp.json()
                return ResponseResult(**resp_json)
