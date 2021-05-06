import ast
import time

import numpy as np

from pprint import pprint
from os.path import isfile
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal

from instr.instrumentfactory import mock_enabled, GeneratorFactory, SourceFactory, \
    MultimeterFactory, AnalyzerFactory
from measureresult import MeasureResult


# TODO calibration
# TODO add attenuation field -- calculate each pow point + att power

class InstrumentController(QObject):
    pointReady = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.requiredInstruments = {
            'Анализатор': AnalyzerFactory('GPIB1::7::INSTR'),
            'P LO': GeneratorFactory('GPIB1::6::INSTR'),
            'P RF': GeneratorFactory('GPIB1::20::INSTR'),
            'Источник': SourceFactory('GPIB1::3::INSTR'),
            'Мультиметр': MultimeterFactory('GPIB1::22::INSTR'),
        }

        if isfile('./instr.ini'):
            with open('./instr.ini', mode='rt', encoding='utf-8') as f:
                addrs = ast.literal_eval(''.join(f.readlines()))
                self.requiredInstruments = {
                    'Анализатор': AnalyzerFactory(addrs['Анализатор']),
                    'P LO': GeneratorFactory(addrs['P LO']),
                    'P RF': GeneratorFactory(addrs['P RF']),
                    'Источник': SourceFactory(addrs['Источник']),
                    'Мультиметр': MultimeterFactory(addrs['Мультиметр']),
                }

        self.deviceParams = {
            'Демодулятор': {
                'F': 1,
            },
        }

        self.secondaryParams = {
            'Usrc': 5.0,
            'Flo_min': 1.0,
            'Flo_max': 3.0,
            'Flo_delta': 0.5,
            'Plo': -5.0,
            'Prf': -5.0,
            'loss': 0.82,
            'ref_level': 10.0,
            'scale_y': 5.0,
        }

        if isfile('./params.ini'):
            with open('./params.ini', 'rt', encoding='utf-8') as f:
                self.secondaryParams = ast.literal_eval(''.join(f.readlines()))

        self._deltas = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200, 250, 300, 350, 400, 450]

        if isfile('./deltas.ini'):
            with open('./deltas.ini', 'rt', encoding='utf-8') as f:
                self._deltas = ast.literal_eval(''.join(f.readlines()))

        self._instruments = dict()
        self.found = False
        self.present = False
        self.hasResult = False

        self.result = MeasureResult()

    def __str__(self):
        return f'{self._instruments}'

    def connect(self, addrs):
        print(f'searching for {addrs}')
        for k, v in addrs.items():
            self.requiredInstruments[k].addr = v
        self.found = self._find()

    def _find(self):
        self._instruments = {
            k: v.find() for k, v in self.requiredInstruments.items()
        }
        return all(self._instruments.values())

    def check(self, token, params):
        print(f'call check with {token} {params}')
        device, secondary = params
        self.present = self._check(token, device, secondary)
        print('sample pass')

    def _check(self, token, device, secondary):
        print(f'launch check with {self.deviceParams[device]} {self.secondaryParams}')
        return True

    def measure(self, token, params):
        print(f'call measure with {token} {params}')
        device, _ = params
        try:
            self.result.set_secondary_params(self.secondaryParams)
            self._measure(token, device)
            # self.hasResult = bool(self.result)
            self.hasResult = True  # HACK
        except RuntimeError as ex:
            print('runtime error:', ex)

    def _measure(self, token, device):
        param = self.deviceParams[device]
        secondary = self.secondaryParams
        print(f'launch measure with {token} {param} {secondary}')

        self._clear()
        self._init()
        self._measure_s_params(token, param, secondary)
        return True

    def _clear(self):
        self.result.clear()

    def _init(self):
        self._instruments['P LO'].send('*RST')
        self._instruments['P RF'].send('*RST')
        self._instruments['Источник'].send('*RST')
        self._instruments['Мультиметр'].send('*RST')
        self._instruments['Анализатор'].send('*RST')

    def _measure_s_params(self, token, param, secondary):
        gen_lo = self._instruments['P LO']
        gen_rf = self._instruments['P RF']
        src = self._instruments['Источник']
        mult = self._instruments['Мультиметр']
        sa = self._instruments['Анализатор']

        secondary = {
            'Usrc': 5.0,
            'Flo_min': 1.0,
            'Flo_max': 3.0,
            'Flo_delta': 0.5,
            'Plo': -5.0,
            'Prf': -5.0,
            'loss': 0.82,
            'ref_level': 10.0,
            'scale_y': 5.0,
        }

        src_u = secondary['Usrc']
        src_i = 200   # mA

        freq_lo_start = secondary['Flo_min']
        freq_lo_end = secondary['Flo_max']
        freq_lo_step = secondary['Flo_delta']

        pow_lo = secondary['Plo']
        pow_rf = secondary['Prf']

        p_loss = secondary['loss']
        ref_level = secondary['ref_level']
        scale_y = secondary['scale_y']

        freq_lo_values = [round(x, 3) for x in np.arange(start=freq_lo_start, stop=freq_lo_end + 0.2, step=freq_lo_step)]
        freq_rf_deltas = [x / 1_000 for x in self._deltas]

        src.send(f'APPLY p6v,{src_u}V,{src_i}mA')

        sa.send(':CAL:AUTO OFF')
        sa.send(':SENS:FREQ:SPAN 1MHz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {ref_level}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {scale_y}')

        gen_lo.send(f'SOUR:POW {pow_lo}dbm')
        gen_rf.send(f'SOUR:POW {pow_rf}dbm')

        if mock_enabled:
            with open('./mock_data/-5db.txt', mode='rt', encoding='utf-8') as f:
                index = 0
                mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        res = []
        for freq_lo in freq_lo_values:
            gen_lo.send(f'SOUR:FREQ {freq_lo}GHz')

            for freq_rf_delta in freq_rf_deltas:

                if token.cancelled:
                    gen_lo.send(f'OUTP:STAT OFF')
                    gen_rf.send(f'OUTP:STAT OFF')

                    if not mock_enabled:
                        time.sleep(0.5)

                    src.send('OUTPut OFF')

                    gen_rf.send(f'SOUR:POW {pow_rf}dbm')
                    gen_lo.send(f'SOUR:POW {pow_lo}dbm')

                    gen_rf.send(f'SOUR:FREQ {freq_lo_start + freq_rf_deltas[0]}GHz')
                    gen_lo.send(f'SOUR:FREQ {freq_lo_start}GHz')
                    raise RuntimeError('measurement cancelled')

                freq_rf = freq_lo + freq_rf_delta
                gen_rf.send(f'SOUR:FREQ {freq_rf}GHz')

                src.send('OUTPut ON')

                gen_lo.send(f'OUTP:STAT ON')
                gen_rf.send(f'OUTP:STAT ON')

                time.sleep(0.5)
                if not mock_enabled:
                    time.sleep(0.5)

                i_mul_read = float(mult.query('MEAS:CURR:DC? 1A,DEF'))

                center_freq = freq_rf - freq_lo
                sa.send(':CALC:MARK1:MODE POS')
                sa.send(f':SENSe:FREQuency:CENTer {center_freq}GHz')
                sa.send(f':CALCulate:MARKer1:X:CENTer {center_freq}GHz')

                if not mock_enabled:
                    time.sleep(0.5)

                pow_read = float(sa.query(':CALCulate:MARKer:Y?'))

                raw_point = {
                    'f_lo': freq_lo,
                    'f_rf': freq_rf,
                    'p_lo': pow_lo,
                    'p_rf': pow_rf,
                    'u_mul': src_u,
                    'i_mul': i_mul_read,
                    'pow_read': pow_read,
                }

                if mock_enabled:
                    raw_point = mocked_raw_data[index]
                    raw_point['loss'] = p_loss
                    index += 1

                print(raw_point)

                res.append(raw_point)

        if not mock_enabled:
            with open('out.txt', mode='wt', encoding='utf-8') as f:
                f.write(str(res))

        return res

    def _add_measure_point(self, data):
        print('measured point:', data)
        self.result.add_point(data)
        self.pointReady.emit()

    def saveConfigs(self):
        with open('./params.ini', 'wt', encoding='utf-8') as f:
            pprint(self.secondaryParams, stream=f)

    @pyqtSlot(dict)
    def on_secondary_changed(self, params):
        self.secondaryParams = params

    @property
    def status(self):
        return [i.status for i in self._instruments.values()]


def parse_float_list(lst):
    return [float(x) for x in lst.split(',')]
