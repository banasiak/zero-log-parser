"""
Tests for entry type 0x54 ("Sensor Data") in Gen2.sensor_data(): the
shared 6-byte FST prefix and 16 unidentified bytes. odometer_meters /
odometer_km used to be read from bytes 0-3, which are the prefix's
sub-second field, and sensor_1..4_value / status_flags from offsets that
straddle the prefix; all of them are gone.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, synthetic in-process buffers, no dataset files
checked in. The payload bytes follow a shape seen in real 0x54 entries.
"""

import logging
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2

BODY = bytes.fromhex('000000003efeffff0000000051950100')


def _payload(subsecond=484000, sequence=0x1e, utc_offset=-6, body=BODY):
    return bytearray(struct.pack('<IBb', subsecond, sequence, utc_offset) + body)


def test_decodes_the_prefix_and_keeps_the_rest_raw():
    out = Gen2.sensor_data(_payload())
    sd = out['structured_data']
    assert out['event'] == 'Sensor Data'
    assert sd['subsecond_us'] == 484000
    assert sd['sequence'] == 0x1e
    assert bytes.fromhex(sd['raw_hex']) == bytes(_payload())


def test_the_subsecond_field_is_not_reported_as_an_odometer():
    sd = Gen2.sensor_data(_payload())['structured_data']
    assert not any(key.startswith(('odometer', 'sensor_', 'status')) for key in sd)


def test_other_lengths_and_out_of_range_subseconds_fall_back():
    for payload in (_payload()[:21], _payload() + b'\x01', _payload(subsecond=1000001)):
        out = Gen2.sensor_data(payload)
        assert 'structured_data' not in out
        assert out['conditions'].startswith('Raw data:')


def test_parse_entry_dispatches_end_to_end():
    logger = logging.getLogger('test_sensor_data_decode')
    body = bytes([0x54]) + struct.pack('<I', 1_792_000_000) + bytes(_payload())
    # 0xFE (and 0xB2) are escaped on disk as fe 01 (fe 4d)
    escaped = body.replace(b'\xfe', b'\xfe\x01').replace(b'\xb2', b'\xfe\x4d')
    raw = bytearray([0xb2, len(escaped) + 2]) + bytearray(escaped)
    length, entry, _unhandled = Gen2.parse_entry(raw, 0, 0, logger)
    assert length == len(raw)
    assert entry['message_type'] == '0x54'
    assert entry['structured_data']['subsecond_us'] == 484000
