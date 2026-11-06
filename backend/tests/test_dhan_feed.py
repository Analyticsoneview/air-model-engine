import struct
import unittest

from app.brokers.dhan_feed import DhanFeedProtocolError, decode_dhan_message


def header(code, length, segment=2, security_id=12345):
    return struct.pack("<BHB I", code, length, segment, security_id)


class DhanFeedDecoderTests(unittest.TestCase):
    def test_ticker_and_prev_close_concatenated(self):
        ticker_payload = struct.pack("<fI", 123.45, 1793956500)
        close_payload = struct.pack("<fI", 120.0, 500)
        message = (
            header(2, 8 + len(ticker_payload)) + ticker_payload
            + header(6, 8 + len(close_payload)) + close_payload
        )
        packets = decode_dhan_message(message)
        self.assertEqual([p["type"] for p in packets], ["ticker", "previous_close"])
        self.assertEqual(packets[0]["ltp"], 123.45)
        self.assertEqual(packets[1]["previous_oi"], 500)

    def test_quote_and_oi_packets(self):
        quote = struct.pack("<fHIfIIIffff", 101.5, 10, 1793956500, 100.5,
                            25000, 100, 120, 99.0, 98.0, 103.0, 97.0)
        oi = struct.pack("<I", 987654)
        message = header(4, 8 + len(quote)) + quote + header(5, 12) + oi
        packets = decode_dhan_message(message)
        self.assertEqual(packets[0]["ltp"], 101.5)
        self.assertEqual(packets[0]["volume"], 25000)
        self.assertEqual(packets[1]["open_interest"], 987654)

    def test_full_packet_depth(self):
        depth = b"".join(
            struct.pack("<IIHHff", 100 + i, 200 + i, 2, 3, 100.0 - i, 101.0 + i)
            for i in range(5)
        )
        payload = struct.pack(
            "<fHIfIIIIIIffff100s", 101.5, 10, 1793956500, 100.5,
            25000, 100, 120, 900, 950, 800, 99.0, 98.0, 103.0, 97.0, depth,
        )
        packet = decode_dhan_message(header(8, 8 + len(payload)) + payload)[0]
        self.assertEqual(packet["type"], "full")
        self.assertEqual(packet["open_interest"], 900)
        self.assertEqual(len(packet["depth"]), 5)
        self.assertEqual(packet["depth"][0]["bid_quantity"], 100)

    def test_invalid_and_truncated_packets_rejected(self):
        with self.assertRaises(DhanFeedProtocolError):
            decode_dhan_message(b"abc")
        with self.assertRaises(DhanFeedProtocolError):
            decode_dhan_message(header(2, 30) + b"short")


if __name__ == "__main__":
    unittest.main()
