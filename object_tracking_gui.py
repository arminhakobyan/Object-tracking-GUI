from PyQt5 import QtGui
import sys
import cv2
import time
import json
import pygame
from collections import deque
from multiprocessing import Process
import numpy as np
import socket
from traceback import print_exc
from serial import Serial
from serial.tools import list_ports
from serial import SerialException, SerialTimeoutException
from threading import Thread
from configs import Configurations
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

)


def list_open_com_ports():
    ports = list_ports.comports()
    open_ports = []
    for port in ports:
        open_ports.append(port.device)
    return open_ports


def write_to_serial(ser, js):
    print("write_to_serial", js)
    ser.write(bytes([0xff]))

    for char in js:
        ser.write(char.encode())
        time.sleep(0.0001)

    ser.write(bytes([0xff]))


class VideoCaptureThread(QThread):
    change_frame_signal = pyqtSignal(np.ndarray)
    camera_ready_signal = pyqtSignal()

    def __init__(self, index, api_pref, ):
        super().__init__()
        self._index = index
        self._api_pref = api_pref
        self.video_capture = cv2.VideoCapture(self._index, self._api_pref)
        self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.running = True

    def get_index(self):
        return self._index

    def run(self):
        self.running = True
        if self.video_capture.isOpened():
            while self.running:
                ret, frame = self.video_capture.read()
                if ret:
                    self.change_frame_signal.emit(frame)

    def stop(self):
        self.running = False
        self.wait()
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


    def run(self):
        print("run()")

        while self.running:
            try:
                if self.serial.in_waiting > 0:
                    my_list = []
                    data = ""
                    while self.serial.in_waiting > 0:
                        d = self.serial.read()
                        my_list.append(d)
                        time.sleep(0.02)
                    for i in my_list:
                        data += str(i.decode("utf-8"))

                    print("received the data ", data)

                    data = data.strip()
                    self.received_data_signal.emit(data)

            except Exception as e:
                print(f"Error: {e}")


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
            print("About to write...")
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
        #self.video_label.mousePressEvent = self.click_on

        self.video_label.setMouseTracking(True)

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
        self.configurations_window_btn.setGeometry(1650, 150, 150, 50)
        self.configurations_window_btn.clicked.connect(self.show_configurations)

        # buffer for point coordinates
        self.coords_buffer = deque()

        self.serial_thread = None
        self.video_writer = None
        self.video_capture = None
        self.video_thread = None
        self.is_recording = False
        self.camera_closed = False
        self.input_data_json = None
        self.recorded_frames = []
        self.camera_buttons = []
        self.selected_camera = 0
        self.track_frame_size = [150, 150]  # height, width
        self.resized_frame_shape = [540, 960]
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
        self.device_id = 1234567890

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

        self.console = None

        self.pointer = QLabel(self)  # self.video_label
        self.pointer.setFixedSize(0, 0)  # (10, 10)
        self.pointer.setStyleSheet("background-color: red; border-radius: 5px;")
        #self.pointer.move(self.resized_frame_shape[0], self.resized_frame_shape[1])
        #self.pointer.move(0, 0)

        # Start joystick thread
        self.joystick_thread = JoystickThread()
        #self.joystick_thread.axis_changed.connect(self.update_joystick_pointer)

        self.joystick_thread.axis_changed.connect(self.send_joystick_coords)
        self.joystick_thread.started_moving.connect(self.start_joystick_motion)
        self.joystick_thread.stopped_moving.connect(self.stop_joystick_motion)
        self.joystick_thread.button_pushed.connect(self.handle_joystick_button)

        self.pointer_pos = [0, 0]


    def keyPressEvent(self, event):
        if event.key() == Qt.Key_T:
            self.mouse_as_joystick = not self.mouse_as_joystick
            print("Mouse joystick mode:", self.mouse_as_joystick)

    def mouseReleaseEvent(self, event):
        if self.mouse_as_joystick and event.button() == Qt.LeftButton:
            self.mouse_pressed = False
            self.last_mouse_pos = None


    def mousePressEvent(self, event):
        if self.mouse_as_joystick:
            if event.button() == Qt.LeftButton:
                self.click_on(event)
                self.mouse_pressed = True
            elif event.button() == Qt.RightButton:
                self.handle_joystick_button(0)
        #else:
        #    self.click_on(event)


    def click_on(self, event):
        print("click_on_video")
        if event.button() == Qt.LeftButton is not None:  # and self.video_thread
            self.cursor_x = int(event.pos().x())
            self.cursor_y = int(event.pos().y())
            self.cursor_x_in_original_frame = int((event.pos().x() - self.video_label_deviation[0]) * self.scale_x)
            self.cursor_y_in_original_frame = int((event.pos().y() - self.video_label_deviation[1]) * self.scale_y)
            self.pointer_pos[0] = int(event.pos().x()) - self.video_label_deviation[0]
            self.pointer_pos[1] = int(event.pos().y()) - self.video_label_deviation[1]

            self.coords_in_original_frame = {"cursor_x": self.cursor_x_in_original_frame,
                                             "cursor_y": self.cursor_y_in_original_frame}

            self.coords_buffer.append(self.coords_in_original_frame)
            self.send_buffer_coordinates(buffer=self.coords_buffer)



    def stop_joystick_motion(self, dx, dy):
        print("stopped joystick")
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

    """
    def mouseMoveEvent(self, event):
        if self.mouse_as_joystick and event.buttons() & Qt.LeftButton:
            center_x = self.width() / 2
            center_y = self.height() / 2

            # Simple proportional movement from center
            dx = (event.x() - center_x) / center_x  # -1 to 1 range
            dy = (event.y() - center_y) / center_y  # -1 to 1 range

            # Optional: apply dead zone
            dead_zone = 0.1
            if abs(dx) < dead_zone: dx = 0
            if abs(dy) < dead_zone: dy = 0

            self.send_joystick_coords(dx, dy)
    """

    def mouseMoveEvent(self, event):
        if self.mouse_as_joystick and event.buttons() & Qt.LeftButton:

            # Get mouse position relative to widget
            mouse_x = event.x()
            mouse_y = event.y()

            target_x = mouse_x - 5 - self.video_label_deviation[0]
            target_y = mouse_y - 5 - self.video_label_deviation[1]
            dx = (target_x - self.pointer_pos[0]) / 5
            dy = (target_y - self.pointer_pos[1]) / 5

            self.send_joystick_coords(dx, dy)



    def update_joystick_pointer(self, dx, dy):
        self.joystick_pointers_count += 1
        speed = 5

        self.pointer_pos[0] += dx * speed
        self.pointer_pos[1] += dy * speed

        self.pointer_pos[0] = max(-5, min(self.resized_frame_shape[1] - 5, self.pointer_pos[0]))
        self.pointer_pos[1] = max(-5, min(self.resized_frame_shape[0] - 5, self.pointer_pos[1]))

        self.pointer_move(coord_x = int(self.pointer_pos[0] + self.video_label_deviation[0]), coord_y = int(self.pointer_pos[1])+self.video_label_deviation[1])

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
                if self.console.configs_window:
                    self.console.configs_window.change_parameter_value(x, "cursor_x")
                    self.console.configs_window.change_parameter_value(y, "cursor_y")



    def handle_joystick_button(self, i: int):
        if i == 0:
            print("joystick button pushed")
            if self.pointer_coord:
                x = 0x8000 | self.pointer_coord['cursor_x']
                y = 0x8000 | self.pointer_coord['cursor_y']
                self.cursor_x = self.pointer_coord['cursor_x']/self.scale_x + self.video_label_deviation[0] + 5
                self.cursor_y = self.pointer_coord['cursor_y']/self.scale_y + self.video_label_deviation[1] + 5
                x_json = json.dumps({'cursor_x': x})
                y_json = json.dumps({'cursor_y': y})
                if self.serial_thread:
                    self.serial_thread.send_joystick_coordinates.emit(x_json, y_json)
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
        if not self.mouse_as_joystick:
            self.selected_camera = ind
            print(self.available_cameras[self.selected_camera])
            self.open_camera_button.setEnabled(True)

    def hide_loading(self):
        self.loading_movie.stop()
        self.loading_label.hide()


    def open_camera(self):
        if not self.mouse_as_joystick:
            self.camera_closed = False
            self.start_button.setEnabled(True)
            self.close_camera_button.setEnabled(True)

            if self.video_thread is not None:  # and self.video_thread.get_index() != self.available_cameras[self.selected_camera][1]:
                self.video_thread.stop()
                self.video_thread = None

            ind = self.available_cameras[self.selected_camera][1]
            api_pref = self.available_cameras[self.selected_camera][2]

            self.video_thread = VideoCaptureThread(ind, api_pref)

            self.video_thread.camera_ready_signal.connect(self.hide_loading)
            self.video_thread.change_frame_signal.connect(self.update_frame)

            self.video_thread.start()
            #self.joystick_thread.start()


    @pyqtSlot(np.ndarray)
    def update_frame(self, frame):
        if self.video_thread is not None:
            self.original_frame_shape = frame.shape  # height, width, ch
            frame = cv2.resize(frame, (self.resized_frame_shape[1], self.resized_frame_shape[0]))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            img = QtGui.QImage(frame.tobytes(), frame.shape[1], frame.shape[0], frame.shape[1] * 3,
                               QtGui.QImage.Format_RGB888)
            self.video_label.setPixmap(QtGui.QPixmap.fromImage(img))

            self.scale_x = self.original_frame_shape[1] / self.resized_frame_shape[1]  # width
            self.scale_y = self.original_frame_shape[0] / self.resized_frame_shape[0]  # height

            if self.console:
                if self.console.configs_window is not None:
                    self.cursor_x = int(self.console.configs_window.track_coord_x / self.scale_x + self.video_label_deviation[0] + 5)
                    self.cursor_y = int(self.console.configs_window.track_coord_y / self.scale_y + self.video_label_deviation[1] + 5)
                    self.track_frame_size = self.console.configs_window.track_frame_size

            if self.cursor_x is not None and self.cursor_y is not None:
                x_start = int(max(1, self.cursor_x - self.track_frame_size[1] / 2 - self.video_label_deviation[0]))
                x_end = int(min(self.resized_frame_shape[1], self.cursor_x + self.track_frame_size[1] / 2 - self.video_label_deviation[0]))
                y_start = int(max(0, self.cursor_y - self.track_frame_size[0] / 2 - self.video_label_deviation[0]))
                y_end = int(min(self.resized_frame_shape[0], self.cursor_y + self.track_frame_size[0] / 2 - self.video_label_deviation[0]))

                self.track_video = frame[y_start:y_end, x_start:x_end]

                if self.track_video.size > 0:
                    h, w, ch = self.track_video.shape
                    bytes_per_line = ch * w
                    self.track_video_label.setPixmap(QtGui.QPixmap.fromImage(QtGui.QImage(self.track_video.tobytes(),
                                                                                          w, h, bytes_per_line,
                                                                                          QtGui.QImage.Format_RGB888)))
                    self.track_video_label.setGeometry(self.track_video_label_x, self.track_video_label_y,
                                                       self.track_frame_size[1],
                                                       self.track_frame_size[0])  # x, y, w, h

            if self.track_frame_size == [0, 0] and self.track_video_label is not None:
                self.track_video_label.clear()

            self.current_frame = frame

            if self.is_recording:
                self.recorded_frames.append(self.current_frame)


    def get_text_from_consolefield(self):
        print(self.console_field.document().toPlainText())


    def start_recording(self):
        if not self.mouse_as_joystick:
            self.is_recording = True
            self.open_camera_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.save_records_button.setEnabled(False)


    def stop_recording(self):
        if not self.mouse_as_joystick:
            self.is_recording = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.save_records_button.setEnabled(True)
            self.open_camera_button.setEnabled(True)


    def save_video(self):
        if len(self.recorded_frames) == 0 or self.mouse_as_joystick:
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Save Video", "", "mp4 Files (*.mp4v)")
        if filename:
            fshape = self.recorded_frames[0].shape
            fheight = int(fshape[1])
            fwidth = int(fshape[0])
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(filename, fourcc, 15, (fwidth, fheight), True)
            for frame in self.recorded_frames:
                self.video_writer.write(frame)
            self.video_writer.release()
            self.recorded_frames = []

        print("video saved!")


    def select_port(self, ind):
        if self.mouse_as_joystick:
            return
        else:
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
            self.ser = Serial(port, int(baud_rate), timeout=1)
            self.ser.close()
            self.ser.open()
            self.port_connected = True
            return True
        except:
            print("Couldn't connect")
            return False



    def connect_port(self):
        if not self.mouse_as_joystick:
            if self.port_connected and self.ser is not None and self.ser.is_open:
                self.ser.write(bytes([0xFE]))
                # response_dis = ""
                # my_list2 = []
                time.sleep(0.3)
                if self.console:
                    if self.console.configs_window:
                        if self.console.configs_window.timer.isActive():
                            self.console.configs_window.timer.stop()
                            self.console.configs_window.ser_th = None
                            self.console.configs_window.hide()
                    self.console.serial_th = None
                    self.console.hide()

            else:
                port = self.get_selected_port()
                print(self.get_selected_port())

                check_port = self.check_port_connection(port, self.baud_rate)
                print("check port", check_port)
                try:
                    if check_port:
                        self.ser.write(bytes([0xFE]))
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

                        if js.get('device_id') == self.device_id:
                            self.ser.write(bytes([0xFE]))

                            confirmation = ""
                            attempt = 0
                            while attempt < 10:
                                attempt += 1
                                time.sleep(0.5)
                                my_list1 = []
                                while self.ser.in_waiting > 0:
                                    d = self.ser.read()
                                    my_list1.append(d)
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
                                self.console = SerialConsole(self.serial_thread)
                                self.console.resize(600, 400)
                                self.console.show()
                                self.joystick_thread.start()

                except SerialException as e:
                    QMessageBox.critical(self, "Error", "Invalid port.")
                    print("Serial port error:", e)
                    if self.ser and self.ser.is_open:
                        self.ser.close()

                except SerialTimeoutException as e:
                    print("Timeout occurred:", e)
                    if self.ser and self.ser.is_open:
                        self.ser.close()

                except Exception as e:
                    print("Unexpected error:", e)
                    QMessageBox.critical(self, "Error", "Invalid response from device.")
                    if self.ser and self.ser.is_open:
                        self.ser.close()


    def receive_data_from_serial(self, text):
        if "Disconnect" in text:
            self.connect_btn.setText("Connect")
            self.port_connected = False
            if self.console is not None and self.console.isVisible():
                self.console.hide()
                self.console = None
            try:
                self.serial_thread.stop()
                self.ser.close()
                print("disconnected")
            except EOFError as e:
                print(e)



    def send_buffer_coordinates(self, buffer):
        while len(buffer) != 0:
            sending_coords = buffer.pop()
            self.send_coordinates_through_serial(coords=sending_coords)


    def send_coordinates_through_serial(self, coords: dict):
        coords_to_json = json.dumps(coords)

        if self.console is not None:
            self.serial_thread.send_text_signal.emit(coords_to_json)
            if self.console.configs != {} and self.console.configs_window is not None:
                keys = list(coords.keys())
                for k in keys:
                    self.console.configs_window.change_parameter_value(val=coords[k], label_name=k)
                    print("self.buffer_configs[track_fr_h]:",
                          self.console.configs_window.buffer_configs["track_fr_h"])

                self.console.configs_window.track_frame_size = [
                    self.console.configs_window.buffer_configs["track_fr_h"],
                    self.console.configs_window.buffer_configs["track_fr_w"]]
                self.console.configs_window.track_coord_x = self.console.configs_window.buffer_configs["track_x"]
                self.console.configs_window.track_coord_y = self.console.configs_window.buffer_configs["track_y"]
        else:
            write_to_serial(self.ser, coords_to_json)


    def show_configurations(self):
        if self.console is not None and not self.mouse_as_joystick:
            if self.console.configs != {} and self.console.configs_window is not None:
                if self.console.configs_window.isVisible():
                    self.console.configs_window.hide()
                else:
                    self.console.configs_window.show()


    def close_camera(self):
        if not self.mouse_as_joystick:
            self.camera_closed = True
            self.is_recording = False

            if self.video_thread:
                self.video_thread.stop()
                self.video_thread = None

            self.video_label.clear()
            self.track_video = None
            self.track_video_label.clear()
            self.recorded_frames = []
            self.close_camera_button.setEnabled(False)
            self.open_camera_button.setEnabled(True)
            self.save_records_button.setEnabled(False)
            self.start_button.setEnabled(False)


    def closeEvent(self, event):
        if self.is_recording:
            self.stop_recording()
        self.close_camera()
        if self.console:
            self.console.close()
            if self.console.configs_window:
                self.console.configs_window.close()
        # if self.video_capture is not None:
        #    self.video_capture.release()
        event.accept()


