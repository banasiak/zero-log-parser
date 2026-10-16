"""
Tests for page markers that land inside an entry's payload in the FST/Gen3
BMS page format (Gen2.collect_paged_bms_entries, via
Gen2._marker_block_indices and Gen2._parse_around_marker). The 00 f0 ff 00
marker at every 128-byte page after the first overwrites 4 bytes of
whatever entry spans that position; the entry's length byte still counts
them. Previously only a marker over the type byte or the 0xb2 header was
recognised, and one anywhere else was decoded as data (16,773.12 A,
61.44 V, 240% state of charge). Now a structured field that depends on a
lost byte is None, the entry is flagged with mark_bytes_corrupted(), lost
characters in a debug string show as '~', and a lost timestamp is left for
the neighbouring entries to fill in.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, synthetic in-process buffers, no dataset files
checked in. The two REAL_* entries are copied from a 2023 DSR/X's BMS log
exactly as they are on disk, marker included; they hold telemetry only,
nothing that identifies the vehicle.
"""

import logging
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2

PAGE = 128
MARK = b'\x00\xf0\xff\x00'
LOGGER = logging.getLogger('test_bms_page_marker_in_payload')

# 0x4B entries with the marker at raw offset 28 (over the current) and 21
# (over the low and unloaded-low cell voltages); in the file they started
# 100 and 107 bytes into a page.
REAL_MARKER_IN_CURRENT = bytes.fromhex(
    'b2344b5d5ed16ab8ff01009cfa0000000000000000d10fd20fd60f5400f0ff001e3300ff01000000000000000007'
    '67bb01000107')
REAL_MARKER_IN_CELL_VOLTAGES = bytes.fromhex(
    'b2344ba95dd16ad001010094fa000000000000000000f0ff00d70f54ae0100001e330078000000000000000000069d'
    'bb01000109')


def _paged_buffer_with(raw, offset_in_page, pages=6):
    """A buffer of unwritten (0xff) pages with the marker at every page
    boundary after the first, and raw placed offset_in_page bytes into the
    third page. raw already holds the marker wherever it crosses into the
    next page, exactly as on disk."""
    buf = bytearray(b'\xff' * (PAGE * pages))
    for page in range(PAGE, len(buf), PAGE):
        buf[page:page + 4] = MARK
    start = 2 * PAGE + offset_in_page
    buf[start:start + len(raw)] = raw
    assert bytes(buf[start:start + len(raw)]) == bytes(raw)
    return buf  # a bytearray, as LogData hands it over; unescape_block edits in place


def _entry_across_page(message_type, payload, marker_at, timestamp=1_792_000_000):
    """Frame an entry whose raw byte marker_at falls on a page boundary, and
    overwrite those 4 bytes with the marker. Returns (raw, offset_in_page)."""
    body = bytes([message_type]) + struct.pack('<I', timestamp) + bytes(payload)
    raw = bytearray([0xb2, len(body) + 2]) + bytearray(body)
    raw[marker_at:marker_at + 4] = MARK
    return raw, PAGE - marker_at


def _collect(buf):
    return [entry for _ts, entry, _num in Gen2.collect_paged_bms_entries(buf, LOGGER)]


def _fd_payload(text):
    return struct.pack('<IBb', 250000, 0x10, -6) + text + b'\x00'


def test_marker_over_the_current_nulls_only_the_current():
    [entry] = _collect(_paged_buffer_with(REAL_MARKER_IN_CURRENT, 100))
    sd = entry['structured_data']
    assert entry['event'] == 'BMS Cell Telemetry'
    assert sd['battery_current_amps'] is None  # previously 16,773.12 A
    assert (sd['voltage_low_cell_volts'], sd['voltage_high_cell_volts']) == (4.049, 4.054)
    assert sd['state_of_charge_percent'] == 84
    assert sd['pack_voltage_volts'] == 113.511
    assert sd['bytes_corrupted'] is True and sd['corrupted_byte_count'] == 4


def test_marker_over_the_cell_voltages_nulls_only_those_two():
    [entry] = _collect(_paged_buffer_with(REAL_MARKER_IN_CELL_VOLTAGES, 107))
    sd = entry['structured_data']
    assert sd['voltage_low_cell_volts'] is None  # previously 61.44 V
    assert sd['voltage_unloaded_cell_volts'] is None
    assert sd['voltage_high_cell_volts'] == 4.055
    assert sd['battery_current_amps'] == 0.43
    assert sd['bytes_corrupted'] is True


def test_raw_hex_keeps_the_bytes_as_they_are_on_disk():
    [entry] = _collect(_paged_buffer_with(REAL_MARKER_IN_CURRENT, 100))
    assert bytes.fromhex(entry['structured_data']['raw_hex']) == REAL_MARKER_IN_CURRENT[7:]


