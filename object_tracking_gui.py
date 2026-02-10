from PyQt5 import QtGui
import sys
import cv2
import time
import json
import pygame
import os
from collections import deque
from multiprocessing import Process
import numpy as np
import socket
import copy
from math import ceil
from traceback import print_exc
from serial import Serial
from serial.tools import list_ports
from serial import SerialException, SerialTimeoutException
from threading import Thread
from difflib import SequenceMatcher
from functools import partial
from ast import literal_eval
from joystickclass import JoystickThread
from cv2_enumerate_cameras import enumerate_cameras
from configs_classes import Inputs, read_inputs, write_response_to_serial
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QKeyEvent, QMovie, QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QAction,
    QMenuBar,
    QStatusBar,
    QFrame,
    QPushButton,
    QComboBox,
    QCheckBox,
    QRadioButton,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QDialogButtonBox,
    QPlainTextEdit,
    QDockWidget,
)


def write_log(text: str, filename="device_log.txt"):
    with open(filename, "a") as f:     # encoding="utf-8"
        f.write(text + "\n")


"""
def write_log(text: str, filename="device_log.txt"):
    print("writing in log file")
    try:
        f = open(filename, 'a')
        f.write(text + "\n")
        f.flush()

    except FileNotFoundError:
        print(f"Error: The file {filename} was not found.")
    except PermissionError:
        print(f"Error: Permission denied. Unable to access {filename} file.")
    except Exception as e:
        # Catch any other unexpected exceptions
        print(f"An unexpected error occurred: {e}")
"""


def clear_log(filename="device_log.txt"):
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        open(filename, "w").close()  # clear the content

def is_bluetooth_port(port_info):
    text = port_info.description.lower()
    return "bluetooth" in text

def list_open_com_ports():     # skip bluetooth ports
    ports = list_ports.comports()
    open_ports = []
    for port in ports:
        if is_bluetooth_port(port):
            continue
        else:
            open_ports.append(port.device)
    return open_ports


def write_to_serial(ser, js):
    print("write_to_serial", js)
    #ser.write(bytes([0xff]))

    for char in js:
        ser.write(char.encode())
        time.sleep(0.0001)

    #ser.write(bytes([0xff]))


