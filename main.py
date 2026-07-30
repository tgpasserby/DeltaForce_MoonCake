# -*- coding: utf-8 -*-

"""开源版程序入口。

原来的启动流程由 run.py 做运行环境准备，再导入 main.py 启动界面。
现在入口统一收敛到本文件：负责日志、管理员权限、子进程窗口策略、
启动异常记录，以及创建主界面。
"""
import ctypes
import os
import platform
import subprocess
import sys

TEST = True

def monkey_patch_subprocess() -> None:
    """让 Windows 子进程默认不创建额外控制台窗口。"""
    if platform.system() != "Windows":
        return

    original_popen = subprocess.Popen

    class PatchedPopen(original_popen):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
            super().__init__(*args, **kwargs)

    subprocess.Popen = PatchedPopen

monkey_patch_subprocess()

import logging

def is_admin() -> bool:
    """检查当前进程是否以管理员权限运行。"""
    if platform.system() != "Windows":
        return False

    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_privileges() -> bool:
    """通过 UAC 以管理员身份重启当前程序。"""
    if platform.system() != "Windows":
        return False

    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{item}"' for item in sys.argv[1:])

    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            f'"{script}" {params}',
            None,
            1,
        )
        return ret > 32
    except Exception as e:
        logging.error(f"尝试提权时 ShellExecuteW 失败: {e}")
        return False

def run_with_admin() -> None:
    """如果当前不是管理员权限，则尝试请求管理员权限后重启。"""
    if is_admin():
        return

    logging.info("检测到程序未以管理员权限运行，正在请求管理员权限...")
    if elevate_privileges():
        logging.info("已请求管理员权限，正在重启程序...")
        sys.exit(0)

    logging.warning("请求管理员权限失败，将继续以当前权限运行")

run_with_admin()

class NullWriter:
    """用于打包环境中丢弃 stdout/stderr 输出。"""

    def write(self, _):
        pass

    def flush(self):
        pass

def configure_logging() -> None:
    """配置全局日志输出。"""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    if not TEST:
        logging.disable()
    else:
        os.makedirs("debug", exist_ok=True)

def prepare_runtime() -> None:
    """准备运行环境。"""
    if getattr(sys, "frozen", False):
        sys.stdout = NullWriter()
        sys.stderr = NullWriter()

    configure_logging()

prepare_runtime()

def show_startup_error(message: str) -> None:
    """显示启动失败提示。"""
    if platform.system() == "Windows":
        ctypes.windll.user32.MessageBoxW(None, message, "程序启动失败", 0x10)
    else:
        print(message, file=sys.stderr)

def write_startup_log() -> None:
    """将启动异常写入 startup_error.log。"""
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "startup_error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    except Exception:
        pass


import logging
import traceback
from PyQt5.QtWidgets import QApplication

import hmac
import hashlib
import winreg  # 用于读取注册表
import pyperclip
import functools
import random
import win32gui
import win32api
import win32con
import win32ui
import traceback
from paddleocr import PaddleOCR
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QComboBox, QPushButton, QTextEdit,
                             QGroupBox, QMessageBox, QSpinBox, QRadioButton, QSizePolicy,
                             QButtonGroup, QDialog)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QRect
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

import time
from datetime import datetime, timedelta
import json
import cv2
import numpy as np
import re
import gc
import pyautogui
import typing
from typing import Optional, TypeVar

import keyboard
import imagehash
from PIL import Image
import pickle

# ================================= 自己的库 =======================================
from drag_select_window import DraggableSelectorWithOverlay
from window_operator import WindowOperator
from shutdown_dialog import ShutdownDialog
from resolution_m import resolution_ratio_str, resolution_position
from ui import AutomationUI
from worker import Worker
from schedule_dialog import ScheduleDialog
from template_recognizer import ImageProcessor, TemplateRecognizer
from ocr_recognizer import OcrRecognizer
import basic_tools
import nhc

from ui import AutomationUI

def main() -> None:
    """创建并启动主界面事件循环。"""
    app = QApplication(sys.argv)
    main_ui = AutomationUI()
    main_ui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write_startup_log()
        show_startup_error(
            "程序启动失败，可能是程序文件不完整、运行组件缺失。\n\n"
            "错误详情已保存到 startup_error.log"
        )
        sys.exit(1)