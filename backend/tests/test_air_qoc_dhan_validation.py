import pytest
from pydantic import ValidationError

from app.air_qoc_dhan import DhanOptionChainRequest


def test_option_chain_request_accepts_iso_date_expiry():
    request = DhanOptionChainRequest(
        underlying_scrip=13, underlying_segment="IDX_I", expiry="2026-11-26"
    )
    assert request.expiry == "2026-11-26"


def test_option_chain_request_rejects_non_iso_expiry():
    with pytest.raises(ValidationError):
        DhanOptionChainRequest(
            underlying_scrip=13, underlying_segment="IDX_I", expiry="26-11-2026"
        )
