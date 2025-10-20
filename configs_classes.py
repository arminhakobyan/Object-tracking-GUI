import time
import json
import serial

"""
COM_PORT = 'COM1'



BAUD_RATE = 9600

ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
ser.close()
ser.open()
"""


def write_response_to_serial(ser, response):
    print("write_response_to_serial", response)

    ser.write(bytes([0xff]))

    for char in response:
        ser.write(char.encode())
        print(char)

    ser.write(bytes([0xff]))

    print("response is sent")


class Inputs:
    def __init__(self, x_pos: int, y_pos: int):  # , threshold: int, direction_threshold: int, autocorr_threshold: int,
        #  match_size: int):

        self.x_pos = x_pos
        self.y_pos = y_pos
        # self.threshold = threshold
        # self.direction_threshold = direction_threshold
        # self.autocorr_threshold = autocorr_threshold
        # self.match_size = match_size

    def to_dict(self):
        return {
            "x_pos": self.x_pos,
            "y_pos": self.y_pos,
            # "threshold": self.threshold,
            # "direction_threshold": self.direction_threshold,
            # "autocorr_threshold":  self.autocorr_threshold,
            # "match_size":  self.match_size,
        }

    def to_dict_coords(self):
        return {
            "x_pos": self.x_pos,
            "y_pos": self.y_pos,
        }

    def to_json_coords(self):
        return json.dumps(self.to_dict_coords())

    def set_x(self, x):
        self.x_pos = x

    def set_y(self, y):
        self.y_pos = y

    def set_threshold(self, thr: int):
        self.threshold = thr


    def set_direction_threshold(self, dir_thr: int):
        self.direction_threshold = dir_thr


    def set_autocorr_threshold(self, auto_thr: int):
        self.autocorr_threshold = auto_thr


    def set_match_size(self, m_size: int):
        self.match_size = m_size

    def to_json(self):
        return json.dumps(self.to_dict())

    def write_coords_to_serial(self, uart_ser, x_pos=None, y_pos=None):
        self.x_pos = x_pos if x_pos is not None else self.x_pos
        self.y_pos = y_pos if y_pos is not None else self.y_pos
        coords_json = self.to_json_coords()
        arr = []

        uart_ser.write(bytes([0xff]))
        for char in "input" + coords_json:
            uart_ser.write(char.encode())
            # arr.append(char.encode())
            time.sleep(0.001)
        uart_ser.write(bytes([0xff]))
        print(arr)
        print(f"Successfully changed the inputs to: {coords_json}")

    def write_width_to_serial(self, ser, width):
        print("write_width_to_serial w - ", width)
        to_dict = {
            "width": width
        }
        width_to_json = json.dumps(to_dict)

        ser.write(255)

        for char in width_to_json:
            ser.write(char.encode())
            time.sleep(0.001)
        ser.write(255)

    def write_height_to_serial(self, ser, height):
        print("write_height_to_serial h - ", height)
        to_dict = {
            "height": height
        }
        height_to_json = json.dumps(to_dict)

        ser.write(255)

        for char in height_to_json:
            ser.write(char.encode())
            time.sleep(0.001)
        ser.write(255)

    def write_baud_rate_to_serial(self, ser, bd):
        print("write_baud_rate_to_serial bd - ", bd)
        to_dict = {
            "baud_rate": bd
        }
        bd_to_json = json.dumps(to_dict)

        ser.write(255)

        for char in bd_to_json:
            ser.write(char.encode())
            time.sleep(0.001)
        ser.write(255)


    def write_to_serial(self, uart_ser, x_pos=None, y_pos=None, thr=100, dir_thr=100, auto_thr=100, m_size=32):
        self.x_pos = x_pos if x_pos is not None else self.x_pos
        self.y_pos = y_pos if y_pos is not None else self.y_pos
        # self.threshold = thr
        # self.direction_threshold = dir_thr
        # self.autocorr_threshold = auto_thr
        # self.match_size = m_size

        inputs_json = self.to_json()
        print("HI")

        uart_ser.write(255)
        for char in inputs_json:
            uart_ser.write(char.encode())
            time.sleep(0.001)
        uart_ser.write(255)

        print(f"Successfully changed the inputs to: {inputs_json}")


def read_inputs(uart_ser):
    for char in "$data":
        uart_ser.write(char.encode())
        time.sleep(0.001)
    inputs_raw = uart_ser.read(256) or "{}"
    print(inputs_raw)

    inputs_dict = json.loads(inputs_raw)
    inputs = Inputs(*inputs_dict.values())
    return inputs




""" 
class Configurations:
    def __init__(self, width, height, frequency):
        self.width = width
        self.height = height
        self.frequency = frequency
        # self.x_pos = x_pos
        # self.y_pos = y_pos

    def to_dict(self):
        return {
            "width": self.width,
            "height": self.height,
            "frequency": self.frequency
        }

    def to_json(self):
        return json.dumps(self.to_dict())

    def reconf(self, uart_ser, width=None, height=None, frequency=None):
        self.width = width if width is not None else self.width
        self.height = height if height is not None else self.height
        self.frequency = frequency if frequency is not None else self.frequency

        configs_json = self.to_json()

        for char in "$write" + configs_json + "$":
            uart_ser.write(char.encode())
            time.sleep(0.001)

        print(f"Successfully changed the configuration to: {configs_json}")


def read_configs(uart_ser):
    for char in "$read":
        uart_ser.write(char.encode())
        time.sleep(0.001)
    configs_raw = uart_ser.read(256) or "{}"
    configs_dict = json.loads(configs_raw)
    configs = Configurations(*configs_dict.values())
    return configs




conf = read_configs(ser)
print(conf)
conf.reconf(ser, height=500)
conf = read_configs(ser)
print(conf)
# # print('sleep')
# # time.sleep(5)
# conf = read_configs(ser)
# print(conf.to_json())
# inp = read_inputs(ser)
# print(inp, inp.x_pos, inp.y_pos)
# inp = read_inputs(ser)
# print(inp, inp.x_pos, inp.y_pos)
inp = read_inputs(ser)
print(inp, inp.x_pos, inp.y_pos)
for i in range(100):
    inp.reconf(ser,x_pos=i, y_pos=i*3)
    inpo = read_inputs(ser)
    print(inpo.x_pos, inpo.y_pos)
    conf.reconf(ser, width=conf.width + i,height=500 +i*6)
    conf = read_configs(ser)
    print(conf, conf.width, conf.height)

"""

