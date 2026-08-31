from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from functools import wraps
from typing import Any, AsyncIterable, Awaitable, Callable, Coroutine, Iterable, TypeVar

from typing_extensions import ParamSpec

T = TypeVar("T")
BASE_URL = "https://catalog.he.u-tokyo.ac.jp/"


class Semester(Enum):
    A1 = "A1"
    A2 = "A2"
    S1 = "S1"
    S2 = "S2"
    W = "W"


class Weekday(IntEnum):
    Mon = 0
    Tue = 1
    Wed = 2
    Thu = 3
    Fri = 4
    Sat = 5
    Sun = 6


class Language(Enum):
    """Language of a course."""

    Japanese = "ja"
    English = "en"
    JapaneseAndEnglish = "ja,en"
    OtherLanguagesToo = "other"
    OnlyOtherLanguages = "only_other"
    Others = "others"


WrappedFnResult = TypeVar("WrappedFnResult")
WrappedFnParam = ParamSpec("WrappedFnParam")
WrappedFn = Callable[WrappedFnParam, WrappedFnResult]
WrappedAwaitableFn = Callable[WrappedFnParam, Awaitable[WrappedFnResult]]


class RateLimitter:
    _min_interval: timedelta
    _last_called: datetime

    def __init__(self, min_interval: timedelta | int):
        """Rate limitter.

        Parameters
        ----------
        min_interval : Union[timedelta, int]
            Minimum interval between calls. If int, it is treated as seconds.
        """
        if isinstance(min_interval, int):
            min_interval = timedelta(seconds=min_interval)
        self.min_interval = min_interval
        self._last_called = datetime.min

    @property
    def last_called(self) -> datetime:
        return self._last_called

    @property
    def next_call(self) -> datetime:
        return self.last_called + self.min_interval

    @property
    def callable(self) -> bool:
        return datetime.now() >= self.next_call

    @property
    def min_interval(self) -> timedelta:
        return self._min_interval

    @min_interval.setter
    def min_interval(self, value: timedelta) -> None:
        if value < timedelta(0):
            raise ValueError("min_interval must be positive")
        self._min_interval = value

    async def wait(self) -> None:
        while not self.callable:
            await asyncio.sleep((self.next_call - datetime.now()).total_seconds())
        self._last_called = datetime.now()

    def wraps(
        self,
        func: (
            WrappedFn[WrappedFnParam, WrappedFnResult]
            | WrappedAwaitableFn[WrappedFnParam, WrappedFnResult]
        ),
    ) -> WrappedFn[WrappedFnParam, WrappedFnResult]:
        @wraps(func)
        async def wrapper(
            *args: WrappedFnParam.args, **kwargs: WrappedFnParam.kwargs
        ) -> WrappedFnResult:
            await self.wait()
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    async def __aenter__(self) -> RateLimitter:
        await self.wait()
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


def async_for_task(async_iterable: AsyncIterable[T]) -> Iterable[asyncio.Task[T]]:
    iterator = type(async_iterable).__aiter__(async_iterable)
    running = True
    while running:
        try:
            coro = type(iterator).__anext__(iterator)
            if asyncio.iscoroutine(coro):
                yield asyncio.create_task(coro)
        except StopAsyncIteration:
            running = False


def async_iterable_to_iterable(
    async_iterable: AsyncIterable[T],
) -> Iterable[Coroutine[None, None, T]]:
    iterator = type(async_iterable).__aiter__(async_iterable)
    running = True
    while running:
        try:
            coro = type(iterator).__anext__(iterator)
            if asyncio.iscoroutine(coro):
                yield coro
        except StopAsyncIteration:
            running = False
