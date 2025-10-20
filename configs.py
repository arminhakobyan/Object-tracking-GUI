import time
import json
import serial



class Configurations:
    def __init__(self, threshold: int, direction_threshold: int, autocorr_threshold: int,
            match_size: int, track_frame_width: int, track_frame_height: int, track_coord_x: int, track_coord_y: int):

        self.threshold = threshold
        self.direction_threshold = direction_threshold
        self.autocorr_threshold = autocorr_threshold
        self.match_size = match_size
        self.track_frame_width = track_frame_width
        self.track_frame_height = track_frame_height
        self.track_coord_x = track_coord_x
        self.track_coord_y = track_coord_y


    def to_dict(self):
        return {
            "threshold": self.threshold,
            "direction_threshold": self.direction_threshold,
            "autocorr_threshold": self.autocorr_threshold,
            "match_size": self.match_size,
            "track_frame_width":  track_frame_width,
            "track_frame_height":  track_frame_height,
            "track_coord_x": track_coord_x,
            "track_coord_y": track_coord_y
        }

    def get_config(self, name: str):
        if name == "threshold":
            return self.threshold
        elif name == "direction_threshold":
            return self.direction_threshold
        elif name == "autocorr_threshold":
            return self.autocorr_threshold
        elif name == "match_size":
            return self.match_size




    def set_coord_x(self, x):
        self.track_coord_x = x

    def set_coord_y(self, y):
        self.track_coord_y = y

    def set_threshold(self, thr: int):
        self.threshold = thr

    def set_direction_threshold(self, dir_thr: int):
        self.direction_threshold = dir_thr

    def set_autocorr_threshold(self, auto_thr: int):
        self.autocorr_threshold = auto_thr

    def set_match_size(self, m_size: int):
        self.match_size = m_size

    def set_track_frame_width(self, width):
        self.track_frame_width = width

    def set_track_frame_height(self, height):
        self.track_frame_height = height

    def to_json(self):
        return json.dumps(self.to_dict())

    def write_to_serial(self, uart_ser):
        json_repr = self.to_json()

        uart_ser.write(bytes([0xff]))

        for char in json_repr:
            uart_ser.write(char.encode())
            time.sleep(0.001)

        uart_ser.write(bytes([0xff]))









