"""AGWPE frame layout, checked byte by byte against the AGWPE TCP/IP API.

The 36-byte header: port (1 byte + 3 reserved), DataKind at 4, PID at 6,
CallFrom (10) at 8, CallTo (10) at 18, DataLen (4, little-endian) at 28,
User (4) at 32, then the data.  Checked here independently of the app's
own decoder, so a mistake can't hide by being made on both sides.
"""

from vara.agwpe import AGWPEFrame, HEADER_SIZE, decode_frame, encode_frame


def test_header_is_36_bytes_at_the_spec_offsets():
    raw = encode_frame(AGWPEFrame(port=1, data_kind="D", pid=0xF0,
                                  call_from="KK4ODA-7", call_to="KE4QCM-7",
                                  data=b"ARES\r"))
    assert HEADER_SIZE == 36
    assert len(raw) == 36 + 5
    assert raw[0] == 1 and raw[1:4] == b"\x00\x00\x00"          # port + reserved
    assert raw[4:5] == b"D" and raw[5] == 0                     # DataKind, reserved
    assert raw[6] == 0xF0 and raw[7] == 0                       # PID, reserved
    assert raw[8:18] == b"KK4ODA-7\x00\x00"                      # CallFrom
    assert raw[18:28] == b"KE4QCM-7\x00\x00"                     # CallTo
    assert int.from_bytes(raw[28:32], "little") == 5            # DataLen
    assert raw[32:36] == b"\x00\x00\x00\x00"                    # User
    assert raw[36:] == b"ARES\r"


def test_connect_via_frame_lists_the_digipeaters():
    """'v' frame data: digipeater count (1 byte), then 10 bytes per call."""
    from vara.agwpe import AGWPEClient
    sent = []
    client = AGWPEClient()
    client.send_frame = lambda f: sent.append(encode_frame(f)) or True
    client.connect_station_via("KK4ODA", "KE4QCM-7", ["WD5EMA-4", "N4XYZ"])
    raw = sent[0]
    assert raw[4:5] == b"v"
    assert raw[8:18] == b"KK4ODA".ljust(10, b"\x00")
    assert raw[18:28] == b"KE4QCM-7".ljust(10, b"\x00")
    assert int.from_bytes(raw[28:32], "little") == 21
    assert raw[36] == 2
    assert raw[37:47] == b"WD5EMA-4".ljust(10, b"\x00")
    assert raw[47:57] == b"N4XYZ".ljust(10, b"\x00")


def test_decode_reads_a_spec_header():
    header = (bytes([0, 0, 0, 0]) + b"C\x00" + bytes([0xF0, 0])
              + b"W1AW-5".ljust(10, b"\x00") + b"KK4ODA".ljust(10, b"\x00")
              + (3).to_bytes(4, "little") + bytes(4))
    f = decode_frame(header, b"abc")
    assert (f.port, f.data_kind, f.pid) == (0, "C", 0xF0)
    assert (f.call_from, f.call_to, f.data) == ("W1AW-5", "KK4ODA", b"abc")


def test_frames_are_logged_both_ways(caplog):
    """Every frame to and from the TNC is in the log, so an on-air report
    shows what Aether Term actually handed Soundmodem."""
    import logging
    import time
    from vara.agwpe import AGWPEClient
    from fake_agwpe import FakeAGWPE

    fake = FakeAGWPE().start()
    got = []
    client = AGWPEClient(port=fake.port, on_frame=got.append)
    caplog.set_level(logging.INFO, logger="vara.agwpe")
    try:
        assert client.connect()
        client.connect_station_via("KK4ODA-7", "KE4QCM-7", ["WD5EMA-4"])
        client.send_connected_data("KK4ODA-7", "KE4QCM-7", b"ARES\r")
        end = time.time() + 5
        while len(got) < 1 and time.time() < end:
            time.sleep(0.02)
        assert got
    finally:
        client.disconnect()
        fake.stop()
    text = caplog.text
    assert "AGWPE TX 'v' port=0 KK4ODA-7 -> KE4QCM-7" in text
    assert "AGWPE TX 'D' port=0 KK4ODA-7 -> KE4QCM-7 pid=0xF0 len=5 b'ARES\\r'" in text
    assert "AGWPE RX 'C' port=0 KE4QCM-7 -> KK4ODA-7" in text
