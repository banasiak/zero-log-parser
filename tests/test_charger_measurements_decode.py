"""
Tests for the DC output and AC input readings in each 49-byte record of
entry type 0x48 (Gen2.charger_info): DC voltage (u32 mV at record offset
12), DC current (u16 A at 16), AC voltage (u8 V at 26) and AC current (u8 A
at 27). The record starts after the shared 6-byte prefix.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, no dataset files checked in. REAL_0x48_CHARGING is
one entry copied from a 2023 DSR/X's MBB log while charging, with the
charger's serial number replaced by zeros; nothing else in it identifies
the vehicle or the charger. It contains no 0xFE escapes, so the payload is
the entry minus its 7-byte header.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2
from test_undecoded_and_corrupted_rendering import _run_txt

REAL_0x48_CHARGING = bytes.fromhex(
    'b23e48b36bd16a60d2040035fa466c742036000000000080018cae01003b003c0048e801002222ef1c003c3510'
    '6800000000001c008ac401003c00260001')


def _payload(entry):
    return bytearray(entry[7:])


def test_real_record_while_charging():
    sd = Gen2.charger_info(_payload(REAL_0x48_CHARGING))['structured_data']
    assert sd['charger_count'] == 1
    c = sd['chargers'][0]
    assert c['name'] == 'Flt 6'
    assert c['flags'] == 0x0180
    assert c['dc_voltage_volts'] == 110.22
    assert c['dc_current_amps'] == 59
    assert c['ac_voltage_volts'] == 239
    assert c['ac_current_amps'] == 28
    assert c['hertz'] == 60
    assert c['serial_number'] == 0  # zeroed in this copy


def test_ac_input_and_dc_output_power_balance():
    # A wrong offset for any of the four readings would not land at a
    # charger efficiency; this record's is about 97%.
    c = Gen2.charger_info(_payload(REAL_0x48_CHARGING))['structured_data']['chargers'][0]
    efficiency = (c['dc_voltage_volts'] * c['dc_current_amps']) / (c['ac_voltage_volts'] * c['ac_current_amps'])
    assert 0.9 < efficiency < 1.0


def test_each_record_of_a_two_charger_payload_has_its_own_readings():
    def record(name, vdc_mv, idc, vac, iac):
        rec = bytearray(((i % 100) + 1) for i in range(49))
        rec[0:10] = name.ljust(10, b'\x00')
        struct.pack_into('<I', rec, 12, vdc_mv)
        struct.pack_into('<H', rec, 16, idc)
        rec[26], rec[27] = vac, iac
        return rec
    payload = bytearray(struct.pack('<IBb', 250000, 0x10, -6))
    payload += record(b'Flt 6', 110220, 59, 239, 28) + record(b'3kW', 0, 0, 0, 0)
    chargers = Gen2.charger_info(payload)['structured_data']['chargers']
    assert [(c['dc_voltage_volts'], c['dc_current_amps'], c['ac_voltage_volts'], c['ac_current_amps'])
            for c in chargers] == [(110.22, 59, 239, 28), (0.0, 0, 0, 0)]


def test_conditions_include_the_readings():
    conditions = Gen2.charger_info(_payload(REAL_0x48_CHARGING))['conditions']
    assert '239 V 28 A in' in conditions
    assert '110.22 V 59 A out' in conditions


def test_text_output_renders_volts_and_amps():
    text = _run_txt(bytearray(REAL_0x48_CHARGING))
    for expected in ('Dc Voltage Volts: 110.22V', 'Dc Current Amps: 59A',
                     'Ac Voltage Volts: 239V', 'Ac Current Amps: 28A'):
        assert expected in text, expected
    assert 'mA' not in text
