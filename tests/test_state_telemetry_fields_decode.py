"""
Tests for the telemetry fields of entry types 0x51/0x52/0x53
(Gen2.state_telemetry_fields, read relative to the state tag at payload
offset 35 / 39 / 43), decoded on the longest variant of each type: 68, 85
and 99 bytes. The shorter variants keep these bytes in raw_hex only.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, no dataset files checked in. The four REAL_*
entries are copied from a 2023 DSR/X's MBB log (firmware 46): a ride at
peak current, a ride with the odometer, a charge, and the bike waiting
with every pack reading still zero. They hold telemetry only, nothing that identifies
the vehicle, and contain no 0xFE escapes, so each payload is the entry
minus its 7-byte header.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero_log_parser import Gen2
from test_undecoded_and_corrupted_rendering import _run_txt

REAL_0x51_RUN_PEAK = bytes.fromhex(
    'b24b51465ad16ac8fc0800a1fa00000000000000001c9c0100346705008a0d000056d79c0100156105005255'
    '4e000000000000d00b00002e0000002d0000001800000017000000100ac600')
REAL_0x51_WAIT = bytes.fromhex(
    'b24b510f55d16ad841040009fa000000006a00000000000000000000000000000000000000000000000057414954'
    '003c000000ac0a00000000000000000000000000000000000020b3c800')
REAL_0x52_RUN = bytes.fromhex(
    'b25c52725bd16a78390800b7fa000000000000000000000000d4a70100b4a40100260d00005315a70100948001'
    '0052554e0000000000008b0b0000340000002f0000001900000018000000f84ec80001018554030024245805aa'
    '4800')
REAL_0x53_CHRG = bytes.fromhex(
    'b26a53736fd16aa8cc03003efa0000000000000000200000000a0000000000000000000000000000004f65b401'
    '002a32ffff43485247000c000000e30d000000000000000000001e0000001c000000100ccb00010130560300000000'
    '0064450000000000000000000000')


def _payload(entry):
    return bytearray(entry[7:])


def test_0x51_ride_at_peak_current():
    sd = Gen2.vehicle_state_telemetry(_payload(REAL_0x51_RUN_PEAK))['structured_data']
    assert sd['vehicle_state'] == 'RUN'
    assert sd['mbb_pack_voltage_volts'] == 105.5
    assert sd['mbb_pack_current_amps'] == 354.1
    assert sd['motor_rpm'] == 3466
    assert sd['state_of_charge_percent'] == 86
    assert sd['bms_pack_voltage_volts'] == 105.687
    assert sd['bms_pack_current_amps'] == 352.533
    assert sd['ambient_temperature_celsius'] == 30.24
    assert (sd['temperature_1_celsius'], sd['temperature_2_celsius']) == (46, 45)
    assert (sd['pack_temperature_high_celsius'], sd['pack_temperature_low_celsius']) == (24, 23)
    assert sd['battery_12v_volts'] == 12.979
    assert 'odometer_km' not in sd  # 0x51 carries no odometer


def test_0x51_deprecated_temperature_aliases_match_the_new_names():
    sd = Gen2.vehicle_state_telemetry(_payload(REAL_0x51_RUN_PEAK))['structured_data']
    assert sd['temperature_3_celsius'] == sd['pack_temperature_high_celsius']
    assert sd['temperature_4_celsius'] == sd['pack_temperature_low_celsius']


def test_mbb_and_bms_sides_of_the_same_record_agree_while_riding():
    for entry, decode in ((REAL_0x51_RUN_PEAK, lambda x: Gen2.vehicle_state_telemetry(x)),
                          (REAL_0x52_RUN, lambda x: Gen2.vehicle_state_telemetry_tier(0x52, x))):
        sd = decode(_payload(entry))['structured_data']
        assert abs(sd['mbb_pack_voltage_volts'] - sd['bms_pack_voltage_volts']) < 1
        assert abs(sd['mbb_pack_current_amps'] - sd['bms_pack_current_amps']) < 20


def test_0x51_waiting_with_every_pack_reading_zero():
    sd = Gen2.vehicle_state_telemetry(_payload(REAL_0x51_WAIT))['structured_data']
    assert sd['vehicle_state'] == 'WAIT'
    for key in ('mbb_pack_voltage_volts', 'mbb_pack_current_amps', 'motor_rpm', 'state_of_charge_percent',
                'bms_pack_voltage_volts', 'bms_pack_current_amps', 'temperature_1_celsius',
                'pack_temperature_high_celsius'):
        assert sd[key] == 0, key
    assert sd['ambient_temperature_celsius'] == 27.32
    assert sd['battery_12v_volts'] == 13.153


def test_0x52_ride_carries_the_odometer():
    sd = Gen2.vehicle_state_telemetry_tier(0x52, _payload(REAL_0x52_RUN))['structured_data']
    assert sd['state'] == 'RUN'
    assert sd['motor_rpm'] == 3366
    assert sd['state_of_charge_percent'] == 83
    assert sd['ambient_temperature_celsius'] == 29.55
    assert (sd['pack_temperature_high_celsius'], sd['pack_temperature_low_celsius']) == (25, 24)
    assert sd['battery_12v_volts'] == 13.127
    assert sd['odometer_km'] == 21824.5


def test_0x53_charge_has_negative_bms_current_and_no_controller_readings():
    sd = Gen2.vehicle_state_telemetry_tier(0x53, _payload(REAL_0x53_CHRG))['structured_data']
    assert sd['state'] == 'CHRG'
    assert (sd['mbb_pack_voltage_volts'], sd['mbb_pack_current_amps'], sd['motor_rpm']) == (0, 0, 0)
    assert sd['bms_pack_voltage_volts'] == 111.717
    assert sd['bms_pack_current_amps'] == -52.694
    assert sd['state_of_charge_percent'] == 79
    assert sd['odometer_km'] == 21867.2


def test_odometer_does_not_go_backwards_between_the_two_real_records():
    ride = Gen2.vehicle_state_telemetry_tier(0x52, _payload(REAL_0x52_RUN))['structured_data']
    charge = Gen2.vehicle_state_telemetry_tier(0x53, _payload(REAL_0x53_CHRG))['structured_data']
    assert charge['odometer_km'] >= ride['odometer_km']


def _filler(length, tag_offset, tag=b'RUN\x00'):
    buf = bytearray((i % 100) + 1 for i in range(length))
    struct.pack_into('<I', buf, 0, 76000)
    buf[tag_offset:tag_offset + 4] = tag
    return buf


def test_shorter_variants_do_not_get_the_new_fields():
    sd = Gen2.vehicle_state_telemetry(_filler(64, 35))['structured_data']
    assert 'mbb_pack_voltage_volts' not in sd
    assert [k for k in sd if k.startswith('temperature_')] == [
        'temperature_1_celsius', 'temperature_2_celsius', 'temperature_3_celsius', 'temperature_4_celsius']
    for message_type, length, tag_offset in ((0x52, 81, 39), (0x53, 93, 43), (0x53, 95, 43)):
        sd = Gen2.vehicle_state_telemetry_tier(message_type, _filler(length, tag_offset))['structured_data']
        assert 'mbb_pack_voltage_volts' not in sd and 'odometer_km' not in sd, (message_type, length)


def test_text_output_renders_each_field_with_its_unit():
    text = _run_txt(bytearray(REAL_0x52_RUN))
    for expected in ('Mbb Pack Voltage Volts: 108.5V', 'Mbb Pack Current Amps: 107.7A', 'Motor Rpm: 3366,',
                     'State Of Charge Percent: 83%', 'Bms Pack Current Amps: 98.452A',
                     'Ambient Temperature Celsius: 29.55°C', 'Pack Temperature High Celsius: 25°C',
                     'Battery 12V Volts: 13.127V', 'Odometer Km: 21824.5'):
        assert expected in text, expected
    assert 'mA' not in text