def test_marker_inside_debug_text_shows_the_lost_characters_as_tildes():
    raw, offset = _entry_across_page(0xfd, _fd_payload(b'Entering ZERO_BMS_STATE_HIBERNATE'), 7 + 6 + 28)
    [entry] = _collect(_paged_buffer_with(raw, offset))
    assert entry['event'] == 'Entering ZERO_BMS_STATE_HIBE~~~~E'
    assert entry['conditions'] == '{corrupted: 4 bytes lost}'


def test_marker_over_the_subsecond_field_still_reads_the_text_after_the_prefix():
    raw, offset = _entry_across_page(0xfd, _fd_payload(b'Entering Hibernate'), 7)
    [entry] = _collect(_paged_buffer_with(raw, offset))
    assert entry['event'] == 'Entering Hibernate'
    assert entry['conditions'] == '{corrupted: 4 bytes lost}'


def test_marker_over_the_timestamp_leaves_the_time_unknown():
    raw, offset = _entry_across_page(0xfd, _fd_payload(b'Contactor closed'), 3)
    [entry] = _collect(_paged_buffer_with(raw, offset))
    assert entry['event'] == 'Contactor closed'
    assert entry['time'] == 'Unknown'
    assert entry['original_timestamp'] is None


def test_marker_in_undecoded_bytes_flags_the_entry_but_nulls_no_field():
    # Block bytes +12..+15 of a 45-byte 0x4B sit between the current and the
    # pack voltage and are not decoded.
    raw, offset = _entry_across_page(0x4b, bytearray(REAL_MARKER_IN_CELL_VOLTAGES[7:]), 7 + 14 + 12)
    raw[7 + 14:7 + 18] = bytes.fromhex('d10fd20f')  # restore the real cell voltages
    [entry] = _collect(_paged_buffer_with(raw, offset))
    sd = entry['structured_data']
    assert not [key for key, value in sd.items() if value is None]
    assert sd['bytes_corrupted'] is True


def test_an_escape_before_the_marker_shifts_the_lost_bytes_by_one():
    # The same payload twice, once with a 0xb2 (written fe 4d on disk) in an
    # undecoded byte before the marker. The marker stays at the same raw
    # offset, so in the unescaped payload it lands one byte earlier.
    payload = bytearray(REAL_MARKER_IN_CURRENT[7:])
    payload[21:25] = bytes.fromhex('6a0b0200')  # a real current in place of the fixture's own marker
    payload[6:8] = b'\x01\x02'
    plain = bytes([0x4b]) + struct.pack('<I', 1_792_000_000) + bytes(payload)
    raw = bytearray([0xb2, len(plain) + 2]) + bytearray(plain)
    raw[7 + 6] = 0xfe
    raw[7 + 7:7 + 7] = b'\x4d'  # payload[6] becomes 0xb2, escaped as fe 4d
    raw[1] = len(raw)
    marker_at = 7 + 14 + 1      # one raw byte later than the low cell voltage
    raw[marker_at:marker_at + 4] = MARK
    [entry] = _collect(_paged_buffer_with(raw, PAGE - marker_at))
    sd = entry['structured_data']
    assert sd['voltage_low_cell_volts'] is None
    assert sd['voltage_unloaded_cell_volts'] is None
    assert sd['voltage_high_cell_volts'] is not None


def test_entries_no_marker_touches_are_unchanged():
    raw = REAL_MARKER_IN_CURRENT[:28] + bytes.fromhex('6a0b0200') + REAL_MARKER_IN_CURRENT[32:]
    [entry] = _collect(_paged_buffer_with(raw, 10))
    sd = entry['structured_data']
    assert 'bytes_corrupted' not in sd
    assert sd['battery_current_amps'] == 133.994


def test_text_output_shows_a_lost_field_as_none_without_a_unit():
    import tempfile
    from zero_log_parser import LogData, LogFile
    buf = _paged_buffer_with(REAL_MARKER_IN_CURRENT, 100)
    first = bytes([0x01]) + struct.pack('<I', 1_792_000_000) + bytes(range(1, 6))
    buf[0:len(first) + 2] = bytes([0xb2, len(first) + 2]) + first  # a file of this format starts with an entry
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'test_BMS0.bin')
        with open(path, 'wb') as f:
            f.write(bytes(buf))
        out = os.path.join(d, 'test.txt')
        LogData(LogFile(path), timezone_offset=0).emit_zero_compatible_decoding(out)
        text = open(out, encoding='utf-8-sig').read()
    assert 'Battery Current Amps: None,' in text
    assert 'NoneA' not in text
    assert '{corrupted: 4 bytes lost}' in text