class Toggle(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QCheckBox {
                spacing: 6px;
                min-width: 40px;
                min-height: 20px;
                border-radius: 10px;
                background: #888888;
                padding-left: 2px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background: white;
                margin: 2px 0 0 2px;
            }
            QCheckBox:checked {
                background: #4CAF50;
                padding-left: 22px;
            }
            QCheckBox:unchecked {
                background: #888888;
                padding-left: 2px;
            }
        """)


class VideoCaptureThread(QThread):
    change_frame_signal = pyqtSignal(np.ndarray)
    camera_ready_signal = pyqtSignal()

    def __init__(self, index, api_pref, default_frame=None):
        super().__init__()
        self._index = index
        self._api_pref = api_pref
        self._default_frame = default_frame.copy() if default_frame is not None else None
        self.running = True

        if index is not None:
            self.video_capture = cv2.VideoCapture(self._index, self._api_pref)
            self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        else:
            self.video_capture = None


    def get_index(self):
        return self._index

    def run(self):
        self.running = True
        if self.video_capture and self.video_capture.isOpened():
            while self.running:
                ret, frame = self.video_capture.read()
                if ret:
                    self.change_frame_signal.emit(frame)
                else:
                    if self._default_frame is not None:
                        self.change_frame_signal.emit(self._default_frame)
                    self.msleep(30)
        else:
            while self.running:
                if self._default_frame is not None:
                    self.change_frame_signal.emit(self._default_frame)
                self.msleep(30)


    def stop(self):
        self.running = False
        self.wait()
        if self.video_capture:
            self.video_capture.release()
            self.video_capture = None


class SerialThread(QThread):
    received_data_signal = pyqtSignal(str)
    send_text_signal = pyqtSignal(str)
    send_bytes_signal = pyqtSignal(bytes)
    send_joystick_coordinates_with_interval = pyqtSignal(str, str)
    send_joystick_coordinates = pyqtSignal(str, str)


    def __init__(self, ser):
        super().__init__()
        self.serial = ser
        self.running = True
        self.first_open = True
        self.coord_last_sent = 0
        self.coord_send_interval = 0.03   # 60 hz

        self.send_text_signal.connect(self.send_text_data)
        self.send_bytes_signal.connect(self.send_bytes_data)
        self.send_joystick_coordinates.connect(self.send_joystick_coord)
        self.send_joystick_coordinates_with_interval.connect(self.send_joystick_coord_with_interval)
        print("SerialThread initialized")


    """
    def run(self):
        print("run()")
        while self.running:
            try:
                #data = self.serial.read(self.serial.in_waiting or 1)
                data = self.serial.read(1024)
                if data:
                    text = data.decode("utf-8", errors="ignore")
                    self.received_data_signal.emit(text)

            except serial.SerialException:
                break
    """

    def run(self):
        buffer = bytearray()

        while self.running:
            try:
                data = self.serial.read(1024)  # waits up to timeout
                if not data:
                    continue

                buffer.extend(data)

                text = buffer.decode("utf-8", errors="ignore")
                buffer.clear()
                self.received_data_signal.emit(text)

            except serial.SerialException:
                break



    def send_joystick_coord_with_interval(self, json_x, json_y):
        now = time.time()
        if now - self.coord_last_sent >= self.coord_send_interval:
            self.send_joystick_coord(json_x, json_y)


    def send_joystick_coord(self, json_x, json_y):
        now = time.time()
        self.send_text_data(json_x)
        self.send_text_data(json_y)
        self.coord_last_sent = now


    @pyqtSlot(str)
    def send_text_data(self, js_data):
        try:
            write_to_serial(ser=self.serial, js=js_data)
            print(f"Sent text data: {js_data}")  # Debug log
        except Exception as e:
            print(f"Send Error: {e}")


    @pyqtSlot(bytes)
    def send_bytes_data(self, bytes_data):
        print("send bytes data")
        print(bytes_data)
        try:
            if self.serial is None or not self.serial.is_open:
                print("Serial port not open or not connected.")
                return
            self.serial.write(bytes_data)  # Send raw bytes
            print(f"Sent bytes: {bytes_data.hex()}")  # debug the hex
        except BaseException as e:
            print("Caught exception in send_bytes_data:")
            print(f"{type(e).__name__}: {e}")
            # traceback.print_exc()


    def stop(self):
        self.running = False
        self.serial.close()
        self.quit()


def get_available_cameras():
    cameras = []
    for camera_info in enumerate_cameras(cv2.CAP_DSHOW):  # cv2.CAP_MSMF
        cameras.append((camera_info.name, camera_info.index, camera_info.backend))

    return cameras



class MainApp(QMainWindow):
    def __init__(self):
        super(MainApp, self).__init__()

        self.setWindowTitle("Camera Recorder")
        geometry = app.desktop().availableGeometry()
        self.setGeometry(geometry)

        self.video_label = QLabel(self)
        self.video_label_deviation = [50, 50]
        self.video_label.setGeometry(self.video_label_deviation[0], self.video_label_deviation[1], 960, 540)
                                        # h     w    ch
        self.gray_frame = np.full((1080, 1920, 3), 128, dtype=np.uint8)    # was (1920,1080, 3) VARDAN
        self.gray_pixmap = QtGui.QPixmap(self.video_label.width(), self.video_label.height())
        self.gray_pixmap.fill(Qt.darkGray)
        self.video_label.setPixmap(self.gray_pixmap)

        self.video_thread = VideoCaptureThread(index=None, api_pref=None, default_frame=self.gray_frame)
        self.video_thread.camera_ready_signal.connect(self.hide_loading)
        self.video_thread.change_frame_signal.connect(self.update_frame)
        self.video_thread.start()
        print("self.video_thread", self.video_thread)

        self.stabilization_label = QLabel('Stabilization', self)
        self.stabilization_label.setGeometry(910, 15, 100, 30)
        self.stabilization_toggle = Toggle(self)
        self.stabilization_toggle.setGeometry(970, 20, 10, 5)
        self.stabilization_toggle.stateChanged.connect(self.stabilization_on_off)
        self.stabilization_label.hide()
        self.stabilization_toggle.hide()

        self.tracking_label = QLabel('Tracking', self)
        self.tracking_label.setGeometry(795, 15, 100, 30)
        self.tracking_toggle = Toggle(self)
        self.tracking_toggle.setGeometry(840, 20, 10, 5)
        self.tracking_toggle.stateChanged.connect(self.tracking_on_off)
        self.tracking_label.hide()
        self.tracking_toggle.hide()

        self.motion_label = QLabel('Motion', self)
        self.motion_label.setGeometry(670, 15, 100, 30)
        self.motion_toggle = Toggle(self)
        self.motion_toggle.setGeometry(710, 20, 10, 5)
        self.motion_toggle.stateChanged.connect(self.motion_on_off)
        self.motion_label.hide()
        self.motion_toggle.hide()

        self.tracking_coord_label = QLabel("Number of tracking coordinates:", self)
        self.tracking_coord_label.setGeometry(800, 595, 150, 30)
        self.tracking_coord_editline = QLineEdit(self)
        self.tracking_coord_editline.setGeometry(970, 600, 40, 20)
        self.tracking_coord_editline.setReadOnly(True)
        # self.tracking_coord_editline.textChanged.connect(self.report_tracking_coord_count)
        self.tracking_coord_editline.setText('0')

        self.temperature_label = QLabel("Temperature", self)
        self.temperature_label.setGeometry(885, 625, 70, 30)
        self.temperature_line_edit = QLineEdit(self)
        self.temperature_line_edit.setGeometry(970, 630, 40, 20)
        self.temperature_line_edit.setReadOnly(True)
        self.temperature_line_edit.setText('0')
        self.tracking_coord_label.hide()
        self.tracking_coord_editline.hide()
        self.temperature_label.hide()
        self.temperature_line_edit.hide()

        self.available_cameras_label = QLabel(self)
        self.available_cameras_label.setText("Available Cameras:")
        self.available_cameras_label.setGeometry(140, 700, 150, 30)

        self.open_camera_button = QPushButton("Open camera", self)
        self.open_camera_button.setGeometry(110, 800, 150, 30)
        self.open_camera_button.setEnabled(True)
        self.open_camera_button.clicked.connect(self.open_camera)

        self.start_button = QPushButton("Start Recording", self)

        self.start_button.setGeometry(270, 800, 150, 30)
        self.start_button.clicked.connect(self.start_recording)
        self.start_button.setEnabled(False)

        self.stop_button = QPushButton("Stop Recording", self)
        self.stop_button.setGeometry(430, 800, 150, 30)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)

        self.save_records_button = QPushButton("Save", self)
        self.save_records_button.setGeometry(590, 800, 150, 30)
        self.save_records_button.setEnabled(False)
        self.save_records_button.clicked.connect(self.save_video)

        self.close_camera_button = QPushButton("Close camera", self)
        self.close_camera_button.setGeometry(750, 800, 150, 30)
        self.close_camera_button.setEnabled(False)
        self.close_camera_button.clicked.connect(self.close_camera)

        self.configurations_window_btn = QPushButton("Configurations", self)
        self.configurations_window_btn.setGeometry(1650, 250, 150, 50)
        self.configurations_window_btn.hide()
        self.configurations_window_btn.clicked.connect(self.show_configurations)
        self.configs_window = None

        # buffer for point coordinates
        self.coords_buffer = deque()

        self.buffer_data = ""              # received text will be saved here
        self.buffer_deque_data = deque()   # here I append anything received - within { }, to be complete config params or coordinates

        self.serial_thread = None
        self.video_writer = None
        self.is_recording = False
        self.camera_closed = False
        self.input_data_json = None
        self.recorded_frames = []
        self.camera_buttons = []
        self.selected_camera = 0
        self.track_frame_size = [150, 150]  # height, width
        self.resized_frame_shape = [540, 960]   # original is- 1080 X 1920 -  frame[y][x] shape = height, width
        self.track_video = None
        self.track_region = None
        self.current_frame = None
        self.pixmap = None
        self.img = None
        self.cursor_x = None
        self.cursor_y = None
        self.cursor_x_in_original_frame = None
        self.cursor_y_in_original_frame = None
        self.ret = None
        self.baud_rate = 115200
        self.original_frame_shape = None
        self.coords_in_original_frame = None
        self.scale_x = 2  #None
        self.scale_y = 2  #None
        self.pointers_buffer = deque()
        self.pointer_coord = None
        self.log_file = "device_log.txt"
        self.buffer_log = ""
        # for track_coordinates_number and temperature widgets
        self.show_widgets = False

        # in this file will be written only tracking coordinates, without any text, just the numbers - {x},  {y}
        # it is special for Armen :)))
        self.coordinates_log = ""
        self.coordinates_log_file = "coordinates_log.txt"

        self.log_file_timer = QTimer(self)
        self.log_file_timer.setInterval(10_000)  # 10 seconds
        self.log_file_timer.timeout.connect(self.flush_logs)

        self.device_id = [i for i in range(10001, 10016)]   # 10001-10015         #1234567890
        self.device_id.append(1234567890)

        self.configs = {}
        self.configs_window = None
        self.first_log = True

        self.tracking_coord_count = 0
        self.receiving_tracking_coord_timer = QTimer(self)
        self.receiving_tracking_coord_timer.setInterval(10_000)  # 10 seconds
        self.receiving_tracking_coord_timer.timeout.connect(self.report_tracking_coord_count)

        self.temperature_timer = QTimer(self)
        self.temperature_timer.setInterval(10_000)
        self.temperature_timer.timeout.connect(self.report_temperature)

        self.joystick_pointers_count = 0
        self.joystick_stopped = False

        self.mouse_as_joystick = False
        self.last_mouse_pos = None
        self.mouse_pressed = False

        self.cameras_combobox = QComboBox(self)
        self.cameras_combobox.setGeometry(250, 705, 160, 30)
        self.available_cameras = get_available_cameras()
        self.update_cameras_widget()
        self.cameras_combobox.currentIndexChanged.connect(self.select_camera)

        self.cameras_thread = Thread(target=self.check_available_cameras, daemon=True)
        self.cameras_thread.start()

        self.open_ports_label = QLabel("Open Ports:", self)
        self.open_ports_label.setGeometry(1500, 50, 150, 50)
        self.ports_combobox = QComboBox(self)
        self.ports_combobox.setGeometry(1600, 60, 80, 30)

        self.open_ports = list_open_com_ports()
        print("open ports:", self.open_ports)
        self.update_ports_widget()
        self.selected_port = 0
        self.ports_combobox.currentIndexChanged.connect(self.select_port)

        self.connect_btn = QPushButton(self)
        self.connect_btn.setText("Connect")
        self.connect_btn.setGeometry(1700, 60, 100, 30)
        self.connect_btn.clicked.connect(self.connect_port)

        self.ports_thread = Thread(target=self.check_available_ports, daemon=True)
        self.ports_thread.start()
        self.port_connected = False
        self.port_connection_messagebox = QMessageBox()
        self.port_connection_messagebox.setText("Port couldn't connect!!!")

        for i in range(len(self.open_ports)):
            try:
                print(self.open_ports[i])
                self.ser = Serial(self.open_ports[i], self.baud_rate, timeout=1)
                self.selected_port = i
                self.ports_combobox.setCurrentIndex(i)
                break
            except Exception as e:
                print(e)

        self.track_video_label = QLabel(self)
        self.track_video_label_x = 1070
        self.track_video_label_y = 50

        self.pointer = QLabel(self)
        self.pointer.setFixedSize(10, 10)  # (0, 0)
        self.pointer.setStyleSheet("background-color: red; border-radius: 5px;")
        self.pointer.move(self.video_label_deviation[0], self.video_label_deviation[1])

        # Start joystick thread
        self.joystick_thread = JoystickThread()

        self.joystick_thread.axis_changed.connect(self.send_joystick_coords)
        self.joystick_thread.started_moving.connect(self.start_joystick_motion)

        self.joystick_thread.stopped_moving.connect(self.stop_joystick_motion)
        self.joystick_thread.button_pushed.connect(self.handle_joystick_button)

        self.pointer_pos = [self.video_label_deviation[0], self.video_label_deviation[1]]



    def keyPressEvent(self, event):
        if event.key() == Qt.Key_T:
            self.mouse_as_joystick = not self.mouse_as_joystick
            print("Mouse joystick mode:", self.mouse_as_joystick)
        elif event.key() == Qt.Key_H:
            if not self.show_widgets:
                self.tracking_coord_label.show()
                self.tracking_coord_editline.show()
                self.temperature_label.show()
                self.temperature_line_edit.show()
                self.show_widgets = True
            else:
                self.tracking_coord_label.hide()
                self.tracking_coord_editline.hide()
                self.temperature_label.hide()
                self.temperature_line_edit.hide()
                self.show_widgets = False


    def mouseReleaseEvent(self, event):
        if self.mouse_as_joystick and event.button() == Qt.LeftButton:
            self.mouse_pressed = False
            self.last_mouse_pos = None


    def stabilization_on_off(self, state):
        print("ON" if state else "OFF")
        st = 1 if state else 0
        if self.serial_thread:
            stab_json = json.dumps({'stabilization': st})
            self.serial_thread.send_text_signal.emit(stab_json)
            #request param
            to_json = json.dumps({"stabilization": "%"})
            self.serial_thread.send_text_signal.emit(to_json)
            #time.sleep(0.01)
            #will be refreshed in self.configs in the function - receive_data_from_serial


    def update_stabilization_toggle(self, state):
        print("update_stabilization_toggle")
        self.stabilization_toggle.blockSignals(True)
        self.stabilization_toggle.setChecked(bool(state))
        self.stabilization_toggle.blockSignals(False)


    def tracking_on_off(self, state):
        print("ON" if state else "OFF")
        st = 1 if state else 0
        if self.serial_thread:
            tr_json = json.dumps({'tracking': st})
            self.serial_thread.send_text_signal.emit(tr_json)
            if st and not self.receiving_tracking_coord_timer.isActive():
                self.tracking_coord_count = 0
                self.receiving_tracking_coord_timer.start()
            else:
                self.receiving_tracking_coord_timer.stop()
                self.tracking_coord_editline.setText('0')
                self.tracking_coord_count = 0
            to_json = json.dumps({"tracking": "%"})
            self.serial_thread.send_text_signal.emit(to_json)
            #time.sleep(0.001)


    def update_tracking_toggle(self, state):
        print("update_tracking_toggle")
        self.tracking_toggle.blockSignals(True)
        self.tracking_toggle.setChecked(bool(state))
        self.tracking_toggle.blockSignals(False)


    def motion_on_off(self, state):
        print("Motion ON" if state else "Motion OFF")
        st = 1 if state else 0
        if self.serial_thread:
            stab_json = json.dumps({'motion_det': st})
            self.serial_thread.send_text_signal.emit(stab_json)
            # request param
            to_json = json.dumps({"motion_det": "%"})
            self.serial_thread.send_text_signal.emit(to_json)
            time.sleep(0.001)
            # will be refreshed in self.configs in the function - receive_data_from_serial


    def update_motion_toggle(self, state):
        print("update_motion_toggle")
        self.motion_toggle.blockSignals(True)
        self.motion_toggle.setChecked(bool(state))
        self.motion_toggle.blockSignals(False)


    def mousePressEvent(self, event):
        if self.mouse_as_joystick:
            if event.button() == Qt.LeftButton:
                #self.click_on(event)
                mouse_x = event.x()
                mouse_y = event.y()

                target_x = mouse_x - 5 - self.video_label_deviation[0]
                target_y = mouse_y - 5 - self.video_label_deviation[1]
                dx = (target_x - self.pointer_pos[0]) / 5
                dy = (target_y - self.pointer_pos[1]) / 5

                self.send_joystick_coords(dx, dy)
                self.mouse_pressed = True
            elif event.button() == Qt.RightButton:
                self.handle_joystick_button(0)


    def stop_joystick_motion(self, dx, dy):
        self.joystick_stopped = True
        pointer_x, pointer_y  = self.update_joystick_pointer(dx, dy)
        if self.serial_thread:
            print("latest coordinate is sent")
            x_json = json.dumps(pointer_x)
            y_json = json.dumps(pointer_y)
            self.serial_thread.send_joystick_coordinates.emit(x_json, y_json)


    def start_joystick_motion(self):
        print("started joystick")
        self.joystick_stopped = False


    def mouseMoveEvent(self, event):
        if self.mouse_as_joystick and event.buttons() & Qt.LeftButton:
            # Get mouse position relative to widget
            mouse_x = event.x()
            mouse_y = event.y()

            target_x = mouse_x - 5 - self.video_label_deviation[0]
            target_y = mouse_y - 5 - self.video_label_deviation[1]
            dx = (target_x - self.pointer_pos[0]) / 5    # speed=5
            dy = (target_y - self.pointer_pos[1]) / 5

            self.send_joystick_coords(dx, dy)


    def update_joystick_pointer(self, dx, dy):
        self.joystick_pointers_count += 1
        speed = 5

        self.pointer_pos[0] += dx * speed
        self.pointer_pos[1] += dy * speed

        # self.resized_frame_shape = [540, 960]- y, x - height, width
        self.pointer_pos[0] = max(-5, min(self.resized_frame_shape[1] - 5, self.pointer_pos[0]))
        self.pointer_pos[1] = max(-5, min(self.resized_frame_shape[0] - 5, self.pointer_pos[1]))

        self.pointer_move(coord_x = int(self.pointer_pos[0] + self.video_label_deviation[0]), coord_y = int(self.pointer_pos[1]+self.video_label_deviation[1]))

        pointer_x = {'cursor_x': int(((self.pointer_pos[0] + 5) * self.scale_x))}
        pointer_y = {'cursor_y': int(((self.pointer_pos[1] + 5) * self.scale_y))}

        self.pointer_coord = {'cursor_x': int(((self.pointer_pos[0] + 5) * self.scale_x)),
                              'cursor_y': int(((self.pointer_pos[1] + 5) * self.scale_y))}

        self.pointers_buffer.append(self.pointer_coord)

        return pointer_x, pointer_y


    def pointer_move(self, coord_x:int, coord_y:int):
        self.pointer.move(coord_x, coord_y)


    def send_joystick_coords(self, dx, dy):
        pointer_x, pointer_y = self.update_joystick_pointer(dx, dy)
        x = pointer_x['cursor_x']
        y = pointer_y['cursor_y']
        if self.serial_thread:
            x_json = json.dumps(pointer_x)
            y_json = json.dumps(pointer_y)
            if not self.joystick_stopped:
                self.serial_thread.send_joystick_coordinates_with_interval.emit(x_json, y_json)
                if self.configs_window:
                    self.configs_window.change_parameter_value(x, "cursor_x")
                    self.configs_window.change_parameter_value(y, "cursor_y")


    def handle_joystick_button(self, i: int):
        if i == 0:
            print("joystick button pushed")
            if self.pointer_coord:
                x = self.pointer_coord['cursor_x']
                y = self.pointer_coord['cursor_y']
                self.cursor_x = self.pointer_coord['cursor_x']/self.scale_x + self.video_label_deviation[0] + 5
                self.cursor_y = self.pointer_coord['cursor_y']/self.scale_y + self.video_label_deviation[1] + 5
                x_json = json.dumps({'track_x': x})
                y_json = json.dumps({'track_y': y})
                if self.serial_thread and self.configs_window:
                    self.serial_thread.send_joystick_coordinates.emit(x_json, y_json)
                    self.configs_window.change_parameter_value(x, 'track_x')
                    self.configs_window.change_parameter_value(y, 'track_y')
                    self.configs_window.request_one_parameter(param_name='track_x')
                    self.configs_window.request_one_parameter(param_name='track_y')
                    self.configs_window.request_one_parameter(param_name='cursor_x')
                    self.configs_window.request_one_parameter(param_name='cursor_y')
        elif i == 1:
            print("RIGHT button pushed")
        elif i == 2:
            print("LB button pushed")
        elif i == 3:
            print("RB button pushed")
        elif i == 4:
            print("SELECT button pushed")
            print("poiner position in original frame: ", int(self.pointer_pos[0] * self.scale_x),
                  int(self.pointer_pos[1] * self.scale_y))
        elif i == 5:
            print("START button pushed")
        else:
            print("Unknown button")


    def check_available_cameras(self):
        while True:
            time.sleep(3)  # poll every 3 seconds
            new_cameras = get_available_cameras()
            if not equal_lists(new_cameras, self.available_cameras):
                print(True)
                self.available_cameras = new_cameras
                self.update_cameras_widget()


    def update_cameras_widget(self):
        if len(self.available_cameras) != 0:
            self.cameras_combobox.clear()
            for i in range(len(self.available_cameras)):
                self.cameras_combobox.addItem(f"Camera {self.available_cameras[i][0]}")
            self.cameras_combobox.setCurrentIndex(0)


    def select_camera(self, ind):
        self.selected_camera = ind
        print(self.available_cameras[self.selected_camera])
        self.open_camera_button.setEnabled(True)


    def hide_loading(self):
        self.loading_movie.stop()
        self.loading_label.hide()


    def open_camera(self):
        self.camera_closed = False
        self.start_button.setEnabled(True)
        self.close_camera_button.setEnabled(True)

        print("self.video_thread", self.video_thread)

        if self.video_thread is not None:  # and self.video_thread.get_index() != self.available_cameras[self.selected_camera][1]:
            self.video_thread.stop()
            self.video_thread = None
        if self.video_label:
            self.video_label.clear()
        if self.track_video_label:
            self.track_video_label.clear()

        ind = self.available_cameras[self.selected_camera][1]
        api_pref = self.available_cameras[self.selected_camera][2]

        self.video_thread = VideoCaptureThread(index=ind, api_pref=api_pref, default_frame=None)

        self.video_thread.camera_ready_signal.connect(self.hide_loading)
        self.video_thread.change_frame_signal.connect(self.update_frame)

        self.video_thread.start()


    @pyqtSlot(np.ndarray)
    def update_frame(self, frame):
        if self.video_thread is not None:
            self.original_frame_shape = frame.shape  # height-Y, width-X, ch - BGR
            frame = cv2.resize(frame, (self.resized_frame_shape[1], self.resized_frame_shape[0]))  #dsize = (new_width, new_height)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                                #     w                h
            img = QtGui.QImage(frame.tobytes(), frame.shape[1], frame.shape[0], frame.shape[1] * frame.shape[2],
                               QtGui.QImage.Format_RGB888)
            self.video_label.setPixmap(QtGui.QPixmap.fromImage(img))

            self.scale_x = self.original_frame_shape[1] / self.resized_frame_shape[1]  # width,   becuase frame_shape[1]=width
            self.scale_y = self.original_frame_shape[0] / self.resized_frame_shape[0]  # height           frame_shape[0]=height
            x = 0
            y = 0
            if self.configs_window:
                x = self.configs['track_x'] / self.scale_x
                y = self.configs['track_y'] / self.scale_y

                ui_stab_state = self.stabilization_toggle.isChecked()
                configs_stab = self.configs['stabilization']
                if bool(configs_stab) != ui_stab_state:
                    self.update_stabilization_toggle(configs_stab)

                ui_track_state = self.tracking_toggle.isChecked()
                configs_track = self.configs['tracking']
                if bool(configs_track) != ui_track_state:
                    self.update_tracking_toggle(configs_track)
                if bool(configs_track) and not self.receiving_tracking_coord_timer.isActive():
                    self.tracking_coord_count = 0
                    self.receiving_tracking_coord_timer.start()

                ui_motion_state = self.motion_toggle.isChecked()

                motion_track = self.configs['motion_det']
                if bool(motion_track) != ui_motion_state:
                    self.update_motion_toggle(motion_track)

            if self.configs and x and y:
                track_windw_size = self.configs['track_wndw_size']
                self.track_frame_size = [track_windw_size, track_windw_size]

                x_start = int(max(0, int(x- track_windw_size/4)))
                x_end = int(
                    min(self.resized_frame_shape[1], int(x + 3/4*track_windw_size  )))
                y_start = int(max(0, int(y- track_windw_size/4)))
                y_end = int(
                    min(self.resized_frame_shape[0], int(y + 3/4*track_windw_size)))

                self.track_video = frame[y_start:y_end, x_start:x_end]

                if self.track_video.size > 0:
                    h, w, ch = self.track_video.shape
                    bytes_per_line = ch * w
                    self.track_video_label.setPixmap(QtGui.QPixmap.fromImage(QtGui.QImage(self.track_video.tobytes(),
                                                                                          w, h, bytes_per_line,
                                                                                          QtGui.QImage.Format_RGB888)))
                    self.track_video_label.setGeometry(self.track_video_label_x, self.track_video_label_y,
                                                       track_windw_size, track_windw_size)  # x, y, w, h
            if self.track_frame_size == [0, 0] and self.track_video_label is not None:
                self.track_video_label.clear()

            if self.is_recording:
                self.recorded_frames.append(frame)
            self.current_frame = frame



    def start_recording(self):
        self.recorded_frames = []
        self.is_recording = True
        self.open_camera_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.save_records_button.setEnabled(False)


    def stop_recording(self):
        self.is_recording = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.save_records_button.setEnabled(True)
        self.open_camera_button.setEnabled(True)


    def save_video(self):
        print("save recorded video")
        if len(self.recorded_frames) == 0:
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Save Video", "", "mp4 Files (*.mp4v)")   # (*.mp4v)
        if filename:
            fshape = self.recorded_frames[0].shape
            fheight = int(fshape[0])
            fwidth = int(fshape[1])
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')        # (*.mp4v)
            self.video_writer = cv2.VideoWriter(filename, fourcc, 15, (fwidth, fheight), True)
            for frame in self.recorded_frames:
                self.video_writer.write(frame)
            self.video_writer.release()
            self.recorded_frames = []

        print("video saved!")


    def select_port(self, ind):
        self.selected_port = ind

    def get_selected_port(self):
        print("get_selected_port")
        return self.ports_combobox.currentText()


    def update_ports_widget(self):
        if len(self.open_ports) != 0:
            self.ports_combobox.clear()
            for i in range(len(self.open_ports)):
                self.ports_combobox.addItem(self.open_ports[i])
        self.ports_combobox.setCurrentIndex(0)


    def check_available_ports(self):
        while True:
            time.sleep(3)
            new_ports = list_open_com_ports()
            if not equal_lists(new_ports, self.open_ports):
                self.open_ports = new_ports
                print(new_ports)

                self.update_ports_widget()


    def check_port_connection(self, port, baud_rate=115200):
        try:
            if self.ser:
                self.ser.close()
        except Exception as e:
            print(e)
        try:
            self.ser = Serial(port, int(baud_rate), timeout=0, write_timeout=0.1)                 #timeout=1)
            self.ser.close()
            self.ser.open()
            self.port_connected = True
            return True
        except Exception as e:
            print(e)
            QMessageBox.warning(self, "Error", f"{e}")
            return False


    def connect_port(self):
        if self.port_connected and self.ser is not None and self.ser.is_open:
            # send 'D' - Disconnect
            self.ser.write(bytes([0x44]))
            time.sleep(0.3)
            if self.configs_window:
                self.configs_window.hide()                                   # self.console.configs_window.timer.stop()
                self.configs_window = None
        else:
            port = self.get_selected_port()

            check_port = self.check_port_connection(port, self.baud_rate)
            print("check port", check_port)
            try:
                if check_port:
                    # send 'I' - request for device_id
                    self.ser.write(bytes([0x49]))
                    response = ""
                    attempt = 0

                    while attempt < 10:
                        attempt += 1
                        time.sleep(0.5)
                        my_list = []

                        while self.ser.in_waiting > 0:
                            d = self.ser.read()
                            my_list.append(d)
                            time.sleep(0.01)

                        if my_list:
                            response = "".join([i.decode("utf-8", errors="ignore") for i in my_list]).strip()
                            try:
                                js = json.loads(response)
                            except json.JSONDecodeError:
                                response = ""  # reset so we know it's not valid yet
                                continue
                            break
                    if not response:
                        print(f"No device id received after {attempt} attempts ({attempt * 0.5:.1f}s).")
                        QMessageBox.warning(self, "Error", "Device did not confirm connection.")
                        self.ser.close()
                        try:
                            self.connect_btn.setText("Connect")
                        except Exception:
                            pass
                        return  # or raise/handle as you need

                    print("received", response)
                    js = json.loads(response)
                    print(js.get('device_id'))

                    if js.get('device_id') in self.device_id:
                        # send 'C' - Connected
                        self.ser.write(bytes([0x43]))
                        confirmation = ""
                        attempt = 0
                        while attempt < 10:
                            attempt += 1
                            time.sleep(0.5)
                            my_list1 = []
                            max_list_len = 11
                            while self.ser.in_waiting > 0 and max_list_len > 0:
                                d = self.ser.read()
                                my_list1.append(d)
                                max_list_len-=1
                                time.sleep(0.01)

                            if my_list1:
                                confirmation = "".join(
                                    [i.decode("utf-8", errors="ignore") for i in my_list1]).strip()

                                if "connected".lower() in confirmation.lower() or "Connected" in confirmation:
                                    break
                                else:
                                    # received data but not the confirmation text yet -> continue attempts
                                    confirmation = ""
                                    continue
                        if not confirmation:
                            print(f"No confirmation received after {attempt} attempts ({attempt * 0.5:.1f}s).")
                            QMessageBox.warning(self, "Error", "Device did not confirm connection.")
                            self.ser.close()
                            try:
                                self.connect_btn.setText("Connect")
                            except Exception:
                                pass
                            return  # or raise/handle

                        if "Connected" in confirmation or "connected" in confirmation.lower():
                            self.connect_btn.setText("Disconnect")
                            self.port_connected = True
                            self.serial_thread = SerialThread(self.ser)
                            self.serial_thread.received_data_signal.connect(self.receive_data_from_serial)
                            self.serial_thread.start()
                            time.sleep(0.1)

                            configs_json = json.dumps({"parameters": "%"})
                            self.serial_thread.send_text_signal.emit(configs_json)

                            self.joystick_thread.start()
                            self.log_file_timer.start()
                    else:
                        QMessageBox.critical(self, "Error", "Device Id doesn't match")

            except SerialException as e:
                QMessageBox.critical(self, "Error", "Invalid port.")
                print("Serial port error:", e)
                if self.ser and self.ser.is_open:
                    self.ser.close()

            except Exception as e:
                print("Unexpected error:", e)
                QMessageBox.critical(self, "Error", "Invalid response from device.")
                if self.ser and self.ser.is_open:
                    self.ser.close()


    def receive_data_from_serial(self, text):
        if self.first_log:
            clear_log(filename = self.log_file)
            clear_log(filename = self.coordinates_log_file)
            self.first_log = False
        #write_log(text=text, filename = self.log_file)
        self.buffer_log += text
        if "Disconnect" in text:
            self.connect_btn.setText("Connect")
            self.port_connected = False
            self.configurations_window_btn.hide()
            self.update_motion_toggle(0)
            self.update_tracking_toggle(0)
            self.update_stabilization_toggle(0)
            self.stabilization_label.hide()
            self.stabilization_toggle.hide()
            self.tracking_label.hide()
            self.tracking_toggle.hide()
            self.motion_label.hide()
            self.motion_toggle.hide()
            self.track_video_label.hide()
            if self.temperature_timer.isActive():
                self.temperature_timer.stop()
            self.temperature_line_edit.setText('0')
            if self.receiving_tracking_coord_timer.isActive():
                self.receiving_tracking_coord_timer.stop()
            self.tracking_coord_editline.setText('0')
            self.flush_logs()
            self.buffer_data = ''
            f = open(self.log_file, 'a')
            f.close()
            fl = open(self.coordinates_log_file, "a")
            fl.close()
            try:
                self.serial_thread.stop()
                self.serial_thread = None
                self.ser.close()
                print("disconnected")
                return
            except EOFError as e:
                print(e)


        self.buffer_data += text
        print("buffer: ", self.buffer_data)

        if "{" in self.buffer_data and "}" in self.buffer_data and '[Config]' in self.buffer_data:
            st = self.buffer_data.index('{')
            end = self.buffer_data.index('}') + 1
            t = self.buffer_data[st:end]

            self.configs = json.loads(t)
            configs_for_win = copy.copy(self.configs)
            if 'tracking' in configs_for_win:
                del configs_for_win['tracking']
            if 'stabilization' in configs_for_win:
                del configs_for_win['stabilization']
            if 'motion_det' in configs_for_win:
                del configs_for_win['motion_det']
            if 'temperature' in configs_for_win:
                tmp = round(configs_for_win['temperature'])
                self.temperature_line_edit.setText(str(tmp))
                del configs_for_win['temperature']
            if self.configs_window is None:
                self.configurations_window_btn.show()
                self.configs_window = ConfigurationsWindow(configs_dict=configs_for_win, ser_th=self.serial_thread)
                self.configs_window.show()
                self.stabilization_label.show()
                self.stabilization_toggle.show()
                self.tracking_label.show()
                self.tracking_toggle.show()
                self.motion_label.show()
                self.motion_toggle.show()
                self.configs_window.show()
                self.track_video_label.show()
                self.temperature_timer.start()
            else:
                json_string = json.dumps(configs_for_win)
                self.configs_window.fill_get_fields(json_string)
            self.buffer_data = self.buffer_data.replace(t, "")
            self.buffer_data = self.buffer_data.replace("[Config]", "")
            self.buffer_data = self.buffer_data.replace(']', "")

        while '{' in self.buffer_data and '}' in self.buffer_data:
            ind1 = self.buffer_data.index('{')
            ind2 = self.buffer_data.index('}') + 1
            sub_text = self.buffer_data[ind1: ind2]
            try:
                sub_text_dict = json.loads(sub_text)
                if list(sub_text_dict.keys()) == ['track_x', 'track_y']:
                    self.tracking_coord_count += 1
                    x = sub_text_dict['track_x']
                    y = sub_text_dict['track_y']
                    self.configs['track_x'] = x
                    self.configs['track_y'] = y
                    self.coordinates_log += f"{x}   {y}\n"

                if 'tracking' in sub_text_dict:
                    self.configs['tracking'] = sub_text_dict['tracking']
                elif 'stabilization' in sub_text_dict:
                    self.configs['stabilization'] = sub_text_dict['stabilization']
                elif 'motion_det' in sub_text_dict:
                    self.configs['motion_det'] = sub_text_dict['motion_det']
                elif 'temperature' in sub_text_dict:
                    tmp = round(sub_text_dict['temperature'])
                    self.configs['temperature'] = tmp
                    self.temperature_line_edit.setText(str(tmp))
                else:
                    self.configs_window.fill_get_fields(sub_text)

                self.buffer_data = self.buffer_data.replace(sub_text, "")

            except json.decoder.JSONDecodeError as e:
                print(f"json decoding error: {sub_text}")
            except Exception as e:
                print(f"Error: {sub_text}")


    def flush_logs(self):
        print("flush_logs")
        if self.buffer_log:
            try:
                f = open(self.log_file, 'a')
                f.write(self.buffer_log + "\n")
                f.flush()
            except FileNotFoundError:
                print(f"Error: The file {self.log_file} was not found.")
            except PermissionError:
                print(f"Error: Permission denied. Unable to access {filename} file.")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

            self.buffer_log = ""

        if self.coordinates_log:
            try:
                f = open(self.coordinates_log_file, 'a')
                f.write(self.coordinates_log )
                f.flush()
            except FileNotFoundError:
                print(f"Error: The file {self.coordinates_log_file} was not found.")
            except PermissionError:
                print(f"Error: Permission denied. Unable to access {filename} file.")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

            self.coordinates_log = ""



    def report_tracking_coord_count(self):
        #print("Coordinates in last 10 seconds:", self.tracking_coord_count)
        per_second_coord_count = ceil(self.tracking_coord_count / 10)
        self.tracking_coord_editline.setText(str(per_second_coord_count))
        self.tracking_coord_count = 0


    def report_temperature(self):
        print("receive report temp")
        to_json = json.dumps({"temperature": "%"})
        self.serial_thread.send_text_signal.emit(to_json)
        time.sleep(0.01)


    def send_buffer_coordinates(self, buffer):
        while len(buffer) != 0:
            sending_coords = buffer.pop()
            self.send_coordinates_through_serial(coords=sending_coords)


    def send_coordinates_through_serial(self, coords: dict):
        coords_to_json = json.dumps(coords)

        self.serial_thread.send_text_signal.emit(coords_to_json)
        if self.configs != {} and self.configs_window is not None:
            keys = list(coords.keys())
            for k in keys:
                self.configs_window.change_parameter_value(val=coords[k], label_name=k)
                print("self.buffer_configs[track_fr_h]:",
                          self.configs_window.buffer_configs["track_fr_h"])

            self.configs_window.track_frame_size = [
                self.configs_window.buffer_configs["track_fr_h"],
                self.configs_window.buffer_configs["track_fr_w"]]
            self.configs_window.track_coord_x = self.configs_window.buffer_configs["track_x"]
            self.configs_window.track_coord_y = self.configs_window.buffer_configs["track_y"]
        else:
            write_to_serial(self.ser, coords_to_json)


    def show_configurations(self):
        if self.configs != {} and self.configs_window is not None:
            if self.configs_window.isVisible():
                self.configs_window.hide()
            else:
                self.configs_window.show()


    def close_camera(self):
        self.camera_closed = True
        self.is_recording = False

        if self.video_thread:
            self.video_thread.stop()
            self.video_thread = None

        self.video_label.clear()
        self.video_label.setPixmap(self.gray_pixmap)
        self.track_video = None
        self.track_video_label.clear()
        self.recorded_frames = []
        self.close_camera_button.setEnabled(False)
        self.open_camera_button.setEnabled(True)
        self.save_records_button.setEnabled(False)
        self.start_button.setEnabled(False)


    def closeEvent(self, event):
        print("closeEvent")
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        self.flush_logs()
        f = open(self.log_file, 'a')
        f.close()
        fl = open(self.coordinates_log_file, 'a')
        fl.close()
        if self.is_recording:
            self.stop_recording()
        self.close_camera()
        if self.configs_window:
            self.configs_window.close()
        event.accept()


def dict_to_text(d: dict):
    text = ""
    for k in d:
        text += str(k) + ': ' + str(d[k]) + '\n'

    return text


def the_closest_string(s: str, list_of_strings: list):
    return max(list_of_strings, key=lambda s: SequenceMatcher(None, target, s).ratio())



class ConfigurationsWindow(QWidget):
    def __init__(self, configs_dict, ser_th):
        super().__init__()
        self.setWindowTitle("Configurations")
        self.setWindowFlags(
            Qt.Tool |               # stays above main window
            Qt.FramelessWindowHint  # optional (clean panel look)
        )

        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._drag_pos = None

        self.layout = QVBoxLayout(self)

        self.ser_th = ser_th

        if configs_dict != {}:
            self.configs_dict = configs_dict

            self.buffer_configs = {}
            for i in self.configs_dict:
                self.buffer_configs[i] = self.configs_dict[i]

            self.label_names = list(self.buffer_configs.keys())

            self.get_fields = {}
            self.set_fields = {}

            parameters_layout = QGridLayout()
            parameters_layout.setHorizontalSpacing(5)
            parameters_layout.setContentsMargins(0, 0, 0, 0)
            for i in range(len(self.label_names)):
                label = QLabel(self.label_names[i], self)
                get_edit = QLineEdit("", self)
                get_edit.setReadOnly(True)
                set_label = QLabel("SET", self)
                if self.label_names[i] == "resolution":
                    set_edit = QHBoxLayout(self)
                    self.rb_full_hd = QRadioButton("FHD", self)
                    self.rb_hd = QRadioButton("HD", self)
                    self.rb_full_hd.toggled.connect(self.update_resolution_fhd)
                    self.rb_hd.toggled.connect(self.update_resolution_hd)
                    set_edit.addWidget(self.rb_full_hd)
                    set_edit.addWidget(self.rb_hd)
                elif self.label_names[i] == "frame_edge":
                    #set_edit = QHBoxLayout(self)
                    self.frame_edge_combo = QComboBox(self)
                    self.frame_edge_combo.addItems([str(i) for i in range(6)])  # 0–5
                    self.frame_edge_combo.currentIndexChanged.connect(self.update_frame_edge)
                    #set_edit.addWidget(self.frame_edge_combo)
                    set_edit = self.frame_edge_combo
                elif self.label_names[i] == "track_wndw_size":
                    self.track_wnd_size_combo = QComboBox(self)
                    self.track_wnd_sizes = ['32', '64', '128']
                    self.track_wnd_size_combo.addItems(self.track_wnd_sizes)
                    self.track_wnd_size_combo.currentIndexChanged.connect(self.update_track_wnd_size)
                    set_edit = self.track_wnd_size_combo
                else:
                    set_edit = QLineEdit("", self)
                    set_edit.setValidator(QIntValidator(0, 99999))
                    set_edit.textChanged.connect(partial(self.change_parameter_value, label_name=self.label_names[i]))

                self.get_fields[self.label_names[i]] = get_edit
                self.set_fields[self.label_names[i]] = set_edit

                parameters_layout.addWidget(label, i, 0)
                parameters_layout.addWidget(get_edit, i, 1)
                parameters_layout.addWidget(set_label, i, 2)
                if isinstance(set_edit, QHBoxLayout):
                    parameters_layout.addLayout(set_edit, i, 3)
                else:
                    parameters_layout.addWidget(set_edit, i, 3)

                self.layout.addLayout(parameters_layout)


        self.track_frame_size = [0, 0]
        self.track_coord_x = None
        self.track_coord_y = None

        self.ok_cancel_btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("OK", self)
        self.cancel_btn = QPushButton("CANCEL", self)
        self.apply_btn = QPushButton("APPLY", self)

        self.ok_cancel_btn_layout.addWidget(self.cancel_btn)
        self.ok_cancel_btn_layout.addWidget(self.ok_btn)
        self.ok_cancel_btn_layout.addWidget(self.apply_btn)

        self.layout.addLayout(self.ok_cancel_btn_layout)

        self.ok_btn.clicked.connect(self.on_ok_click)
        self.cancel_btn.clicked.connect(self.on_cancel_click)
        self.apply_btn.clicked.connect(self.on_apply_click)

        self.setLayout(self.layout)
        self.set_values_in_input_fields(fields = self.get_fields, configs = self.buffer_configs)
        self.set_values_in_input_fields(fields = self.set_fields, configs = self.buffer_configs)
        #self.timer.start(8000)


    def set_values_in_input_fields(self, fields, configs):
        for key in configs:
            if fields is self.set_fields and key == 'resolution':
                if int(configs["resolution"]) == 1:
                    self.rb_full_hd.setChecked(True)
                else:
                    self.rb_hd.setChecked(True)
            elif fields is self.set_fields and key == 'frame_edge':
               self.frame_edge_combo.setCurrentIndex(int(configs["frame_edge"]))
            elif fields is self.set_fields and key == 'track_wndw_size':
                self.track_wnd_size_combo.setCurrentText(str(configs["track_wndw_size"]))
            else:
                fields[key].setText(str(configs[key]))


    def fill_get_fields(self, data):
        if self.ser_th:
            if isinstance(data, str):
                data = json.loads(data)
            self.set_values_in_input_fields(fields=self.get_fields, configs=data)


    def change_parameter_value(self, val, label_name):
        print(label_name,val)

        self.set_fields[label_name].setText(str(val))
        if str(val) != "":
            self.buffer_configs[label_name] = float(val)
        else:
            self.buffer_configs[label_name] = 0


    def update_resolution_fhd(self, selected):
        res = 1 if selected else 0
        self.buffer_configs['resolution'] = 1
        self.configs_dict['resolution'] = 1
        res_json = json.dumps({'resolution': res})
        self.ser_th.send_text_signal.emit(res_json)
        self.request_one_parameter('resolution')


    def update_resolution_hd(self, selected):
        res = 0 if selected else 1
        self.buffer_configs['resolution'] = 0
        self.configs_dict['resolution'] = 0
        res_json = json.dumps({'resolution': res})
        self.ser_th.send_text_signal.emit(res_json)
        self.request_one_parameter('resolution')


    def update_frame_edge(self, ind):
        self.buffer_configs['frame_edge'] = ind

    def update_track_wnd_size(self, ind):
        size = int(self.track_wnd_sizes[ind])
        self.buffer_configs['track_wndw_size'] = size


    def request_parameters_update(self):
        print("request_parameters_update")
        to_json = json.dumps({"parameters": "%"})
        self.ser_th.send_text_signal.emit(to_json)


    def request_one_parameter(self, param_name):
        print("request_one_parameter")
        to_json = json.dumps({f"{param_name}": "%"})
        self.ser_th.send_text_signal.emit(to_json)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


    def on_ok_click(self):
        print("ok")
        self.on_apply_click()
        self.close()


    def on_apply_click(self):
        print("apply")
        for k in self.set_fields:
            if isinstance(self.set_fields[k], QLineEdit) and self.set_fields[k].text() == "":
                self.set_fields[k].setText('0')

        for k in self.configs_dict:
            if self.configs_dict[k] != self.buffer_configs[k]:
                config_to_json = json.dumps({k:self.buffer_configs[k]})
                self.ser_th.send_text_signal.emit(config_to_json)
                self.configs_dict[k] = self.buffer_configs[k]

        time.sleep(0.1)
        self.request_parameters_update()
        time.sleep(0.5)


    def on_cancel_click(self):
        print("cancel")
        self.buffer_configs = self.configs_dict
        self.set_values_in_input_fields(fields = self.set_fields, configs = self.buffer_configs )
        self.close()


def common_elements(dict1, key_list)-> list:
    commonn_elems = []

    if dict1 and key_list:
        for el in key_list:
            if el in dict1:
                commonn_elems.append(el)

    return commonn_elems


def equal_lists(first_list, second_list):
    if len(first_list) != len(second_list):
        return False
    else:
        for i in range(len(first_list)):
            if first_list[i] != second_list[i]:
                return False
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    sys.exit(app.exec_())


