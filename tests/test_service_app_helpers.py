import importlib.util
import io
import os
import sys
import tempfile
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


class DummyMetric:
    def inc(self, *args, **kwargs):
        return None


class StubHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

    def set(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


class FakeDevice(str):
    @property
    def type(self):
        return self.split(":")[0]


def build_torch_stub(cuda_available: bool = False) -> types.ModuleType:
    torch_stub = types.ModuleType("torch")

    class FakeCuda:
        @staticmethod
        def is_available():
            return cuda_available

        @staticmethod
        def device_count():
            return 0

        @staticmethod
        def manual_seed(seed):
            return None

        @staticmethod
        def memory_allocated(device_idx):
            return 0

        @staticmethod
        def memory_reserved(device_idx):
            return 0

        @staticmethod
        def get_device_properties(device_idx):
            return SimpleNamespace(name="Fake GPU", total_memory=1024)

    torch_stub.cuda = FakeCuda()
    torch_stub.float16 = "float16"
    torch_stub.float32 = "float32"
    torch_stub.manual_seed = lambda seed: None
    torch_stub.device = lambda value: FakeDevice(value)
    return torch_stub


def build_transformers_stub() -> types.ModuleType:
    transformers_stub = types.ModuleType("transformers")

    class FakeInputs(dict):
        def to(self, device):
            return self

    class FakeTokenizer:
        lang_code_to_id = {"de": 0, "en": 1, "ar": 2}

        @classmethod
        def from_pretrained(cls, model_name):
            return cls()

        def __call__(self, text, return_tensors=None, truncation=None, max_length=None):
            return FakeInputs(input_ids=[[1, 2, 3]])

        def get_lang_id(self, lang):
            return self.lang_code_to_id[lang]

        def batch_decode(self, generated_tokens, skip_special_tokens=True):
            return ["decoded text"]

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_name, torch_dtype=None):
            return cls()

        def to(self, device):
            return self

        def eval(self):
            return None

        def generate(self, **kwargs):
            return [[1, 2, 3]]

    transformers_stub.M2M100Tokenizer = FakeTokenizer
    transformers_stub.M2M100ForConditionalGeneration = FakeModel
    transformers_stub.pipeline = lambda *args, **kwargs: (
        lambda text: {"audio": [0.1, 0.2], "sampling_rate": 16000}
    )
    return transformers_stub


def build_soundfile_stub() -> types.ModuleType:
    soundfile_stub = types.ModuleType("soundfile")

    def write(target, audio, sampling_rate, format="WAV"):
        payload = b"FAKE-WAV"
        if hasattr(target, "write"):
            target.write(payload)
            return None
        with open(target, "wb") as file_obj:
            file_obj.write(payload)
        return None

    soundfile_stub.write = write
    return soundfile_stub