def dict_to_text(d: dict):
    text = ""
    for k in d:
        text += str(k) + ': ' + str(d[k]) + '\n'

    return text


def the_closest_string(s: str, list_of_strings: list):
    return max(list_of_strings, key=lambda s: SequenceMatcher(None, target, s).ratio())



class SerialConsole(QWidget):
    def __init__(self, serial_th):
        super().__init__()
        self.setWindowTitle("Serial Console")

        self.serial_th = serial_th

        self.layout = QVBoxLayout(self)
        self.console = QPlainTextEdit(self)
        self.console.setReadOnly(True)
        self.layout.addWidget(self.console)

        self.input_field = QPlainTextEdit(self)
        self.input_field.setPlaceholderText(
            "To get the configuraton parameters write << get configuration parameters >> command and enter!")

        self.layout.addWidget(self.input_field)
        self.waiting_for_data = False

        # self.serial_th.send_bytes_signal.emit(bytes([0xff]))
        self.serial_th.received_data_signal.connect(self.send_text_show_on_console)
        self.serial_th.start()

        # Connect key press event for input field
        self.input_field.keyPressEvent = self.handle_key_press

        self.configs = {}
        self.configs_window = None


    def send_text_show_on_console(self, text):
        if text != "" and "Disconnected" not in text:
            print("received the data", text)
            # "{}".split("}")[-1]
            # text[text.index("{") : text.index("}") + 1]
            last_data = ""
            if text.index("}") != len(text)-1:
                text_list = text.split("}")
                print(text_list)
                last_data = str(text_list[-2]) + '}'
                print("last data", last_data)
            else:
                last_data = text
            self.configs = json.loads(last_data)
            console_text = dict_to_text(self.configs)
            self.console.appendPlainText(console_text)
            if self.configs_window is None:
                self.configs_window = ConfigurationsWindow(configs_dict=self.configs, ser_th=self.serial_th)
                self.configs_window.show()
            else:
                self.configs_window.fill_get_fields(last_data)
        else:
            print("no data")

    def send_input(self):
        user_input = self.input_field.toPlainText().strip()
        to_json = ""
        command = user_input
        if user_input:
            input_list = user_input.split(" ", 1)
            if input_list[0] == "get":
                list_parameters = list(self.configs.keys())
                list_parameters.append("configuration parameters")
                to_json = self.get_config(param_name=input_list[1])
            elif input_list[0] == "set":
                data_list_set = input_list[1].split(" ", 1)
                config_name = data_list_set[0]
                val = int(data_list_set[1])
                to_json = self.set_config(param_name=config_name, value=val)
                self.configs_window.change_parameter_value(val=val, label_name=config_name)

            else:
                command = "wrong command"

        self.serial_th.send_text_signal.emit(to_json)

        self.console.appendPlainText(f"> {command}")  # Show sent command

        self.input_field.clear()


    def get_config(self, param_name: str):
        if param_name == "kp_th":
            return json.dumps({"kp_th": "%"})
        elif param_name == "kp_up_th":
            return json.dumps({"kp_up_th": "%"})
        elif param_name == "kp_down_th":
            return json.dumps({"kp_down_th": "%"})
        elif param_name == "dir_th":
            return json.dumps({"dir_th": "%"})
        elif param_name == "autocorr_th":
            return json.dumps({"autocorr_th": "%"})
        elif param_name == "match_size":
            return json.dumps({"match_size": "%"})
        elif param_name == "track_fr_w":
            return json.dumps({"track_fr_w": "%"})
        elif param_name == "track_fr_h":
            return json.dumps({"track_fr_h": "%"})
        elif param_name == "track_x":
            return json.dumps({"track_x": "%"})
        elif param_name == "track_y":
            return json.dumps({"track_y": "%"})
        elif param_name == "cursor_x":
            return json.dumps({"cursor_x": "%"})
        elif param_name == "cursor_y":
            return json.dumps({"cursor_y": "%"})
        elif param_name == "resolution":
            return json.dumps({"resolution": "%"})
        elif param_name == "configuration parameters":
            return json.dumps({"parameters": "%"})
        else:
            self.console.appendPlainText("Wrong parameter name")

    def set_config(self, param_name: str, value: int):
        if param_name == "kp_th":
            self.configs["kp_th"] = value
            return json.dumps({"kp_th": value})
        elif param_name == "kp_up_th":
            self.configs["kp_up_th"] = value
            return json.dumps({"kp_up_th": value})
        elif param_name == "kp_down_th":
            self.configs["kp_down_th"] = value
            return json.dumps({"kp_down_th": value})
        elif param_name == "dir_th":
            self.configs["dir_th"] = value
            return json.dumps({"dir_th": value})
        elif param_name == "autocorr_th":
            self.configs["autocorr_th"] = value
            return json.dumps({"autocorr_th": value})
        elif param_name == "match_size":
            self.configs["match_size"] = value
            return json.dumps({"match_size": value})
        elif param_name == "cursor_x":
            self.configs["cursor_x"] = value
            return json.dumps({"cursor_x": value})
        elif param_name == "cursor_y":
            self.configs["cursor_y"] = value
            return json.dumps({"cursor_y": value})
        elif param_name == "track_fr_w":
            self.configs["track_fr_w"] = value
            self.configs_window.track_frame_size[1] = value
            return json.dumps({"track_fr_w": value})
        elif param_name == "track_fr_height":
            self.configs["track_fr_h"] = value
            self.configs_window.track_frame_size[0] = value
            return json.dumps({"track_fr_h": value})

        else:
            self.console.appendPlainText("Wrong parameter name")  # Show sent command


    def handle_key_press(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.send_input()
        else:
            QPlainTextEdit.keyPressEvent(self.input_field, event)


    def show_configs_window(self):
        if self.configs_window.isVisible():
            self.configs_window.hide()
        else:
            self.configs_window.show()


class ConfigurationsWindow(QWidget):
    def __init__(self, configs_dict, ser_th):
        super().__init__()
        self.setWindowTitle("Configurations")
        self.setGeometry(900, 500, 400, 400)
        self.setGeometry(800, 400, 500, 500)

        self.layout = QVBoxLayout(self)

        self.ser_th = ser_th

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.request_parameters_update)

        if configs_dict != {}:
            self.configs_dict = configs_dict

            self.buffer_configs = {}
            for i in self.configs_dict:
                self.buffer_configs[i] = self.configs_dict[i]

            self.label_names = list(self.buffer_configs.keys())

            self.get_fields = {}
            self.set_fields = {}

            parameters_layout = QGridLayout()
            for i in range(len(self.label_names)):
                if self.label_names[i] == "track_x" or self.label_names[i] == "track_y":
                    label = QLabel(self.label_names[i], self)
                    get_field = QLineEdit("", self)
                    get_field.setReadOnly(True)
                    lb_set = QLabel("READ ONLY", self)
                    self.get_fields[self.label_names[i]] = get_field
                    parameters_layout.addWidget(label, i, 0)
                    parameters_layout.addWidget(get_field, i, 1)
                    parameters_layout.addWidget(lb_set, i, 3)
                else:
                    label = QLabel(self.label_names[i], self)
                    get_field = QLineEdit("", self)
                    get_field.setReadOnly(True)
                    lb_set = QLabel("SET", self)

                    set_field = QLineEdit("", self)
                    set_field.setValidator(QIntValidator(0, 99999))

                    set_field.textChanged.connect(partial(self.change_parameter_value, label_name=self.label_names[i]))
                    self.get_fields[self.label_names[i]] = get_field
                    self.set_fields[self.label_names[i]] = set_field

                    parameters_layout.addWidget(label, i, 0)
                    parameters_layout.addWidget(get_field, i, 1)
                    parameters_layout.addWidget(lb_set, i, 2)
                    parameters_layout.addWidget(set_field, i, 3)

                self.layout.addLayout(parameters_layout)


        self.track_frame_size = None
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
        self.timer.start(8000)


    def set_values_in_input_fields(self, fields, configs):
        print("set_values_in_input_fields")
        for i in range(len(self.label_names)):
            param_name = self.label_names[i]
            print(param_name)
            if fields is self.set_fields and (param_name == 'track_x' or param_name == "track_y"):
                continue
            elif (fields is self.get_fields
                  and (param_name == 'track_x' or param_name == "track_y" or
                    param_name == 'cursor_x' or param_name == 'cursor_y')) and configs[param_name] > 1980:
                param = int(configs[param_name]) & 0x7FFF
                fields[param_name].setText(str(param))
            else:
                fields[param_name].setText(str(configs[param_name]))
        track_frame_height = int(configs["track_fr_h"])
        track_frame_width = int(configs["track_fr_w"])
        self.track_frame_size = [track_frame_height, track_frame_width]

        self.track_coord_x = int(configs["track_x"]) & 0x7FFF
        self.track_coord_y = int(configs["track_y"]) & 0x7FFF


    def fill_get_fields(self, data):
        print("fill get fields data")
        if self.ser_th:
            if isinstance(data, str):
                data = json.loads(data)
            self.set_values_in_input_fields(fields=self.get_fields, configs=data)


    def change_parameter_value(self, val, label_name):
        print(label_name,val)

        self.set_fields[label_name].setText(str(val))
        if str(val) != "":
            self.buffer_configs[label_name] = int(val)
        else:
            self.buffer_configs[label_name] = 0


    def request_parameters_update(self):
        print("request_parameters_update")
        to_json = json.dumps({"parameters": "%"})
        self.ser_th.send_text_signal.emit(to_json)


    def on_ok_click(self):
        print("ok")
        self.on_apply_click()
        self.close()


    def on_apply_click(self):
        print("apply")
        for k in self.set_fields:
            if self.set_fields[k].text() == "":
                self.set_fields[k].setText('0')

        #self.track_frame_size = [self.buffer_configs["track_fr_h"], self.buffer_configs["track_fr_w"]]
        #self.track_coord_x = self.buffer_configs["track_x"]
        #self.track_coord_y = self.buffer_configs["track_y"]

        for k in self.configs_dict:
            if self.configs_dict[k] != self.buffer_configs[k]:
                config_to_json = json.dumps({k:self.buffer_configs[k]})
                self.ser_th.send_text_signal.emit(config_to_json)

        coords_json = json.dumps({'cursor_x':self.buffer_configs['cursor_x'], 'cursor_y':self.buffer_configs['cursor_y']})
        self.ser_th.send_text_signal.emit(coords_json)

        for i in self.configs_dict:
            self.configs_dict[i] = self.buffer_configs[i]

        self.request_parameters_update()
        time.sleep(4)

        #self.ser_th.received_data_signal.connect(self.fill_get_fields)
        #self.timer.start(8000)


    def on_cancel_click(self):
        print("cancel")
        self.buffer_configs = self.configs_dict
        self.set_values_in_input_fields(fields = self.set_fields, configs = self.buffer_configs )
        self.close()



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

