"""Hermetic tests exercise the strict engine, replacing only model inference."""

import threading
from types import SimpleNamespace

import pytest

from services.translation import strict_text


class Tensor:
    def __init__(self, values):
        self.values = values
        self.shape = (1, len(values[0]))

    def to(self, _device):
        return self

    def tolist(self):
        return self.values


class Tokenizer:
    model_max_length = 64
    eos_token_id = 2
    pad_token_id = 0

    def __call__(self, text, **kwargs):
        assert kwargs.get("truncation") is False
        ids = [101] + [ord(c) + 200 for c in text] + [2]
        return {"input_ids": Tensor([ids])}

    def get_lang_id(self, lang):
        return {"en": 10, "de": 11}[lang]

    def batch_decode(self, outputs, **kwargs):
        return ["".join(chr(i - 200) for i in outputs.tolist()[0] if i >= 200)]


class Model:
    config = SimpleNamespace(max_position_embeddings=64, eos_token_id=2)
    generation_config = SimpleNamespace(eos_token_id=2, forced_eos_token_id=None)

    def __init__(self, cap_above=None, always_cap=False):
        self.calls = []
        self.cap_above = cap_above
        self.always_cap = always_cap

    def generate(self, input_ids, **kwargs):
        ids = input_ids.tolist()[0][1:-1]
        self.calls.append((ids, kwargs))
        if self.always_cap or self.cap_above is not None and len(ids) > self.cap_above:
            return Tensor([[2, 10] + [ord("x") + 200] * (kwargs["max_new_tokens"] - 1)])
        return Tensor([[2, 10] + ids + [2]])


def engine(model=None, **limits):
    return strict_text.StrictTextEngine(
        Tokenizer(),
        model or Model(),
        threading.Lock(),
        "cpu",
        strict_text.StrictLimits(input_tokens=10, output_tokens=32, **limits),
    )


def test_segmentation_counts_special_tokens_preserves_paragraphs_and_unbroken_unicode():
    worker = engine()
    plan = worker.plan(["  Hello. World!\r\n\r\n漢字仮名交じり文です。  "], "de")
    assert (
        "".join(piece.text for piece in plan[0])
        == "  Hello. World!\r\n\r\n漢字仮名交じり文です。  "
    )
    assert all(len(piece.text) + 2 <= 10 for piece in plan[0] if piece.translate)
    assert any(piece.text == "\r\n\r\n" and not piece.translate for piece in plan[0])


def test_preflight_work_limit_rejects_before_inference():
    model = Model()
    worker = engine(model, max_segments=2)
    with pytest.raises(strict_text.StrictTextError) as raised:
        worker.plan(["abcdefghijklmnopqrstuvwxyz"], "de")
    assert raised.value.code == "WORK_LIMIT_EXCEEDED"
    assert raised.value.limits == {"max_segments": 2, "input_tokens": 10}
    assert model.calls == []


@pytest.mark.asyncio
async def test_capped_generation_subdivides_under_one_request_budget():
    model = Model(cap_above=4)
    worker = engine(model)
    output = await strict_text.translate_plan(worker, ["abcdefgh"], "de", "en", lambda fn: _run(fn))
    assert output == ["abcdefgh"]
    assert len(model.calls) == 3


async def _run(fn):
    return fn()


@pytest.mark.asyncio
async def test_retries_exhaust_request_budget_without_returning_partial_text():
    worker = engine(Model(always_cap=True), max_attempts=2)
    with pytest.raises(strict_text.StrictTextError) as raised:
        await strict_text.translate_plan(worker, ["abcdefgh"], "de", "en", lambda fn: _run(fn))
    assert raised.value.code == "INCOMPLETE_TRANSLATION"


def test_decoder_capacity_accounts_for_start_token_and_forced_eos_is_disabled():
    model = Model()
    model.config = SimpleNamespace(max_position_embeddings=12, eos_token_id=2)
    worker = engine(model)
    assert worker.generate("abc", "de", "en") == "abc"
    assert model.calls[0][1]["max_new_tokens"] == 11
    assert model.calls[0][1]["forced_eos_token_id"] is None


def test_decoder_start_eos_is_not_mistaken_for_completed_generation():
    worker = engine(Model(always_cap=True))
    with pytest.raises(strict_text.IncompleteGeneration):
        worker.generate("abc", "de", "en")


def test_tokens_after_eos_are_not_treated_as_a_complete_translation():
    class MalformedModel(Model):
        def generate(self, **kwargs):
            return Tensor([[2, 10, 299, 2, 300]])

    worker = engine(MalformedModel())
    with pytest.raises(strict_text.IncompleteGeneration):
        worker.generate("abc", "de", "en")


@pytest.mark.asyncio
async def test_output_budget_is_preflighted_before_any_inference():
    model = Model()
    worker = engine(model, total_output_tokens=32)
    with pytest.raises(strict_text.StrictTextError) as raised:
        await strict_text.translate_plan(
            worker, ["abcdefgh", "ijklmnop"], "de", "en", lambda fn: _run(fn)
        )
    assert raised.value.code == "WORK_LIMIT_EXCEEDED"
    assert model.calls == []


@pytest.mark.asyncio
async def test_activity_is_rechecked_at_worker_dispatch_after_offload_delay():
    import asyncio

    busy = False

    async def activity(_remaining):
        return busy

    class DelayedAdmission:
        in_flight = 0

        async def run(self, fn):
            nonlocal busy
            # Simulate a worker-pool delay during which ASR becomes active.
            busy = True
            return await asyncio.to_thread(fn)

    model = Model()
    executor = strict_text.StrictTextExecutor()
    try:
        with pytest.raises(strict_text.StrictTextError) as raised:
            await executor.run(
                engine(model), ["Hello"], "de", "en", 0.03, DelayedAdmission(), activity, lambda: 0
            )
        assert raised.value.code == "SYSTEM_BUSY"
        assert model.calls == []
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_known_busy_state_is_retained_while_next_activity_poll_is_pending():
    import asyncio

    from services.translation.app import TranslationAdmission

    executor = strict_text.StrictTextExecutor()
    calls = 0

    async def activity(remaining):
        nonlocal calls
        calls += 1
        if calls == 1:
            return True
        await asyncio.Event().wait()

    try:
        with pytest.raises(strict_text.StrictTextError) as raised:
            await executor.run(
                engine(), ["hello"], "de", "en", 0.08, TranslationAdmission(), activity, lambda: 0
            )
        assert raised.value.status == 503
        assert raised.value.code == "SYSTEM_BUSY"
    finally:
        for task in list(executor.tasks):
            task.cancel()
        await executor.close()