def build_fastapi_stub() -> tuple[types.ModuleType, types.ModuleType]:
    fastapi_stub = types.ModuleType("fastapi")
    responses_stub = types.ModuleType("fastapi.responses")

    class Response:
        def __init__(self, content=None, media_type=None, headers=None, status_code=200):
            self.body = content if isinstance(content, bytes) else str(content).encode()
            self.media_type = media_type
            self.headers = {k.lower(): v for k, v in (headers or {}).items()}
            self.status_code = status_code

    class JSONResponse(Response):
        def __init__(self, content=None, status_code=200):
            import json

            super().__init__(
                content=json.dumps(content, separators=(",", ":")).encode(),
                media_type="application/json",
                headers={},
                status_code=status_code,
            )

    class FastAPI:
        def __init__(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            return lambda func: func

        def post(self, *args, **kwargs):
            return lambda func: func

    def _marker(*args, **kwargs):
        return {"args": args, "kwargs": kwargs}

    fastapi_stub.FastAPI = FastAPI
    fastapi_stub.File = _marker
    fastapi_stub.Form = _marker
    fastapi_stub.HTTPException = StubHTTPException
    fastapi_stub.Request = object
    fastapi_stub.UploadFile = object
    responses_stub.JSONResponse = JSONResponse
    responses_stub.Response = Response
    return fastapi_stub, responses_stub


def build_prometheus_stub() -> types.ModuleType:
    prometheus_stub = types.ModuleType("prometheus_client")
    prometheus_stub.Counter = lambda *args, **kwargs: DummyMetric()
    prometheus_stub.Gauge = lambda *args, **kwargs: DummyMetric()
    prometheus_stub.Histogram = lambda *args, **kwargs: DummyMetric()
    prometheus_stub.generate_latest = lambda: b"metrics"
    return prometheus_stub


def build_tts_stub() -> tuple[types.ModuleType, types.ModuleType]:
    tts_pkg = types.ModuleType("TTS")
    tts_api = types.ModuleType("TTS.api")

    class FakeTTS:
        def __init__(self, model_name):
            self.model_name = model_name
            self._device = "cpu"

        def to(self, device):
            self._device = device
            return self

        def parameters(self):
            return iter([SimpleNamespace(device=self._device)])

        def tts_to_file(self, text, file_path):
            with open(file_path, "wb") as file_obj:
                file_obj.write(b"COQUI-WAV")

    tts_api.TTS = FakeTTS
    tts_pkg.api = tts_api
    return tts_pkg, tts_api


def load_module(monkeypatch, module_name: str, relative_path: str, stubs: dict[str, object]):
    for stub_name, stub_module in stubs.items():
        monkeypatch.setitem(sys.modules, stub_name, stub_module)

    module_path = ROOT / relative_path
    unique_name = f"{module_name}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def build_request(payload=None, query_params=None, *, fail_json: bool = False):
    class FakeRequest:
        def __init__(self):
            self.query_params = query_params or {}

        async def json(self):
            if fail_json:
                raise ValueError("invalid json")
            return payload

    return FakeRequest()


class FakeUploadFile:
    def __init__(self, data: bytes):
        self._data = data
        self.file = io.BytesIO(data)

    async def read(self):
        return self._data


@pytest.fixture
def asr_app(monkeypatch):
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.asr.app",
        "services/asr/app.py",
        {
            "torch": build_torch_stub(cuda_available=False),
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


@pytest.fixture
def translation_app(monkeypatch):
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.translation.app",
        "services/translation/app.py",
        {
            "torch": build_torch_stub(cuda_available=False),
            "transformers": build_transformers_stub(),
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


@pytest.fixture
def tts_app(monkeypatch):
    tts_pkg, tts_api = build_tts_stub()
    fastapi_stub, responses_stub = build_fastapi_stub()
    return load_module(
        monkeypatch,
        "services.tts.app",
        "services/tts/app.py",
        {
            "torch": build_torch_stub(cuda_available=False),
            "transformers": build_transformers_stub(),
            "soundfile": build_soundfile_stub(),
            "TTS": tts_pkg,
            "TTS.api": tts_api,
            "fastapi": fastapi_stub,
            "fastapi.responses": responses_stub,
            "prometheus_client": build_prometheus_stub(),
        },
    )


def test_asr_helpers_build_debug_payloads(asr_app, monkeypatch):
    asr_app.psutil = SimpleNamespace(
        cpu_percent=lambda: 12.5,
        virtual_memory=lambda: SimpleNamespace(percent=38.0),
    )

    debug_info = asr_app._build_debug_info("de")

    assert debug_info["input"] == {"lang": "de"}
    assert debug_info["system"] == {"cpu": 12.5, "ram": 38.0}
    assert asr_app._build_asr_response("Hallo", False, False, debug_info) == {
        "text": "Hallo",
        "fallback": False,
    }
    assert asr_app._build_asr_response("Hallo", True, True, debug_info)["debug"] == debug_info


@pytest.mark.asyncio
async def test_asr_transcribe_fallback_and_success_paths(asr_app, monkeypatch):
    request = build_request(query_params={"debug": "true"})

    asr_app.model_loaded = False
    fallback_response = await asr_app.transcribe(
        FakeUploadFile(b"audio-bytes"), "de", request, "true"
    )
    assert fallback_response["fallback"] is True
    assert fallback_response["text"] == "Hallo Welt"

    tmp_input = tempfile.NamedTemporaryFile(delete=False)
    tmp_input.close()
    tmp_output = tempfile.NamedTemporaryFile(delete=False)
    tmp_output.close()

    class FakeModel:
        @staticmethod
        def transcribe(path, language):
            return {"text": f"{language}:{os.path.basename(path)}"}

    monkeypatch.setattr(asr_app, "model_loaded", True)
    monkeypatch.setattr(asr_app, "model", FakeModel())
    monkeypatch.setattr(asr_app, "_persist_upload_to_temp", lambda file_obj: tmp_input.name)
    monkeypatch.setattr(asr_app, "normalize_to_wav16k", lambda path: tmp_output.name)

    success_response = await asr_app.transcribe(
        FakeUploadFile(b"wav-data"), "en", build_request(query_params={}), None
    )

    assert success_response == {"text": f"en:{os.path.basename(tmp_output.name)}", "fallback": False}
    assert not os.path.exists(tmp_input.name)
    assert not os.path.exists(tmp_output.name)


def test_translation_helper_functions_cover_debug_and_chunking(translation_app, monkeypatch):
    translation_app.psutil = SimpleNamespace(
        cpu_percent=lambda: 7.0,
        virtual_memory=lambda: SimpleNamespace(percent=22.0),
    )

    debug_response = translation_app._build_debug_response(
        True, {"error": "boom"}, 400
    )
    assert debug_response is not None
    assert debug_response.status_code == 400

    with pytest.raises(translation_app._DebugResponse):
        translation_app._raise_http_error(True, {"error": None}, 422, "kaputt")

    debug_active, payload = translation_app._parse_translation_payload(
        {"text": "Hallo"}, build_request(query_params={"debug": "true"})
    )
    assert debug_active is True
    assert payload == {"text": "Hallo"}

    translation_app.MAX_INPUT_CHARS = 8
    monkeypatch.setattr(
        translation_app,
        "_generate_single",
        lambda text, source_lang, target_lang, gen_overrides: f"{source_lang}->{target_lang}:{text}",
    )
    outputs = translation_app._translate_texts(
        ["kurz", "eins. zwei. drei."], "de", "en", {}
    )
    assert outputs[0] == "de->en:kurz"
    assert outputs[1].startswith("de->en:")
    assert translation_app._maybe_uromanize(["Hallo"], False) is None


def test_translation_validation_and_response_helpers(translation_app):
    debug_info = {"error": None}
    translation_app.model_loaded = True
    translation_app.m2m_model = object()
    translation_app.m2m_tokenizer = SimpleNamespace(lang_code_to_id={"de": 0, "en": 1})
    translation_app.supported_langs = ["de", "en"]
    translation_app._validate_translation_input(
        "Hallo", "de", "en", debug_active=False, debug_info=debug_info
    )

    response = translation_app._build_translation_response(
        ["Hello"],
        "de",
        "en",
        0.123,
        False,
        True,
        {"input": "Hallo", "error": None},
    )
    assert response.status_code == 200
    assert b'"translations":"Hello"' in response.body
    assert b'"debug"' in response.body


@pytest.mark.asyncio
async def test_translation_translate_handles_invalid_json_and_success(translation_app, monkeypatch):
    with pytest.raises(StubHTTPException) as invalid_error:
        await translation_app.translate(build_request(fail_json=True))
    assert invalid_error.value.status_code == 400
    assert invalid_error.value.detail == "Invalid JSON payload"

    translation_app.model_loaded = True
    translation_app.m2m_model = object()
    translation_app.m2m_tokenizer = SimpleNamespace(lang_code_to_id={"de": 0, "en": 1})
    translation_app.supported_langs = ["de", "en"]
    monkeypatch.setattr(translation_app, "_validate_lang", lambda lang: None)
    monkeypatch.setattr(
        translation_app, "_translate_texts", lambda texts, source_lang, target_lang, gen_overrides: ["Hello"]
    )

    response = await translation_app.translate(
        build_request(
            payload={
                "text": "Hallo",
                "source_lang": "de",
                "target_lang": "en",
                "debug": "true",
            },
            query_params={},
        )
    )

    assert response.status_code == 200
    assert b'"translations":"Hello"' in response.body
    assert b'"debug"' in response.body


def test_tts_helper_functions_cover_model_resolution_and_responses(tts_app, monkeypatch):
    assert tts_app._normalize_lang_code(" EN ") == "en"
    assert tts_app._resolve_hf_model_name("ar") == "facebook/mms-tts-ara"
    assert tts_app.resolve_tts_model_name("de") == "tts_models/de/thorsten/vits"
    assert tts_app.resolve_tts_model_name("ar") == "facebook/mms-tts-ara"
    with pytest.raises(ValueError):
        tts_app.resolve_tts_model_name("")

    debug_info = {}
    session_seed = tts_app._seed_for_request("session-1", "Hallo", debug_info)
    text_seed = tts_app._seed_for_request(None, "Hallo", debug_info)
    assert isinstance(session_seed, int)
    assert isinstance(text_seed, int)

    headers_response = tts_app._audio_response(
        b"WAV", "model-x", "de", True, {"debug": True}
    )
    assert headers_response.media_type == "audio/wav"
    assert headers_response.headers["x-tts-model"] == "model-x"

    error_response = tts_app._error_response(
        True, {"error": "kaputt"}, 500, fallback=False, error="kaputt"
    )
    assert error_response.status_code == 500

    reasons = []
    tts_app._append_gpu_signal(
        reasons, {"index": 1, "utilization_percent": 90, "memory_utilization": 91}, 85
    )
    assert reasons == ["gpu1_util>=85", "gpu1_mem>=85"]

    monkeypatch.setattr(tts_app, "_load_coqui_model", lambda lang: (_ for _ in ()).throw(RuntimeError("nope")))
    monkeypatch.setattr(tts_app, "_load_hf_tts_model", lambda lang: {"hf": lang})
    tts_app.tts_model_cache.clear()
    assert tts_app.get_tts_model("ar") == {"hf": "ar"}


@pytest.mark.asyncio
async def test_tts_synthesize_handles_invalid_and_success_paths(tts_app, monkeypatch):
    invalid_response = await tts_app.synthesize(
        build_request(payload={"text": "   ", "lang": "de"}, query_params={})
    )
    assert invalid_response.status_code == 400

    monkeypatch.setattr(tts_app, "get_tts_model", lambda lang: object())
    monkeypatch.setattr(
        tts_app,
        "_render_audio_bytes",
        lambda tts_model, text: __import__("asyncio").sleep(0, result=(b"WAV", True)),
    )

    response = await tts_app.synthesize(
        build_request(
            payload={"text": "Hallo", "lang": "ar", "session_id": "abc", "debug": "true"},
            query_params={},
        )
    )

    assert response.status_code == 200
    assert response.headers["x-tts-language"] == "ar"
    assert response.headers["x-tts-model"].endswith("(MMS-TTS Fallback)")


def test_enhanced_audio_validator_convert_with_ffmpeg(tmp_path, monkeypatch):
    from services.api_gateway.enhanced_audio_validation import EnhancedAudioValidator

    validator = EnhancedAudioValidator()

    def successful_run(cmd, capture_output=True, timeout=30):
        output_path = cmd[-1]
        with open(output_path, "wb") as file_obj:
            file_obj.write(b"converted")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("services.api_gateway.enhanced_audio_validation.subprocess.run", successful_run)
    converted = validator._convert_with_ffmpeg(b"source", "webm")
    assert converted == b"converted"

    def failing_run(cmd, capture_output=True, timeout=30):
        return SimpleNamespace(returncode=1, stderr=b"broken")

    monkeypatch.setattr("services.api_gateway.enhanced_audio_validation.subprocess.run", failing_run)
    assert validator._convert_with_ffmpeg(b"source", "webm") is None


@pytest.mark.asyncio
async def test_legacy_session_route_uses_new_process_wav_contract(monkeypatch):
    from services.api_gateway import session as legacy_session
    from services.api_gateway.session_manager import ClientType

    fake_session = SimpleNamespace(id="SESSION1", messages=[])
    captured = {}

    monkeypatch.setattr(legacy_session.session_manager, "get_session", lambda session_id: fake_session)
    monkeypatch.setattr(
        legacy_session.session_manager,
        "add_message",
        lambda session_id, message: captured.setdefault("message", message),
    )
    monkeypatch.setattr(
        legacy_session,
        "process_wav",
        lambda file_bytes, source_lang, target_lang: {
            "asr_text": "Hallo",
            "translation_text": "Hello",
            "audio_bytes": b"audio",
        },
    )

    response = await legacy_session.send_session_message(
        "SESSION1",
        ClientType.ADMIN,
        FakeUploadFile(b"input-audio"),
        "de",
        "en",
    )

    assert response["status"] == "success"
    assert response["original_text"] == "Hallo"
    assert response["translated_text"] == "Hello"
    assert response["audio_available"] is True
    assert captured["message"].source_lang == "de"
    assert captured["message"].target_lang == "en"
    assert captured["message"].audio_base64 is not None
