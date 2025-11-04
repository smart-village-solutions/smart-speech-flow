import asyncio
import inspect

try:  # pragma: no cover - optional dependency detection
    import pytest_asyncio  # type: ignore  # noqa: F401
    HAS_PYTEST_ASYNCIO = True
except ImportError:  # pragma: no cover
    HAS_PYTEST_ASYNCIO = False


if not HAS_PYTEST_ASYNCIO:
    def pytest_addoption(parser):  # pragma: no cover - exercised via pytest hooks
        parser.addini(
            "asyncio_mode",
            "Compatibility shim when pytest-asyncio is not installed",
            default="auto",
        )

    def pytest_configure(config):  # pragma: no cover - exercised via pytest hooks
        config.addinivalue_line(
            "markers",
            "asyncio: mark test as requiring asyncio event loop",
        )

    def pytest_pyfunc_call(pyfuncitem):  # pragma: no cover - exercised via pytest hooks
        test_func = pyfuncitem.obj
        if not inspect.iscoroutinefunction(test_func):
            return None

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            signature = inspect.signature(test_func)
            call_kwargs = {}
            for name, value in pyfuncitem.funcargs.items():
                if name not in signature.parameters:
                    continue
                if inspect.isawaitable(value):
                    value = loop.run_until_complete(value)
                    pyfuncitem.funcargs[name] = value
                call_kwargs[name] = value

            coro = test_func(**call_kwargs)
            loop.run_until_complete(coro)

            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
        return True


__all__ = []
