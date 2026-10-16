"""
Tests for entry type 0xFD (debug string) in Gen2.debug_message() across
both payload layouts:

- FST/Gen3: the text follows the 6-byte prefix every entry carries (u32
  sub-second, u8 sequence, s8 UTC offset; see Gen2.fst_entry_prefix).
  Reading from byte 0 printed the first sub-second byte as a single
  garbage character, so no FST debug string was ever readable.
- Classic and ring-buffer: the text starts at byte 0, unchanged.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, synthetic in-process buffers, no dataset files
checked in. The two REAL_* payloads are single entries copied from a 2023
DSR/X's MBB and BMS logs (firmware 46); they hold only the prefix and the
text, nothing that identifies the vehicle.
"""

import logging
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2

# 0xFD entries as framed on disk (0xb2, length, type, u32 timestamp, payload).
REAL_MBB_ENTRY = bytes.fromhex(
    'b22bfd4a56d16ac808070037fa5374617465206368616e67652066726f6d2053544f5020746f2052554e00')
REAL_BMS_ENTRY = bytes.fromhex(
    'b224fd463dd16a184f07001afa517569636b2053656c6620546573742050617373656400')


def _payload(entry):
    """The payload parse_entry() hands the decoder: everything after the
    type byte and the 4-byte timestamp."""
    return bytearray(entry[7:])


def _fst_payload(text, subsecond=250000, sequence=0x37, utc_offset=-6):
    return bytearray(struct.pack('<IBb', subsecond, sequence, utc_offset) + text + b'\x00')


def _entry(payload, timestamp=1_792_000_000):
    body = bytes([0xfd]) + struct.pack('<I', timestamp) + bytes(payload)
    return bytearray([0xb2, len(body) + 2]) + bytearray(body)


def test_real_fst_payloads_decode_to_their_text():
    assert Gen2.debug_message(_payload(REAL_MBB_ENTRY))['event'] == 'State change from STOP to RUN'
    assert Gen2.debug_message(_payload(REAL_BMS_ENTRY))['event'] == 'Quick Self Test Passed'


def test_parse_entry_decodes_real_fst_entries_end_to_end():
    logger = logging.getLogger('test_debug_message_decode')
    for raw, text in ((REAL_MBB_ENTRY, 'State change from STOP to RUN'),
                      (REAL_BMS_ENTRY, 'Quick Self Test Passed')):
        length, entry, _unhandled = Gen2.parse_entry(bytearray(raw), 0, 0, logger)
        assert length == len(raw)
        assert entry['message_type'] == '0xFD'
        assert entry['event'] == text


def test_paged_bms_walker_decodes_the_same_text():
    # The BMS page format has its own walker; it dispatches through the same
    # parser table, so the fix has to show up there too.
    logger = logging.getLogger('test_debug_message_decode')
    collected = Gen2.collect_paged_bms_entries(REAL_BMS_ENTRY, logger)
    assert [entry['event'] for _ts, entry, _num in collected] == ['Quick Self Test Passed']


def test_classic_payload_is_still_read_from_byte_zero():
    for text in (b'State change from STOP to RUN', b'Key On', b'Riding', b'x'):
        assert Gen2.debug_message(bytearray(text + b'\x00'))['event'] == text.decode()


def test_printable_text_can_never_pass_the_prefix_check():
    # The smallest u32 four printable ASCII bytes can form is 0x20202020;
    # if FST_SUBSECOND_MAX_US ever reaches it, classic text could be
    # mistaken for an FST prefix.
    assert struct.unpack('<I', b'    ')[0] > Gen2.FST_SUBSECOND_MAX_US


def test_prefix_check_uses_the_shared_subsecond_limit():
    text = b'Contactor closed'
    assert Gen2.debug_message(_fst_payload(text, subsecond=0))['event'] == text.decode()
    assert Gen2.debug_message(_fst_payload(text, subsecond=1000000))['event'] == text.decode()
    # One past the limit is not an FST prefix, so the text is read from byte
    # 0 exactly as before this fix.
    out = Gen2.debug_message(_fst_payload(text, subsecond=1000001))
    assert out['event'] != text.decode()


def test_utc_offset_byte_does_not_affect_the_check():
    for offset in (-7, -6, 0, 1, 2):
        out = Gen2.debug_message(_fst_payload(b'Entering Hibernate', utc_offset=offset))
        assert out['event'] == 'Entering Hibernate'


def test_payload_no_longer_than_the_prefix_is_read_from_byte_zero():
    assert Gen2.debug_message(bytearray(b'Hello\x00'))['event'] == 'Hello'


def test_text_specific_handling_applies_after_the_prefix():
    out = Gen2.debug_message(_fst_payload(b'DEBUG: cellbox_id 2 CRC invalid'))
    assert out['event'] == 'cellbox_id 2 CRC invalid'
    assert out['log_level'] == 'DEBUG'

    out = Gen2.debug_message(_fst_payload(b'Charger 6 Charging SN:1234567 SW:209 237Vac 60Hz EVSE 16A'))
    assert out['event'] == 'Charger Status'
    assert out['structured_data']['serial_number'] == '1234567'
    assert out['structured_data']['frequency_hz'] == 60


def test_parse_entry_dispatches_synthetic_fst_entry():
    logger = logging.getLogger('test_debug_message_decode')
    raw = _entry(_fst_payload(b'All Contactors open'))
    length, entry, _unhandled = Gen2.parse_entry(raw, 0, 0, logger)
    assert length == len(raw)
    assert entry['event'] == 'All Contactors open'
