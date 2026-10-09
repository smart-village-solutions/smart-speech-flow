"""A route whose 422 never echoes what was submitted.

FastAPI's default 422 copies each pydantic error whole, `input` included, and
for a missing field `input` is the entire request body. On the feedback routes
that published the free text whenever any other field was absent. Keeping only
`type`, `loc` and `msg` drops every value: `msg` is pydantic's fixed text, and
`loc` names fields, never answers, because `answers` is not validated by
pydantic at all.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


def _value_free(errors: Sequence[Any]) -> list[dict[str, Any]]:
    return [{"type": error["type"], "loc": error["loc"], "msg": error["msg"]} for error in errors]


class ValueFreeValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def value_free(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise RequestValidationError(_value_free(error.errors())) from None

        return value_free
