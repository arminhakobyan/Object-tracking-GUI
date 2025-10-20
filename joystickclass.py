import pygame
import sys
import time
import numpy as np
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QPainter, QBrush, QColor
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QKeyEvent
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QLabel
)


class JoystickThread(QThread):
    axis_changed = pyqtSignal(float, float)    # x, y
    button_pushed = pyqtSignal(int)
    started_moving = pyqtSignal()
    stopped_moving = pyqtSignal(float, float)


    def __init__(self):
        super().__init__()
        pygame.init()
        pygame.joystick.init()

        self.deadzone = 0.2  # ← tweak this if needed
        self.button_history = {}
        self.moving = False
        self.running = False
        self.current_position = (0.0, 0.0)

        joystick_count = pygame.joystick.get_count()
        print(f"Detected {joystick_count} joystick(s)")

        if joystick_count > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print("joystick initialized")
            self.running = True
        else:
            print("No joystick found")



    def run(self):
        while self.running:
            pygame.event.pump()

            x = self.joystick.get_axis(0)
            y = self.joystick.get_axis(1)

            in_motion = abs(x) > self.deadzone or abs(y) > self.deadzone

            if abs(x) < self.deadzone:
                x = 0.0
            if abs(y) < self.deadzone:
                y = 0.0

            if in_motion and not self.moving:
                self.moving = True
                self.started_moving.emit()
            elif not in_motion and self.moving:
                self.moving = False
                self.stopped_moving.emit(x, y)

            if self.moving:
                self.axis_changed.emit(x, y)

            for i in range(self.joystick.get_numbuttons()):
                state = self.joystick.get_button(i)
                history = self.button_history.get(i, [0, 0])
                # Keep only last 3 states
                history.append(state)
                if len(history) > 3:
                    history.pop(0)

                self.button_history[i] = history

                # Check rising edge with stability: [0, 0, 1]
                if history == [0, 0, 1]:
                    print(f"Rising edge detected on button {i}")
                    self.button_pushed.emit(i)

            time.sleep(0.01)  # ~100Hz polling



class App(QMainWindow):
    def __init__(self):
        super(App, self).__init__()
        self.width = 500
        self.height = 500
        self.setFixedSize(self.width, self.height)

        self.pointer = QLabel(self)
        self.pointer.setFixedSize(10, 10)
        self.pointer.setStyleSheet("background-color: red; border-radius: 5px;")
        self.pointer.move(500, 500)

        # Start joystick thread
        self.joystick_thread = JoystickThread()
        self.joystick_thread.axis_changed.connect(self.update_pointer)
        self.joystick_thread.started_moving.connect(self.update_joystick_motion)
        self.joystick_thread.stopped_moving.connect(self.update_joystick_motion)
        self.joystick_thread.button_pushed.connect(self.handle_push_button)
        self.joystick_thread.start()
        self.pointer_pos = [200, 200]



    def update_joystick_motion(self):
        print("started or stoppped moving")
    def update_pointer(self, dx, dy):
        speed = 5

        self.pointer_pos[0] += dx * speed
        self.pointer_pos[1] += dy * speed

        self.pointer_pos[0] = max(0, min(self.width, self.pointer_pos[0]))
        self.pointer_pos[1] = max(0, min(self.height, self.pointer_pos[1]))

        self.pointer.move(int(self.pointer_pos[0]), int(self.pointer_pos[1]))



    def handle_push_button(self, i:int):
        if i == 0:
            print("LEFT button pushed")
        elif i == 1:
            print("RIGHT button pushed")
        elif i == 2:
            print("LB button pushed")
        elif i == 3:
            print("RB button pushed")
        elif i == 4:
            print("SELECT button pushed")
            print("poiner position: ", int(self.pointer_pos[0]), int(self.pointer_pos[1]))
        elif i == 5:
            print("START button pushed")
        else:
            print("Unknown button")



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec_())