"""Bounded, tokenizer-aware translation for the opt-in laboratory API.

This module never normalizes paragraphs, truncates input, or records text.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import torch


class StrictTextError(RuntimeError):
    def __init__(
        self, code: str, message: str, status: int = 502, *, limits: dict[str, int] | None = None
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.limits = limits


class IncompleteGeneration(RuntimeError):
    pass


@dataclass(frozen=True)
class StrictLimits:
    input_tokens: int = 256
    output_tokens: int = 256
    max_segments: int = 64
    max_attempts: int = 96
    max_depth: int = 8
    total_output_tokens: int = 8192


@dataclass(frozen=True)
class Piece:
    text: str
    translate: bool = True


def _ids(value: Any) -> list[int]:
    values = value.tolist()
    return values[0] if values and isinstance(values[0], list) else values


def _capacity(*values: Any) -> int:
    finite = [int(v) for v in values if isinstance(v, int) and 2 < v < 1_000_000]
    if not finite:
        raise StrictTextError("UNAVAILABLE", "Model context capacity unavailable", 503)
    return min(finite)


class StrictTextEngine:
    def __init__(self, tokenizer, model, tokenizer_lock, device, limits=StrictLimits()):
        self.tokenizer, self.model = tokenizer, model
        self.lock, self.device, self.limits = tokenizer_lock, device, limits
        config = model.config
        self.input_limit = min(
            limits.input_tokens,
            _capacity(
                getattr(config, "max_position_embeddings", None),
                getattr(config, "max_encoder_position_embeddings", None),
                getattr(tokenizer, "model_max_length", None),
            ),
        )
        self.output_limit = min(
            limits.output_tokens,
            _capacity(
                getattr(config, "max_position_embeddings", None),
                getattr(config, "max_decoder_position_embeddings", None),
            )
            - 1,
        )

    def _encode(self, text, source):
        # Source-language mutation and the complete encoding operation share the
        # legacy tokenizer lock; no strict call can change a legacy encoding.
        with self.lock:
            self.tokenizer.src_lang = source
            return self.tokenizer(text, return_tensors="pt", truncation=False)

    def _fits(self, text, source):
        return len(_ids(self._encode(text, source)["input_ids"])) <= self.input_limit

    def split(self, text):
        if len(text) < 2:
            raise StrictTextError("INCOMPLETE_TRANSLATION", "Translation cannot be completed")
        middle = len(text) // 2
        boundaries = [m.end() for m in re.finditer(r"\s+", text) if m.end() < len(text)]
        cut = min(boundaries, key=lambda n: abs(n - middle)) if boundaries else middle
        return text[:cut], text[cut:]

    def _fit_parts(self, text, source):
        if self._fits(text, source):
            return [text]
        if len(text) < 2:
            raise StrictTextError(
                "WORK_LIMIT_EXCEEDED",
                "Input cannot fit model context",
                413,
                limits={"input_tokens": self.input_limit},
            )
        left, right = self.split(text)
        return self._fit_parts(left, source) + self._fit_parts(right, source)

    def plan(self, texts, source):
        plan = []
        count = 0
        for text in texts:
            pieces = []
            for paragraph in re.split(r"((?:\r?\n[ \t]*)+)", text):
                if not paragraph:
                    continue
                if not paragraph.strip():
                    pieces.append(Piece(paragraph, False))
                    continue
                sentences = re.split(r"(?<=[.!?。？！])(?=\s|[^\x00-\x7f])", paragraph)
                packed = ""
                for sentence in sentences:
                    if packed and not self._fits(packed + sentence, source):
                        pieces.extend(Piece(p) for p in self._fit_parts(packed, source))
                        packed = ""
                    packed += sentence
                if packed:
                    pieces.extend(Piece(p) for p in self._fit_parts(packed, source))
            count += sum(piece.translate for piece in pieces)
            if count > self.limits.max_segments:
                raise StrictTextError(
                    "WORK_LIMIT_EXCEEDED",
                    "Input exceeds translation work budget",
                    413,
                    limits={
                        "max_segments": self.limits.max_segments,
                        "input_tokens": self.input_limit,
                    },
                )
            plan.append(pieces)
        return plan

    def generate(self, text, source, target):
        encoded = self._encode(text, source)
        if len(_ids(encoded["input_ids"])) > self.input_limit:
            raise StrictTextError(
                "WORK_LIMIT_EXCEEDED",
                "Input exceeds model context",
                413,
                limits={"input_tokens": self.input_limit},
            )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with self.lock:
            bos = self.tokenizer.get_lang_id(target)
        with torch.inference_mode():
            outputs = self.model.generate(
                **encoded,
                forced_bos_token_id=bos,
                max_new_tokens=self.output_limit,
                num_beams=5,
                early_stopping=True,
                forced_eos_token_id=None,
            )
        ids = _ids(outputs)
        config = getattr(self.model, "generation_config", None)
        eos = getattr(config, "eos_token_id", None)
        if eos is None:
            eos = getattr(self.model.config, "eos_token_id", None)
        if eos is None:
            eos = getattr(self.tokenizer, "eos_token_id", None)
        eos_ids = set(eos if isinstance(eos, (list, tuple)) else [eos]) - {None}
        # Encoder-decoder M2M100 starts with EOS. It is not a completion.
        generated = ids[1:]
        pad = getattr(self.tokenizer, "pad_token_id", None)
        terminal = next((token for token in reversed(generated) if token != pad), None)
        if terminal not in eos_ids or len(generated) > self.output_limit:
            raise IncompleteGeneration
        output = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
        if not isinstance(output, str) or not output.strip():
            raise IncompleteGeneration
        return output


async def translate_plan(
    engine: StrictTextEngine,
    texts: list[str],
    source: str,
    target: str,
    dispatch: Callable[[Callable[[], str]], Awaitable[str]],
) -> list[str]:
    plan = await asyncio.to_thread(engine.plan, texts, source)
    segments = sum(piece.translate for pieces in plan for piece in pieces)
    if (
        segments > engine.limits.max_attempts
        or segments * engine.output_limit > engine.limits.total_output_tokens
    ):
        raise StrictTextError(
            "WORK_LIMIT_EXCEEDED",
            "Input exceeds translation work budget",
            413,
            limits={
                "max_attempts": engine.limits.max_attempts,
                "total_output_tokens": engine.limits.total_output_tokens,
                "output_tokens": engine.output_limit,
            },
        )
    attempts = 0
    output_budget = 0

    async def translate_piece(text, depth=0):
        nonlocal attempts, segments, output_budget
        if (
            attempts >= engine.limits.max_attempts
            or output_budget + engine.output_limit > engine.limits.total_output_tokens
        ):
            raise StrictTextError("INCOMPLETE_TRANSLATION", "Translation work budget exhausted")
        attempts += 1
        output_budget += engine.output_limit
        # Preserve surrounding whitespace even when tokenizer decoding strips it.
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        content = text.strip()
        if not content:
            return text
        try:
            return (
                leading
                + await dispatch(lambda: engine.generate(content, source, target))
                + trailing
            )
        except IncompleteGeneration:
            if depth >= engine.limits.max_depth or segments + 2 > engine.limits.max_segments:
                raise StrictTextError(
                    "INCOMPLETE_TRANSLATION", "Translation cannot be completed"
                ) from None
            left, right = engine.split(text)
            segments += 2
            return await translate_piece(left, depth + 1) + await translate_piece(right, depth + 1)

    results = []
    for pieces in plan:
        translated = []
        for piece in pieces:
            translated.append(await translate_piece(piece.text) if piece.translate else piece.text)
        results.append("".join(translated))
    return results


class _StrictDispatch:
    def __init__(self, timeout, admission, activity, legacy_pending):
        self.stop = asyncio.Event()
        self.loop = asyncio.get_running_loop()
        self.deadline = self.loop.time() + timeout
        self.waiting = None
        self.admission, self.activity, self.legacy_pending = admission, activity, legacy_pending

    def expired(self):
        if self.waiting == "busy":
            return StrictTextError(
                "SYSTEM_BUSY", "Conversation processing has priority; retry later", 503
            )
        if self.waiting == "unknown":
            return StrictTextError(
                "UNAVAILABLE", "Conversation activity unavailable; retry later", 503
            )
        return StrictTextError("DEADLINE_EXCEEDED", "Translation deadline exceeded", 504)

    def _guard(self, fn):
        if self.stop.is_set() or self.loop.time() >= self.deadline:
            raise self.expired()
        if self.legacy_pending():
            self.waiting = "busy"
            raise _PriorityChanged
        # Thread-pool queueing may outlive the loop-side idle observation.
        # Keep HTTP on its owning loop and recheck at the actual dispatch point.
        remaining = self.deadline - self.loop.time()
        future = asyncio.run_coroutine_threadsafe(self.activity(remaining), self.loop)
        try:
            busy = future.result(timeout=remaining)
        except TimeoutError:
            future.cancel()
            self.waiting = "unknown"
            raise _PriorityChanged from None
        if busy is not False or self.legacy_pending():
            self.waiting = "busy" if busy is True or self.legacy_pending() else "unknown"
            raise _PriorityChanged
        if self.stop.is_set() or self.loop.time() >= self.deadline:
            raise self.expired()
        self.waiting = None
        return fn()

    async def __call__(self, fn):
        while True:
            remaining = self.deadline - self.loop.time()
            if self.stop.is_set() or remaining <= 0:
                raise self.expired()
            self.waiting = "unknown"
            busy = await self.activity(remaining)
            pending = self.legacy_pending() or self.admission.in_flight
            self.waiting = (
                "busy" if busy is True or pending else ("unknown" if busy is None else None)
            )
            if busy is False and not pending:
                # Recheck arrivals immediately before inference, after admission
                # acquisition has yielded to the loop.
                try:
                    return await self.admission.run(lambda: self._guard(fn))
                except _PriorityChanged:
                    pass
            await asyncio.sleep(min(0.02, max(0, self.deadline - self.loop.time())))


class StrictTextExecutor:
    """One ephemeral request; its slot outlives a cancelled HTTP waiter."""

    def __init__(self):
        self.active = False
        self.tasks: set[asyncio.Task] = set()

    async def run(
        self, engine, texts, source, target, timeout, admission, activity, legacy_pending
    ):
        if self.active:
            raise StrictTextError("SYSTEM_BUSY", "Background translation already active", 503)
        self.active = True
        dispatch = _StrictDispatch(timeout, admission, activity, legacy_pending)

        async def work():
            try:
                return await translate_plan(engine, texts, source, target, dispatch)
            finally:
                self.active = False

        task = asyncio.create_task(work())
        self.tasks.add(task)

        def finished(done):
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Consume errors after the HTTP waiter has left.

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            dispatch.stop.set()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise dispatch.expired() from None

    async def close(self):
        # Worker-backed requests retain ownership until they actually finish.
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


class _PriorityChanged(RuntimeError):
    pass
