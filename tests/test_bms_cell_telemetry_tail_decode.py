"""
Tests for the fields after the pack voltage in the BMS-side 0x4C / 0x4D
cell telemetry (Gen2.bms_cell_telemetry), decoded on the longer variant
of each (63 / 71 bytes): pack temperature low and high, the discharge and
charge current limits, and the cell voltage spread. Offsets are relative
to the same field base as the rest of the block (BMS_CELL_TELEMETRY_FIELD_BASE
plus 4 or 8).

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, no dataset files checked in. The two REAL_*
entries are copied from a 2023 DSR/X's BMS log: one while riding at 122 A,
one while charging at 55 A. They hold telemetry only, nothing that
identifies the vehicle, and contain no 0xFE escapes, so each payload is
the entry minus its 7-byte header.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2
from test_undecoded_and_corrupted_rendering import _run_txt

REAL_0x4C_DISCHARGING = bytes.fromhex(
    'b2464c9d43d16a00b80b0047fa000000000000000000000000020f760f100f4cb3dc01001a3300ff01000000'
    '00000000000780a50100081318195d9a03a200d10c0200000e00')
REAL_0x4D_CHARGING = bytes.fromhex(
    'b24e4deb55d16a80bb00005dfa000000000000000000000000000000006a0ffd0e6e0f44d027ffff1c3300ff01'
    '00000000000000000706b0010001151c1d578e034400e10b0200000400a00c0200')

TAIL_KEYS = ('pack_temperature_low_celsius', 'pack_temperature_high_celsius',
             'discharge_current_limit_amps', 'charge_current_limit_amps', 'cell_voltage_spread_volts')


def _payload(entry):
    return bytearray(entry[7:])


def test_0x4c_while_riding():
    sd = Gen2.bms_cell_telemetry(0x4c, _payload(REAL_0x4C_DISCHARGING))['structured_data']
    assert sd['battery_current_amps'] == 122.035
    assert (sd['pack_temperature_low_celsius'], sd['pack_temperature_high_celsius']) == (24, 25)
    assert sd['discharge_current_limit_amps'] == 922
    assert sd['charge_current_limit_amps'] == 162
    assert sd['cell_voltage_spread_volts'] == 0.014


def test_0x4d_while_charging():
    sd = Gen2.bms_cell_telemetry(0x4d, _payload(REAL_0x4D_CHARGING))['structured_data']
    assert sd['battery_current_amps'] == -55.344
    assert (sd['pack_temperature_low_celsius'], sd['pack_temperature_high_celsius']) == (28, 29)
    assert sd['discharge_current_limit_amps'] == 910
    assert sd['charge_current_limit_amps'] == 68
    assert sd['cell_voltage_spread_volts'] == 0.004


def test_spread_is_high_minus_low_cell_voltage():
    for message_type, entry in ((0x4c, REAL_0x4C_DISCHARGING), (0x4d, REAL_0x4D_CHARGING)):
        sd = Gen2.bms_cell_telemetry(message_type, _payload(entry))['structured_data']
        assert round(sd['voltage_high_cell_volts'] - sd['voltage_low_cell_volts'], 3) == sd['cell_voltage_spread_volts']


def test_shorter_variants_and_0x4b_do_not_get_the_tail_fields():
    for message_type, length in ((0x4c, 61), (0x4d, 69), (0x4b, 43), (0x4b, 45)):
        payload = bytearray((i % 100) + 1 for i in range(length))
        payload[0:4] = (123000).to_bytes(4, 'little')
        sd = Gen2.bms_cell_telemetry(message_type, payload)['structured_data']
        assert not any(key in sd for key in TAIL_KEYS), (message_type, length)


def test_text_output_renders_limits_in_amps_and_temperatures_in_celsius():
    text = _run_txt(bytearray(REAL_0x4C_DISCHARGING))
    for expected in ('Pack Temperature Low Celsius: 24°C', 'Pack Temperature High Celsius: 25°C',
                     'Discharge Current Limit Amps: 922A', 'Charge Current Limit Amps: 162A',
                     'Cell Voltage Spread Volts: 0.014V'):
        assert expected in text, expected
    assert 'mA' not in text
