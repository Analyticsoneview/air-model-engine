"""DhanHQ v2 binary market-feed packet decoder.

Packet layout is defined by Dhan's v2 Live Market Feed documentation.
A WebSocket message may contain one or more concatenated packets.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any


class DhanFeedProtocolError(ValueError):
    pass


_HEADER = struct.Struct("<BHB I")
_TICKER = struct.Struct("<fI")
_PREV_CLOSE = struct.Struct("<fI")
_QUOTE = struct.Struct("<fHIfIIIffff")
_OI = struct.Struct("<I")
_FULL = struct.Struct("<fHIfIIIIIIffff100s")
_DEPTH_LEVEL = struct.Struct("<IIHHff")


def _positive_or_none(value: float) -> float | None:
    return value if value > 0 else None


def decode_dhan_message(message: bytes) -> list[dict[str, Any]]:
    """Decode all packets in one binary WebSocket message without losing trailing packets."""
    if not isinstance(message, (bytes, bytearray, memoryview)):
        raise DhanFeedProtocolError("Dhan feed message must be binary")
    data = bytes(message)
    packets: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise DhanFeedProtocolError("Truncated Dhan response header")
        code, packet_length, segment, security_id = _HEADER.unpack_from(data, offset)
        if packet_length < 8 or offset + packet_length > len(data):
            raise DhanFeedProtocolError("Invalid Dhan packet length")
        packet = data[offset:offset + packet_length]
        payload = packet[8:]
        item: dict[str, Any] = {
            "response_code": code,
            "exchange_segment_id": segment,
            "security_id": security_id,
        }
        if code == 2:
            if len(payload) != _TICKER.size:
                raise DhanFeedProtocolError("Invalid ticker packet size")
            ltp, epoch = _TICKER.unpack(payload)
            item.update(type="ticker", ltp=ltp, exchange_time=datetime.fromtimestamp(epoch, timezone.utc).isoformat())
        elif code == 6:
            if len(payload) != _PREV_CLOSE.size:
                raise DhanFeedProtocolError("Invalid previous-close packet size")
            close, previous_oi = _PREV_CLOSE.unpack(payload)
            item.update(type="previous_close", previous_close=close, previous_oi=previous_oi)
        elif code == 4:
            if len(payload) != _QUOTE.size:
                raise DhanFeedProtocolError("Invalid quote packet size")
            ltp, ltq, epoch, average, volume, sell_qty, buy_qty, open_price, close_price, high, low = _QUOTE.unpack(payload)
            item.update(
                type="quote", ltp=ltp,
                last_trade_quantity=ltq,
                exchange_time=datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
                average_price=average, volume=volume, total_sell_quantity=sell_qty,
                total_buy_quantity=buy_qty, open=_positive_or_none(open_price),
                close=_positive_or_none(close_price), high=_positive_or_none(high),
                low=_positive_or_none(low),
            )
        elif code == 5:
            if len(payload) != _OI.size:
                raise DhanFeedProtocolError("Invalid OI packet size")
            item.update(type="oi", open_interest=_OI.unpack(payload)[0])
        elif code == 8:
            if len(payload) != _FULL.size:
                raise DhanFeedProtocolError("Invalid full packet size")
            (ltp, ltq, epoch, average, volume, sell_qty, buy_qty, oi, oi_high, oi_low,
             open_price, close_price, high, low, depth_bytes) = _FULL.unpack(payload)
            depth = []
            for level in range(5):
                bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = _DEPTH_LEVEL.unpack_from(depth_bytes, level * 20)
                depth.append({
                    "bid_quantity": bid_qty, "ask_quantity": ask_qty,
                    "bid_orders": bid_orders, "ask_orders": ask_orders,
                    "bid_price": _positive_or_none(bid_price),
                    "ask_price": _positive_or_none(ask_price),
                })
            item.update(
                type="full", ltp=ltp,
                last_trade_quantity=ltq,
                exchange_time=datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
                average_price=average, volume=volume, total_sell_quantity=sell_qty,
                total_buy_quantity=buy_qty, open_interest=oi, oi_high=oi_high,
                oi_low=oi_low, open=_positive_or_none(open_price),
                close=_positive_or_none(close_price), high=_positive_or_none(high),
                low=_positive_or_none(low), depth=depth,
            )
        elif code == 50:
            if len(payload) < 2:
                raise DhanFeedProtocolError("Invalid disconnect packet")
            item.update(type="disconnect", reason_code=struct.unpack_from("<h", payload)[0])
        else:
            item.update(type="unknown", payload_length=len(payload))
        packets.append(item)
        offset += packet_length
    return packets
