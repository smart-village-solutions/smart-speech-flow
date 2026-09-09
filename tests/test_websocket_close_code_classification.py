"""An abnormal close code is not a clean client exit.

The endpoint's receive loop treats every WebSocketDisconnect the same and
leaves exit_reason at "client_disconnect". A browser closing its tab and a
connection dying mid-frame (1006) or a server error (1011) then record the
identical reason, so the unexpected-disconnect KPI and
WebSocketConnectionFailures stay blind to the failures they exist to catch --
the same defect this branch fixed one layer down, still present at the seam.
"""

import pytest
from fastapi import WebSocketDisconnect

from services.api_gateway import websocket as ws
from services.api_gateway.session_manager import SessionStatus
from services.api_gateway.websocket_monitor import DisconnectReason


class TestOrdinaryClosesStayClean:
    @pytest.mark.parametrize(
        "code",
        [
            1000,  # normal closure
            1001,  # going away -- tab closed, navigation
            1005,  # no status received: a close frame that carried no code
        ],
    )
    def test_a_routine_close_is_a_client_disconnect(self, code: int):
        assert ws.disconnect_reason_for_close_code(code) == "client_disconnect"


class TestAbnormalClosesAreReported:
    @pytest.mark.parametrize(
        "code",
        [
            1006,  # abnormal closure: no close frame at all
            1011,  # internal server error
            1012,  # service restart
            1013,  # try again later
            1014,  # bad gateway
            1015,  # TLS handshake failure
        ],
    )
    def test_an_abnormal_close_is_a_connection_error(self, code: int):
        reason = ws.disconnect_reason_for_close_code(code)

        assert reason == "connection_error"
        assert DisconnectReason.from_wire(reason) is DisconnectReason.CONNECTION_ERROR

    @pytest.mark.parametrize("code", [1002, 1003, 1007, 1008, 1009, 1010])
    def test_a_protocol_level_close_is_a_protocol_error(self, code: int):
        assert ws.disconnect_reason_for_close_code(code) == "protocol_error"

    def test_an_unknown_code_is_not_silently_clean(self):
        """Consistent with DisconnectReason.from_wire: an unrecognised cause is
        not evidence of a clean exit."""
        assert ws.disconnect_reason_for_close_code(4999) != "client_disconnect"


class TestTheReasonReachesCleanup:
    """The classifier is only worth having if the endpoint uses it."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            (1000, DisconnectReason.CLIENT_DISCONNECT),
            (1006, DisconnectReason.CONNECTION_ERROR),
            (1011, DisconnectReason.CONNECTION_ERROR),
        ],
    )
    async def test_the_endpoint_records_the_classified_reason(
        self, monkeypatch, code: int, expected: DisconnectReason
    ):
        recorded: list[str] = []

        class _Session:
            status = SessionStatus.ACTIVE

        class _SessionManager:
            def get_session(self, session_id):
                return _Session()

        class _Manager:
            session_manager = _SessionManager()

            async def connect_websocket(self, *args, **kwargs):
                return "conn-1"

            async def disconnect_websocket(self, connection_id, reason, *args):
                recorded.append(reason)

        class _Socket:
            async def receive_json(self):
                raise WebSocketDisconnect(code=code)

        monkeypatch.setattr(ws, "validate_websocket_origin", _always_allowed)
        await ws.websocket_endpoint(
            websocket=_Socket(),
            session_id="session-1",
            client_type="customer",
            manager=_Manager(),
            origin="https://console.example",
        )

        assert recorded == [expected.value]


async def _always_allowed(origin):
    return True
