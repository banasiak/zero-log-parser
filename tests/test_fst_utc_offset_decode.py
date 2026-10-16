"""
Tests for byte 5 of the shared FST/Gen3 entry prefix (Gen2.fst_entry_prefix):
the UTC offset in whole hours, signed, exposed as utc_offset_hours on every
FST decoder that copies the prefix into its structured_data. The raw byte
stays available as marker, its name from before it was identified.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, synthetic in-process buffers, no dataset files
checked in. The two REAL_* payloads are single entries copied from a 2023
DSR/X's MBB and BMS logs (firmware 46), recorded under US Mountain Daylight
Time; they hold telemetry only, nothing that identifies the vehicle.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2
from test_undecoded_and_corrupted_rendering import _entry, _run_txt

# 0x51 payload (68 bytes, state WAIT) and BMS-side 0x4C payload (63 bytes),
# as parse_entry() hands them to the decoder.
REAL_MBB_0x51 = bytes.fromhex(
    'd841040009fa000000006a00000000000000000000000000000000000000000000000057414954003c000000'
    'ac0a00000000000000000000000000000000000020b3c800')
REAL_BMS_0x4C = bytes.fromhex(
    '00b80b0047fa000000000000000000000000020f760f100f4cb3dc01001a3300ff0100000000000000000780'
    'a50100081318195d9a03a200d10c0200000e00')


def _prefix(offset_byte, subsecond=250000, sequence=0x10):
    return bytearray(struct.pack('<IBB', subsecond, sequence, offset_byte))


def test_byte_5_reads_as_a_signed_hour_offset():
    cases = {0xfa: -6, 0xf9: -7, 0xf8: -8, 0xfc: -4, 0xfb: -5, 0x00: 0, 0x01: 1, 0x02: 2,
             0xf4: -12, 0x0e: 14}
    for raw, hours in cases.items():
        assert Gen2.fst_entry_prefix(_prefix(raw))['utc_offset_hours'] == hours, hex(raw)


def test_marker_keeps_the_raw_unsigned_byte():
    prefix = Gen2.fst_entry_prefix(_prefix(0xf9))
    assert prefix['marker'] == 0xf9
    assert prefix['utc_offset_hours'] == -7


def test_real_mbb_and_bms_payloads_carry_mountain_daylight_time():
    sd = Gen2.vehicle_state_telemetry(bytearray(REAL_MBB_0x51))['structured_data']
    assert sd['vehicle_state'] == 'WAIT'
    assert sd['utc_offset_hours'] == -6

    sd = Gen2.bms_cell_telemetry(0x4c, bytearray(REAL_BMS_0x4C))['structured_data']
    assert sd['utc_offset_hours'] == -6


def test_text_output_shows_the_offset_as_a_plain_signed_number():
    payload = bytearray(46)
    struct.pack_into('<I', payload, 0, 1000)
    payload[5] = 0xf9
    payload[35:39] = b'RUN\x00'
    text = _run_txt(_entry(0x4b, 1_600_000_000, payload))
    assert 'Utc Offset Hours: -7,' in text
    assert 'Marker: 249' in text
