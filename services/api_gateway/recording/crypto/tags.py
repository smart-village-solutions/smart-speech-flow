"""Type tags (spec Appendix A.2). Each is also the HKDF `info` of its payload."""

from __future__ import annotations

from typing import Final

OBJECT: Final[str] = "ssf-rec/object/v1"
CK_WRAP: Final[str] = "ssf-rec/ck-wrap/v1"
PRIVATE_KEY: Final[str] = "ssf-rec/private-key/v1"
SHARE: Final[str] = "ssf-rec/share/v1"
SUBSHARE: Final[str] = "ssf-rec/subshare/v1"
PARTIAL: Final[str] = "ssf-rec/partial/v1"
SERVER_LAYER: Final[str] = "ssf-rec/server-layer/v1"
AUDIT: Final[str] = "ssf-rec/audit/v1"
WRAP_SIG: Final[str] = "ssf-rec/wrap-sig/v1"
DEALING_SIG: Final[str] = "ssf-rec/dealing-sig/v1"
REQUEST_SIG: Final[str] = "ssf-rec/request-sig/v1"
APPROVAL_SIG: Final[str] = "ssf-rec/approval-sig/v1"
CHAIN_SIG: Final[str] = "ssf-rec/chain-sig/v1"
VERIFICATION_SIG: Final[str] = "ssf-rec/verification-sig/v1"
TRANSCRIPT: Final[str] = "ssf-rec/transcript/v1"
DLEQ: Final[str] = "ssf-rec/dleq/v1"
POK: Final[str] = "ssf-rec/pok/v1"
FINGERPRINT: Final[str] = "ssf-rec/fpr/v1"

SEALED_TYPES: Final[frozenset[str]] = frozenset({CK_WRAP, SHARE, SUBSHARE, PARTIAL})
