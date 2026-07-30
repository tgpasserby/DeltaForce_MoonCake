# ----- 导入官方库 -----
import ctypes
import re
import threading
import time
from datetime import datetime
import sys
import os
from itertools import combinations
from typing import TypeVar, Optional
import json

# ----- 导入三方库 -----
import keyboard
# from pynput import mouse
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,QDoubleSpinBox,QComboBox,
                             QLabel, QLineEdit, QPushButton, QTextEdit,QTabWidget,
                             QGroupBox, QSpinBox, QRadioButton, QSizePolicy,
                             QApplication, QFileDialog, QCheckBox)

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QTime, QObject, QThread
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,  QTableWidget, QTableWidgetItem,
     QAbstractItemView, QHeaderView, QMessageBox
)

# ----- 导入自用库 -----
from resolution_m import resolution_ratio_str, resolution_position
from worker import Worker
from shutdown_dialog import ShutdownDialog
import win32gui
import win32api
import win32con
from drag_select_window import DraggableSelectorWithOverlay
from window_operator import WindowOperator
from schedule_dialog import ScheduleDialog

T = TypeVar("T")

class ControlFlag:
    """
    控制标志类，用于控制线程的停止。
    """
    def __init__(self):
        self.stop = False  # 停止标志，初始为 False

class GlobalListener(QObject):
    """
    全局快捷键监听类。
    利用 keyboard 库轮询键盘状态，结合 Windows API (ctypes) 轮询鼠标状态。
    支持自定义快捷键与硬编码默认键（F9/中键）的双重监听。
    """
    start_signal = pyqtSignal()  # 触发自动化开始的信号
    stop_signal = pyqtSignal()   # 触发自动化停止的信号

    def __init__(self, config_folder:str):
        """
        初始化监听器。
        Args:
            config_folder: 配置文件存放的文件夹路径
        """
        super().__init__()
        self.running:bool = True     # 是否在监听快捷键
        self.paused:bool = False     # 录制期间暂停监听
        self.config_folder:str = config_folder
        self.config_file:str = os.path.join(self.config_folder, "hotkeys.json")

        # 内存中的快捷键配置，默认为 F9 和 鼠标中键
        self.start_cfg:dict[str,str] = {"type": "keyboard", "key": "f9"}
        self.stop_cfg:dict[str,str]  = {"type": "mouse", "key": "middle"}

        # 鼠标虚拟键码 (Virtual Key Codes) 映射表
        self.mouse_map = {
            "middle": win32con.VK_MBUTTON,  # 鼠标中键
            "x1": win32con.VK_XBUTTON1,     # 鼠标侧键1
            "x2": win32con.VK_XBUTTON2,     # 鼠标侧键2
        }

        self.load_from_file()   # 启动时从本地文件恢复配置
        self.listener_thread = threading.Thread(target=self._run, daemon=True)

    def _check_pressed(self, cfg:dict[str,str], is_start=True):
        """
        核心检测函数：判断指定的快捷键（或对应的默认键）是否被按下。
        Args:
            cfg: 配置字典，如 {"type": "keyboard", "key": "ctrl+a"}
            is_start: 是否为启动检测。启动对应默认键 F9，停止对应默认键 鼠标中键。

        Returns:
            bool，True 表示按键处于按下状态。
        """
        # 1. 检测 UI 设置的自定义快捷键
        custom_pressed = False
        if cfg["type"] == "keyboard":
            return keyboard.is_pressed(cfg["key"])
        else:
            vk = self.mouse_map.get(cfg["key"].lower(), 0)
            if vk:
                state = ctypes.windll.user32.GetAsyncKeyState(vk)
                return state & 0x8000 != 0

        # 2. 整合脚本强制默认键逻辑：自定义键 或 默认键 任何一个满足即为按下
        if is_start:
            # 启动：自定义键 OR F9
            return custom_pressed or keyboard.is_pressed('f9')
        else:
            # 停止：自定义键 OR 鼠标中键
            m_vk = win32con.VK_MBUTTON
            middle_pressed = ctypes.windll.user32.GetAsyncKeyState(m_vk) & 0x8000 != 0
            return custom_pressed or middle_pressed

    def _run(self):
        """
        监听线程主循环。以轮询方式检查按键状态。
        """
        while self.running:
            if not self.paused:  # 录制期间不进行业务逻辑检测
                try:
                    # --- 检查启动 ---
                    # 触发条件：自定义快捷键 OR 固定默认值 F9
                    if self._check_pressed(self.start_cfg, is_start=True):
                        self.start_signal.emit()
                        # 阻塞直至用户松开启动按键，防止因轮询过快导致连续触发
                        while self._check_pressed(self.start_cfg, is_start=True):
                            QThread.msleep(10)

                        QThread.msleep(100)

                    # --- 检查停止 ---
                    # 触发条件：自定义快捷键 OR 固定默认值 鼠标中键
                    if self._check_pressed(self.stop_cfg, is_start=False):
                        self.stop_signal.emit()
                        while self._check_pressed(self.stop_cfg, is_start=False):
                            QThread.msleep(10)

                        QThread.msleep(100)
                except Exception:
                    pass
            else:
                # 如果在暂停状态，持续刷新 API 状态，消耗掉录制期间的按键残留
                ctypes.windll.user32.GetAsyncKeyState(win32con.VK_MBUTTON)

            QThread.msleep(20)

    def start(self):
        """启动监听线程"""
        if not self.listener_thread.is_alive():
            self.listener_thread.start()

    def stop(self):
        """停止监听线程循环"""
        self.running = False

    def load_from_file(self):
        """从文件加载快捷键配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 简单校验数据结构
                    if "start" in data and "stop" in data:
                        self.start_cfg = data["start"]
                        self.stop_cfg = data["stop"]
            except Exception:
                pass

    def save_to_file(self):
        """保存当前快捷键配置到文件"""
        os.makedirs(self.config_folder, exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                # 使用 indent=4 方便人工阅读
                json.dump({"start": self.start_cfg, "stop": self.stop_cfg}, f, indent=4)
        except Exception:
            pass

    def update_keys(self, start_cfg: dict, stop_cfg: dict) -> tuple[bool, str]:
        """
        核心校验与更新函数

        Returns:
            (是否成功, 提示消息)
        """
        # 1. 检查格式
        if not start_cfg.get("key") or not stop_cfg.get("key"):
            return False, "按键不能为空"

        # 2. 检查冲突 (类型和按键都相同则冲突)
        if (start_cfg["type"] == stop_cfg["type"] and
            start_cfg["key"].lower() == stop_cfg["key"].lower()):
            return False, "开始和停止快捷键不能相同！"

        # 3. 更新并保存
        self.start_cfg = start_cfg
        self.stop_cfg = stop_cfg
        self.save_to_file()
        return True, "快捷键更新成功"

class HotkeySetter(QPushButton):
    """
    快捷键录制按钮控件。
    点击后进入录制状态，捕获下一个键盘输入或鼠标侧键输入，并将其转换为 keyboard 库可识别的字符串。
    """
    changed = pyqtSignal(dict)  # 发出配置字典 {"type": "keyboard/mouse", "key": "str"}
    record_status_signal = pyqtSignal(bool)  # 录制状态改变信号：True 开始录制，False 结束录制

    def __init__(self, text="未设置", parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)     # 按钮具有切换状态，用于表示是否正在录制
        self.recording:bool = False      # 录制标志位
        self.current_cfg:dict[str,str] = {"type": "keyboard", "key": ""}
        self.setToolTip("点击后按下键盘按键或鼠标侧键进行设置")

    def mousePressEvent(self, event):
        """处理鼠标点击事件以捕获鼠标按键"""
        if not self.recording:
            if event.button() == Qt.LeftButton: # 按钮未处于录制状态时，左键点击触发录制
                self.start_recording()
            return

        # 鼠标映射表：仅保留侧键
        # 注意：不捕获左键（UI交互）、右键（易冲突）和中键（已硬编码为默认停止）。
        btn_map = {
            Qt.XButton1: "x1",
            Qt.XButton2: "x2"
        }
        key_name = btn_map.get(event.button())
        if key_name:
            self.stop_recording("mouse", key_name)

    def keyPressEvent(self, event):
        """处理键盘按下事件以捕获键盘按键"""
        if self.recording:
            # 转换键名
            key = event.key()
            if key == Qt.Key_Escape:
                self.cancel_recording()
                return

            # 调用内部转换函数，将 Qt 键码转为 keyboard 库识别的字符串
            key_name = self._qt_key_to_str(event)
            if key_name:
                self.stop_recording("keyboard", key_name)

    def _qt_key_to_str(self, event)->Optional[str]:
        """
        转换核心逻辑：将 QKeyEvent 转换为类似 "ctrl+shift+f1" 的字符串。
        处理修饰键组合、字母、数字、大小键盘区分及特殊功能键。
        """
        modifiers = event.modifiers()
        key = event.key()

        # 1. 屏蔽单独按下修饰键的情况
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return None

        # 2. 收集修饰键前缀
        parts = []
        if modifiers & Qt.ControlModifier: parts.append("ctrl")
        if modifiers & Qt.ShiftModifier: parts.append("shift")
        if modifiers & Qt.AltModifier: parts.append("alt")

        main_key = ""

        # 3. 处理主按键：
        # 处理 F1-F12
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            main_key = f"f{key - Qt.Key_F1 + 1}"

        # 处理 字母 A-Z (解决组合键字母失效问题)
        elif Qt.Key_A <= key <= Qt.Key_Z:
            main_key = chr(key).lower()

        # 处理 数字 0-9 (区分大小键盘)
        elif Qt.Key_0 <= key <= Qt.Key_9:
            val = chr(key)
            if modifiers & Qt.KeypadModifier:
                main_key = f"numpad {val}"  # 识别为小键盘数字
            else:
                main_key = val              # 识别为主键盘数字

        # 处理 小键盘专用符号
        elif modifiers & Qt.KeypadModifier:
            kp_map = {
                Qt.Key_Slash: "/", Qt.Key_Asterisk: "*",
                Qt.Key_Minus: "-", Qt.Key_Plus: "+",
                Qt.Key_Enter: "enter", Qt.Key_Period: "."
            }
            if key in kp_map:
                # 这里的 enter 不需要加 numpad
                main_key = f"numpad {kp_map[key]}" if key != Qt.Key_Enter else "enter"

        # 处理 其他常用功能键
        if not main_key:
            special_keys = {
                Qt.Key_Space: "space",
                Qt.Key_Return: "enter",
                Qt.Key_Tab: "tab",
                Qt.Key_Backspace: "backspace",
                Qt.Key_Delete: "delete",
                Qt.Key_Left: "left",
                Qt.Key_Up: "up",
                Qt.Key_Right: "right",
                Qt.Key_Down: "down",
                Qt.Key_Home: "home",
                Qt.Key_End: "end",
                Qt.Key_PageUp: "page up",
                Qt.Key_PageDown: "page down"
            }
            if key in special_keys:
                main_key = special_keys[key]
            else:
                # 最后保底：符号类（如 /, [, , 等）使用 text()
                main_key = event.text().lower()

        if not main_key: return None

        # 4. --- 屏蔽 Windows 常用自带快捷键 ---
        full_key = "+".join(parts + [main_key])
        forbidden_keys = [
            "f9","alt+f4", "alt+tab", "ctrl+alt+delete",
            "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+a", "ctrl+s",
            "alt+space", "ctrl+esc"
        ]
        if full_key in forbidden_keys:
            return None

        parts.append(main_key)
        # 生成 keyboard 库识别的格式，如 "ctrl+a" 或 "numpad 1"
        return "+".join(parts)

    def start_recording(self):
        """进入录制状态"""
        self.recording = True
        self.record_status_signal.emit(True)    # 通知外部（如监听器）进入暂停模式
        self.setText("请按键...")
        self.grabKeyboard()                     # 强制捕获所有键盘输入
        self.setFocus()

    def cancel_recording(self):
        """取消录制状态，不保存任何更改"""
        self.recording = False
        self.releaseKeyboard()
        self.setChecked(False)
        self.update_display()                   # 恢复显示原来的配置
        self.record_status_signal.emit(False)   # 通知监听器恢复工作

    def stop_recording(self, itype:str, key:str):
        """完成录制，保存新配置"""
        self.recording = False
        self.releaseKeyboard()
        self.setChecked(False)
        self.current_cfg = {"type": itype, "key": key}
        self.update_display()
        self.record_status_signal.emit(False)   # 通知外部恢复监听
        self.changed.emit(self.current_cfg)     # 发射信号供 UI 逻辑处理（如校验、存盘）

    def update_display(self):
        """更新按钮上显示的文字内容"""
        prefix = "鼠标-" if self.current_cfg["type"] == "mouse" else ""
        self.setText(f"{prefix}{self.current_cfg['key'].upper()}")

    def set_cfg(self, cfg):
        """供外部初始化或还原配置"""
        self.current_cfg = cfg
        self.update_display()

class AutomationUI(QWidget):
    """
    自动化工具的用户界面类。
    """
    start_automation_signal = pyqtSignal()
    stop_automation_signal = pyqtSignal()

    def __init__(self):
        """
        初始化用户界面。
        """
        super().__init__()
        # self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)  # 窗口置顶
        self.resolution = '2560*1600'  # 默认分辨率
        self.flag = ControlFlag()  # 记录任务是否应该结束
        self.flag.stop = True
        self.user_stopped = False  # 记录是否用户手动停止

        self.start_automation_signal.connect(self.start_automation)
        self.stop_automation_signal.connect(self.stop_automation)
        self.op_large = WindowOperator()    # 大号
        self.op_small = WindowOperator()    # 小号
        self.need_dual = False              # 是否需要双端
        self.currently_topmost_hwnd = 0     # 当前置顶得窗口

        # 配置文件路径
        self.config_folder = os.path.join(os.path.dirname(sys.argv[0]), "config_bullets")
        self.config_path = os.path.join(self.config_folder, 'config.json')

        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)  # 确保配置文件夹存在

        # ==================== 新的定时任务管理 ====================
        # 一个哨兵定时器，它会统一检查所有定时任务
        self.schedule_sentinel = QTimer(self)
        self.schedule_sentinel.setInterval(10 * 1000) # 每10秒检查一次就足够了
        self.schedule_sentinel.timeout.connect(self.check_schedules)

        # 【2. 状态字典】只存储运行时状态，程序启动时重置,self.schedule_settings 只存储字典
        self.schedule_settings :dict = {
            'tasks': {
                'single': {'name': '单端任务', 'tab_index': 0, 'start_enabled': False, 'end_enabled': False,
                           'start_time': QTime(2, 5), 'end_time': QTime(10, 0)},
                'hoard':  {'name': '屯仓任务', 'tab_index': 1, 'start_enabled': False, 'end_enabled': False,
                           'start_time': QTime(1, 2), 'end_time': QTime(2, 2)},
                'dual':   {'name': '双端任务', 'tab_index': 2, 'start_enabled': False, 'end_enabled': False,
                           'start_time': QTime(0, 3), 'end_time': QTime(1, 0)},
            },
            'close_small_checkbox': True,
            'shutdown': {'enabled': False, 'time': QTime(10, 5)},
        }

        # 下面这个字典用于记录是否已经触发过了，防止重复触发
        self.schedule_states = {
            'tasks': {
                'single': {'start_triggered': False, 'end_triggered': False},
                'hoard' : {'start_triggered': False, 'end_triggered': False},
                'dual'  : {'start_triggered': False, 'end_triggered': False},
            },
            'shutdown': {'triggered_this_session': False},
        }
        self.auto_plan = False  # 如果是定时任务启动的就是 True
        self.auto_tasks = []

        # ==================== 强制杀死定时器 ====================
        self.force_kill_timer = QTimer(self)
        self.force_kill_timer.setSingleShot(True)   # 确保它只触发一次
        self.force_kill_timer.timeout.connect(self.force_kill_worker)
        # =========================================================

        # 用于持有正在运行的Worker线程的引用，防止被垃圾回收
        self.active_worker = None
        self.init_ui()  # 初始化用户界面
        self._setup_config_registry()   # 记录要保存的信息

        self.log_folder = "运行日志"

        self.setup_hotkeys()  # 设置快捷键

        # self._log("[提示] 请先看群里视频教程，不然出问题别来问",color='red')
        self._log("[提示] 别忘记设置里局外锁 60帧！！！",color='red')
        self._log("[提示] 鼠标悬停在输入框有说明的，不懂就先看一下",color='red')
        self._log('')

    def init_ui(self):
        """
        初始化用户界面的组件和布局。
        """
        self.setWindowTitle(f"月饼的三角洲滚仓工具-v1.2.24 开源版")  # 设置窗口标题
        self.setGeometry(500, 500, 800, 600)  # 设置窗口位置和大小
        main_layout = QHBoxLayout()  # 主布局，水平布局
        param_layout = QVBoxLayout()  # 参数设置分组框内的垂直布局
        # === 参数设置区域 ===
        param_group = QGroupBox("参数设置")  # 创建参数设置分组框

        # ==================== 窗口选择区域 ====================
        selector_group = QGroupBox("目标窗口绑定")
        selector_layout = QVBoxLayout()

        # --- 大号选择器 ---
        large_selector_layout = QHBoxLayout()
        large_selector_layout.addWidget(QLabel("大号窗口:"))
        self.selector_btn_large = DraggableSelectorWithOverlay("大号", self)
        large_selector_layout.addWidget(self.selector_btn_large)
        self.info_label_large = QLabel("未绑定 (请拖动左侧图标到游戏窗口)")
        self.info_label_large.setWordWrap(True)
        large_selector_layout.addWidget(self.info_label_large, 1)  # 使用 stretch factor

        # --- 小号选择器 ---
        self.small_account_container = QWidget()  # 创建一个容器
        self.small_selector_layout = QHBoxLayout(self.small_account_container)  # 将布局设给容器
        self.small_selector_layout.setContentsMargins(0, 0, 0, 0)  # 消除边距，保持紧凑
        self.small_selector_layout.addWidget(QLabel("小号窗口:"))
        self.selector_btn_small = DraggableSelectorWithOverlay("小号", self)
        self.small_selector_layout.addWidget(self.selector_btn_small)
        self.info_label_small = QLabel("未绑定 (请拖动左侧图标到游戏窗口)")
        self.info_label_small.setWordWrap(True)
        self.small_selector_layout.addWidget(self.info_label_small, 1)  # 使用 stretch factor
        self.small_account_container.hide() # 默认先把小号选择器隐藏掉

        # --- 悬停状态标签 ---
        self.hover_status_label = QLabel("当前悬停: 无")
        self.hover_status_label.setStyleSheet("color: gray;")

        selector_layout.addLayout(large_selector_layout)
        selector_layout.addWidget(self.small_account_container)
        selector_layout.addWidget(self.hover_status_label)
        selector_group.setLayout(selector_layout)

        # 将整个选择器组添加到参数布局顶部
        param_layout.addWidget(selector_group)

        # 连接信号
        self.selector_btn_large.window_hover_signal.connect(self.update_hover_status)
        self.selector_btn_large.window_selected_signal.connect(self.update_selected_window)
        self.selector_btn_small.window_hover_signal.connect(self.update_hover_status)
        self.selector_btn_small.window_selected_signal.connect(self.update_selected_window)
        # ===================================================

        # ================== 第 2 部分：中间的选项卡区域 =========================
        param_layout.addStretch(1)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        # --- 创建并添加第一个选项卡：“单端设置” ---
        self.create_single_client_tab()
        self.tabs.setTabVisible(0,False)    # 隐藏掉单端
        # --- 创建并添加第二个选项卡：“屯仓” ---
        self.create_hoarding_tab()
        self.tabs.setCurrentIndex(1)
        # --- 创建并添加第三个选项卡：“双端” ---
        self.create_double_client_tab()

        # --- 创建并添加第四个选项卡：“皮肤” ---
        self.create_skin_tab()
        self.tabs.setTabVisible(3,False)    # 隐藏掉皮肤

        # --- 创建并添加第5个选项卡：“测试” ---
        self.create_test_tab()

        # --- 创建并添加“设置”选项卡 ---
        self.create_settings_tab()

        # self.tabs.setTabVisible(3,False)
        # self.tabs.setTabVisible(4,False)

        param_layout.addWidget(self.tabs)
        param_layout.addStretch(1)
        # ===============================================================

        # ========== 定时任务设置按钮 =============
        schedule_layout = QHBoxLayout()
        self.schedule_button = QPushButton("定时任务设置")
        self.schedule_button.setToolTip("点击设置定时自动开始、自动关机和自动屯仓。\n"
                                        "每个任务只能触发一次。")
        self.schedule_button.clicked.connect(self.open_schedule_dialog)
        schedule_layout.addWidget(self.schedule_button)
        schedule_layout.addStretch(1)

        # 启用测试按钮
        self.test = QCheckBox("启用测试")
        self.test.setToolTip("启动测试模式，请仅在无法正常使用的调试使用\n"
                             "debug文件夹放了识别的图片\n"
                             "app.log存储详细日志")

        schedule_layout.addWidget(self.test)
        param_layout.addLayout(schedule_layout)
        # ===============================================================

        # ========== 保存/加载数据按钮 =============
        button_layout = QHBoxLayout()
        button_layout2 = QHBoxLayout()
        self.start_btn = QPushButton("开始")  # 修改按钮文本
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.load_config_btn = QPushButton("加载配置")
        self.save_config_btn = QPushButton("保存配置")

        self.start_btn.clicked.connect(self.start_automation)
        self.stop_btn.clicked.connect(self.stop_automation)
        self.load_config_btn.clicked.connect(self.load_config)
        self.save_config_btn.clicked.connect(self.save_config)

        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout2.addWidget(self.load_config_btn)
        button_layout2.addWidget(self.save_config_btn)
        param_layout.addLayout(button_layout)
        param_layout.addStretch(1)
        param_layout.addLayout(button_layout2)
        param_layout.addStretch(1)
        # ===============================================================

        # ========== 快捷键布局 =============
        hotkey_layout = QHBoxLayout()
        hotkey_label = QLabel("开始: F9        停止: 鼠标中键")
        hotkey_font = QFont("Arial", 12)
        hotkey_font.setBold(True)
        hotkey_label.setFont(hotkey_font)
        hotkey_layout.addWidget(hotkey_label)
        hotkey_layout.addStretch(1)
        # ===============================================================

        # ==================== 新增：置顶复选框 ====================
        self.topmost_checkbox = QCheckBox("窗口置顶")
        self.topmost_checkbox.setToolTip("勾选后，此工具窗口将保持在所有其他窗口的最上方。")
        # 连接 toggled 信号到我们即将创建的槽函数
        self.topmost_checkbox.toggled.connect(self.toggle_window_topmost)
        hotkey_layout.addWidget(self.topmost_checkbox)
        # =========================================================

        param_layout.addLayout(hotkey_layout)
        param_layout.setSpacing(0)      # 让竖向更紧凑
        param_group.setLayout(param_layout)
        param_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        main_layout.addWidget(param_group, stretch=0)
        # ================= 日志显示布局 ====================
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_clear = QPushButton("清空日志")
        self.log_clear.clicked.connect(lambda: self.log_area.clear())
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_area)
        log_layout.addWidget(self.log_clear)
        main_layout.addLayout(log_layout, stretch=1)
        self.setLayout(main_layout)
        # ==================================================
        self.show()

    @staticmethod
    def add_form_row(widgets:list[tuple[str, QWidget] | tuple[str, QWidget, bool]]):
        """
        添加一行，简化代码
        Args:
            widgets: 包含一整行内容的元组，里面包括：
                label_text:标签文本
                widget:组件
                bool: 是否在这组后面添加弹簧，默认为 True

        Returns:
            返回 layout, QLabel
        """

        row = QHBoxLayout()
        labels = [] # 存储这一行创建的所有标签
        n = len(widgets)

        for i, item in enumerate(widgets):
            # --- 预处理：统一转为 (str, QWidget, bool) ---
            if len(item) == 2:
                label_text, widget = item
                # 默认逻辑：中间元素加弹簧(True)，最后一个不加(False)
                add_stretch = True if i < n - 1 else False
            else:
                label_text, widget, add_stretch = item

            # --- 创建并添加控件 ---
            if label_text:
                label = QLabel(label_text)
                labels.append(label)    # 记录引用
                row.addWidget(label)
            else:
                # 即使没文字也占个位，保证 labels 列表索引与 widgets 对应
                labels.append(None)

            row.addWidget(widget)

            # --- 根据控制位添加弹簧 ---
            if add_stretch:
                row.addStretch(1)

        return row, labels  # 返回布局和标签列表

        # row = QHBoxLayout()
        # labels = [] # 存储这一行创建的所有标签
        # n = len(widgets)
        # i = 0
        # for label_text, widget in widgets:
        #     label = QLabel(label_text)
        #     labels.append(label)  # 记录引用
        #     row.addWidget(label)
        #     row.addWidget(widget)
        #
        #     # 在不同控件之间添加弹簧
        #     i+=1
        #     if i<n:
        #         row.addStretch(1)
        #
        # return row, labels # 返回布局和标签列表

    def _log(self, text:str,color:str='black'):
        self.log_message(f"<font color={color}>{text}</font>")

    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        group = QGroupBox("快捷键自定义")
        g_layout = QVBoxLayout()

        # 开始键
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("启动任务:"))
        self.hk_start = HotkeySetter()
        self.hk_start.set_cfg({"type": "keyboard", "key": "f9"})
        h1.addWidget(self.hk_start)
        g_layout.addLayout(h1)

        # 停止键
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("停止任务:"))
        self.hk_stop = HotkeySetter()
        self.hk_stop.set_cfg({"type": "mouse", "key": "middle"})
        h2.addWidget(self.hk_stop)
        g_layout.addLayout(h2)

        group.setLayout(g_layout)
        layout.addWidget(group)

        # 冲突检查提示
        self.hk_warning = QLabel("")
        self.hk_warning.setStyleSheet("color: red;")
        layout.addWidget(self.hk_warning)

        layout.addStretch(1)
        self.tabs.addTab(tab, "设置")

        # 信号连接
        self.hk_start.changed.connect(self.on_hotkey_changed)
        self.hk_stop.changed.connect(self.on_hotkey_changed)

    # def _setup_config_registry(self):
    #     # 现有的注册表...
    #     self.config_registry["hotkey_settings"] = {
    #         "start_key_cfg": (self.hk_start, {"type": "keyboard", "key": "f9"}),
    #         "stop_key_cfg": (self.hk_stop, {"type": "mouse", "key": "middle"}),
    #     }
    #
    #     # 注意：因为 HotkeySetter 是自定义控件，需要修改 _get_widget_value 和 _set_widget_value
    #     # 在 _get_widget_value 中添加：
    #     if isinstance(widget, HotkeySetter):
    #         return widget.current_cfg
    #
    #     # 在 _set_widget_value 中添加：
    #     if isinstance(widget, HotkeySetter):
    #         widget.set_cfg(val)
    #         # 加载完后顺便应用一下
    #         self.apply_hotkeys()

    def create_single_client_tab(self):
        """创建“单端设置”选项卡，并填充相关控件。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        #
        # # ==================== 配装行 ========================
        # self.loadout_widgets = []
        # for i in range(1, 5):
        #     widgets = self._create_loadout_row(layout, i)
        #     self.loadout_widgets.append(widgets)
        # # ====================================================
        #
        # # ==================== 其他参数布局 ====================
        # # 识别延迟
        # row1_layout = QHBoxLayout()
        # row1_layout.addWidget(QLabel("识别延迟:"))
        # self.delay_loadout = QLineEdit("300")
        # self.delay_loadout.setFixedWidth(50)
        # self.delay_loadout.setToolTip("切换到配装后，延迟多久识别价格")
        # row1_layout.addWidget(self.delay_loadout)
        # row1_layout.addStretch(1)
        #
        # # 刷新延迟
        # # row1_layout.addWidget(QLabel("刷新延迟:"))
        # self.delay_small = QLineEdit("100")
        # self.delay_small.setFixedWidth(50)
        # self.delay_small.setToolTip("识别价格后，再次刷新配装的延迟")
        # self.delay_small.hide()
        # row1_layout.addWidget(self.delay_small)
        #
        # # 去大战场得时间
        # row1_layout.addWidget(QLabel("去大战场:"))
        # self.refresh_interval = QLineEdit("15")
        # self.refresh_interval.setFixedWidth(50)
        # self.refresh_interval.setToolTip(f"每隔多少分钟去大战场")
        # row1_layout.addWidget(self.refresh_interval)
        #
        # layout.addLayout(row1_layout)  # 将第一行添加到主参数布局
        # layout.addStretch(1)
        #
        # # --- 第二行：期望价格 和 挡屎价 ---
        # row2_layout = QHBoxLayout()
        # row2_layout.addStretch(1)
        # # 子弹数量
        # row2_layout.addWidget(QLabel("子弹数量:"))
        # self.bullet_quantity = QLineEdit("1")
        # self.bullet_quantity.setFixedWidth(50)
        # self.bullet_quantity.setToolTip("配装方案一次购买的子弹数量。")
        # row2_layout.addWidget(self.bullet_quantity)
        #
        #
        # layout.addLayout(row2_layout)
        # layout.addStretch(1)
        # # ================= 延迟吃等待时间行布局 ====================
        # # 延迟吃等待多久：
        # delay_eat_layout = QHBoxLayout()
        # delay_eat_layout.addWidget(QLabel('延迟吃等待时间:'))
        # self.delay_eat_min = QDoubleSpinBox()
        # self.delay_eat_min.setRange(0.0, 100.0)
        # self.delay_eat_min.setSingleStep(0.1)
        # self.delay_eat_min.setDecimals(1)
        # self.delay_eat_min.setValue(1)  # 默认最短0.5s
        # self.delay_eat_min.setToolTip("识别完价格后，等待时间下限")
        # self.delay_eat_min.setSuffix("秒")
        # self.delay_eat_min.setFixedWidth(80)
        # delay_eat_layout.addWidget(self.delay_eat_min)
        # delay_eat_layout.addWidget(QLabel('至'))
        #
        # self.delay_eat_max = QDoubleSpinBox()
        # self.delay_eat_max.setRange(0.0, 100.0)
        # self.delay_eat_max.setSingleStep(0.1)
        # self.delay_eat_max.setDecimals(1)
        # self.delay_eat_max.setValue(5)  # 默认最久5s
        # self.delay_eat_max.setToolTip("识别完价格后，等待时间上限")
        # self.delay_eat_max.setSuffix("秒")
        # self.delay_eat_max.setFixedWidth(80)
        # delay_eat_layout.addWidget(self.delay_eat_max)
        # delay_eat_layout.addStretch(1)
        #
        # # 秒吃按钮
        # self.fast_eat = QRadioButton("秒吃")
        # self.fast_eat.setToolTip("勾选后，检测到低价直接吃。开启后延迟吃等待失效")
        # delay_eat_layout.addWidget(self.fast_eat)
        # layout.addLayout(delay_eat_layout)
        # layout.addStretch(1)
        #
        # # ================= 自动售卖按钮行布局 ====================
        # self.auto_sell = QGroupBox("自动售卖")
        # self.auto_sell.setCheckable(True)
        # self.auto_sell.setChecked(True)
        # self.auto_sell.setToolTip('勾选后，购买成功会自动去仓库卖出。')
        # self.auto_sell.toggled.connect(lambda x:self.set_visible_group(x,self.auto_sell))
        # # self.auto_sell.setAlignment(Qt.AlignLeft)  # 标题靠左
        # # self.auto_sell.setFlat(True)
        #
        # options_layout = QHBoxLayout()
        # options_layout.setContentsMargins(0, 3, 0, 3)  # 重点：去掉内部边距
        # # options_layout.setSpacing(0)  # 控件间距设为0
        #
        # # 自动出售的价格档位
        # options_layout.addWidget(QLabel("档位"))
        # self.auto_sell_price = QComboBox()
        # self.auto_sell_price.addItems(["市场价","低一档","低两档"])
        # self.auto_sell_price.setCurrentText("低一档")
        # self.auto_sell_price.setFixedWidth(90)
        # self.auto_sell_price.setToolTip("自动出售的价格")
        # options_layout.addWidget(self.auto_sell_price)
        # options_layout.addStretch(1)
        #
        # # 最低出售价
        # options_layout.addWidget(QLabel("最低出售价"))
        # self.min_sell_price = QLineEdit("0")
        # self.min_sell_price.setFixedWidth(50)
        # self.min_sell_price.setToolTip("自动出售时，挂单的最低价格。")
        # options_layout.addWidget(self.min_sell_price)
        # options_layout.addStretch(1)
        #
        # # 领邮件的频率
        # options_layout.addWidget(QLabel('领邮件  '))
        # self.receive_mail = QSpinBox()
        # self.receive_mail.setRange(1, 10)
        # self.receive_mail.setValue(1)  # 默认每3次成功，领一次邮件
        # self.receive_mail.setToolTip("领邮件的频率，1就是每成功购买1次去领一回邮件，以此类推")
        # self.receive_mail.setSuffix("次")
        # self.receive_mail.setFixedWidth(50)
        # options_layout.addWidget(self.receive_mail)
        #
        # # 添加到主 ui
        # self.auto_sell.setLayout(options_layout)
        # layout.addWidget(self.auto_sell)
        # layout.addStretch(1)
        #
        # # ================= 自动挡屎布局 ====================
        # self.auto_block_shit_option = QGroupBox("自动挡屎")
        # self.auto_block_shit_option.setCheckable(True)
        # self.auto_block_shit_option.setChecked(False)
        #
        # self.auto_block_shit_option.setToolTip('勾选后会自动调整挡屎价，需要输入挡位差价')
        # self.auto_block_shit_option.toggled.connect(lambda x:self.set_visible_group(x,self.auto_block_shit_option))
        # # self.auto_sell.setAlignment(Qt.AlignLeft)  # 标题靠左
        # # self.auto_sell.setFlat(True)
        #
        # auto_block_shit_layout = QHBoxLayout()
        # auto_block_shit_layout.setContentsMargins(0, 1, 0, 5)  # 重点：去掉内部边距
        #
        # # 自动档位选择
        # auto_block_shit_layout.addWidget(QLabel("档位"))
        # self.price_range = QComboBox()
        # self.price_range.addItems([f"低{i}档" for i in range(1,6+1)])
        # self.price_range.setCurrentText("低3档")
        # self.price_range.setFixedWidth(90)
        # # self.price_range.setEnabled(False)
        # auto_block_shit_layout.addWidget(self.price_range)
        # auto_block_shit_layout.addStretch(1)
        #
        # # 自动档位最高价格
        # auto_block_shit_layout.addWidget(QLabel("最高挡屎价"))
        # self.auto_block_max = QLineEdit()
        # self.auto_block_max.setFixedWidth(50)
        # self.auto_block_max.setToolTip("自动挡屎的最高价格")
        # auto_block_shit_layout.addWidget(self.auto_block_max)
        # auto_block_shit_layout.addStretch(1)
        #
        # # 档位差价
        # auto_block_shit_layout.addWidget(QLabel("档位差价"))
        # self.price_diff = QLineEdit()
        # self.price_diff.setFixedWidth(50)
        # # self.price_diff.setEnabled(False)
        # self.price_diff.setToolTip("就是游戏内交易行该商品两个柱子之间的差价")
        # auto_block_shit_layout.addWidget(self.price_diff)
        #
        # # layout.addLayout(auto_block_shit_layout)
        # self.auto_block_shit_option.setLayout(auto_block_shit_layout)
        # self.set_visible_group(False,self.auto_block_shit_option)
        # layout.addWidget(self.auto_block_shit_option)
        # layout.addStretch(1)

        self.tabs.addTab(tab, "单端")

    def create_double_client_tab(self):
        """创建“双端设置”选项卡，并填充相关控件。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ==================== 第1行 ========================
        # 选择配装
        row0 = []
        self.loadout_combo = QComboBox()
        self.loadout_combo.setFixedWidth(100)
        self.loadout_combo.addItem("")  # 第一个是空白选项
        for i in range(1, 6):  # 添加 1 到 5 号配装
            self.loadout_combo.addItem(f"配装 {i}")
        row0.append(("选择配装:", self.loadout_combo))  # 添加内容

        # 去大战场得时间
        self.refresh_interval_double = QSpinBox()
        self.refresh_interval_double.setRange(0, 60)
        self.refresh_interval_double.setSingleStep(1)
        self.refresh_interval_double.setValue(15)
        self.refresh_interval_double.setSuffix(" min")
        self.refresh_interval_double.setFixedWidth(100)
        self.refresh_interval_double.setToolTip("每隔多少分钟去大战场")
        row0.append(("去大战场:", self.refresh_interval_double))  # 添加内容

        row0_layout, _ = self.add_form_row(row0)
        layout.addLayout(row0_layout)  # 将第一行添加到主参数布局
        layout.addStretch(1)
        # ==================================================

        # ==================== 第2行 ========================
        # 配装延迟
        row1 = []
        self.delay_loadout_double = QSpinBox()
        self.delay_loadout_double.setRange(0, 10000)
        self.delay_loadout_double.setSingleStep(10)
        self.delay_loadout_double.setValue(300)
        self.delay_loadout_double.setSuffix(" ms")
        self.delay_loadout_double.setFixedWidth(100)
        self.delay_loadout_double.setToolTip("切换到配装后，延迟多久识别价格")
        row1.append(("识别延迟:", self.delay_loadout_double))  # 添加内容

        # 小号点击延迟
        self.small_buy_circle = QSpinBox()
        self.small_buy_circle.setRange(0, 10000)
        self.small_buy_circle.setSingleStep(10)
        self.small_buy_circle.setValue(450)
        self.small_buy_circle.setSuffix(" ms")
        self.small_buy_circle.setFixedWidth(100)
        self.small_buy_circle.setToolTip("小号每次探测之间得间隔时间（周期）")
        row1.append(("小号周期:", self.small_buy_circle))  # 添加内容

        # 小号看价延迟
        self.delay_see_price = QSpinBox()
        self.delay_see_price.setRange(0, 10000)
        self.delay_see_price.setSingleStep(10)
        self.delay_see_price.setValue(100)
        self.delay_see_price.setSuffix(" ms")
        self.delay_see_price.setFixedWidth(100)
        self.delay_see_price.setToolTip(f"小号鼠标在右上角价格停留的时间，太短会导致捕捉不到价格\n"
                                        f"只要能捕捉到价格就不用改。")
        # row1.append(("看价时间:", self.delay_see_price))  # 添加内容

        row1_layout, _ = self.add_form_row(row1)
        layout.addLayout(row1_layout)  # 将第一行添加到主参数布局
        layout.addStretch(1)
        # ==================================================

        # ==================== 第3行 ========================
        row2 = []
        row2_layout = QHBoxLayout()

        # 期望价格
        self.target_price_double = QSpinBox()
        self.target_price_double.setRange(0, 10000)
        self.target_price_double.setSingleStep(10)
        self.target_price_double.setValue(0)
        self.target_price_double.setFixedWidth(100)
        self.target_price_double.setToolTip("小号买到子弹后，你期望的真实成交价。\n低于此价格才会用大号抢购。")
        row2.append(("期望单价:", self.target_price_double))

        # 子弹数量
        self.bullet_quantity_double = QSpinBox()
        self.bullet_quantity_double.setRange(1, 10000)
        self.bullet_quantity_double.setSingleStep(10)
        self.bullet_quantity_double.setValue(1)
        self.bullet_quantity_double.setFixedWidth(100)
        self.bullet_quantity_double.setToolTip("配装方案一次购买的子弹数量。")
        row2.append(("子弹数量:", self.bullet_quantity_double))

        row2_layout, _ = self.add_form_row(row2)
        layout.addLayout(row2_layout)
        layout.addStretch(1)
        # ==================================================

        # ==================== 第4行 ======================== （已隐藏）
        row3_layout = QHBoxLayout()
        # 探测数量
        row3_layout.addWidget(QLabel("探测数量:"))
        self.detect_quantity_double = QLineEdit("31")
        self.detect_quantity_double.setEnabled(False)
        self.detect_quantity_double.setFixedWidth(50)
        self.detect_quantity_double.setToolTip("探测时每次买多少发")
        row3_layout.addWidget(self.detect_quantity_double)
        row3_layout.addStretch(1)

        # 隐藏小号探测数量
        # layout.addLayout(row3_layout)
        # layout.addStretch(1)

        # ================= 自动售卖行布局 ====================
        self.auto_sell_double = QGroupBox("自动售卖")
        self.auto_sell_double.setCheckable(True)
        self.auto_sell_double.setChecked(True)
        self.auto_sell_double.setToolTip('勾选后，购买成功会自动去仓库卖出。')
        self.auto_sell_double.toggled.connect(lambda x:self.set_visible_group(x,self.auto_sell_double))

        row4_layout = QHBoxLayout()
        row4_layout.setContentsMargins(0, 3, 0, 3)  # 重点：去掉内部边距

        # 自动出售的价格档位
        row4_layout.addWidget(QLabel("档位"))
        self.auto_sell_price_double = QComboBox()
        self.auto_sell_price_double.addItems(["市场价","低一档","低两档"])
        self.auto_sell_price_double.setCurrentText("低一档")
        self.auto_sell_price_double.setFixedWidth(90)
        self.auto_sell_price_double.setToolTip("自动出售的价格")
        row4_layout.addWidget(self.auto_sell_price_double)
        row4_layout.addStretch(1)

        # 最低出售价
        row4_layout.addWidget(QLabel("最低售价"))
        self.min_sell_price_double = QSpinBox()
        self.min_sell_price_double.setRange(0, 10000)
        self.min_sell_price_double.setSingleStep(10)
        self.min_sell_price_double.setValue(0)
        self.min_sell_price_double.setFixedWidth(70)
        self.min_sell_price_double.setToolTip("自动出售时，挂单的最低价格。")
        row4_layout.addWidget(self.min_sell_price_double)
        row4_layout.addStretch(1)

        # 领邮件的频率
        row4_layout.addWidget(QLabel('领邮件'))
        self.receive_mail_double = QSpinBox()
        self.receive_mail_double.setRange(1, 1000)
        self.receive_mail_double.setValue(3)  # 默认每3次成功，领一次邮件
        self.receive_mail_double.setToolTip("领邮件的频率，1就是每成功购买1次去领一回邮件，以此类推")
        self.receive_mail_double.setSuffix("次")
        self.receive_mail_double.setFixedWidth(60)
        row4_layout.addWidget(self.receive_mail_double)

        # layout.addLayout(row4_layout)
        self.auto_sell_double.setLayout(row4_layout)
        layout.addWidget(self.auto_sell_double)
        # layout.addStretch(1)
        # ==================================================

        # ================== 自动挡屎布局 =====================（已隐藏）
        # --- 创建双端自动挡屎 ---
        auto_block_data = self.create_auto_block_group("自动挡屎")
        # 挂载控件引用，方便后续读取数据
        self.auto_block_shit_option_double = auto_block_data["group"]
        self.price_range_double = auto_block_data["combo"]
        self.auto_block_max_double = auto_block_data["max_input"]
        self.price_diff_double = auto_block_data["diff_input"]
        # # 隐藏自动挡屎标签
        # layout.addWidget(self.auto_block_shit_option_double)
        # layout.addStretch(1)
        # ==================================================

        self.tabs.addTab(tab, "双端")

    def create_hoarding_tab(self):
        """创建“屯仓”选项卡，并添加新的控件。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ==================== 第1行：屯仓数量 和 屯仓模式 ====================
        # 屯仓数量
        self.hoard_target_quantity = QSpinBox()
        self.hoard_target_quantity.setRange(1, 999999)
        self.hoard_target_quantity.setSingleStep(100)
        self.hoard_target_quantity.setValue(10000)
        self.hoard_target_quantity.setFixedWidth(100)
        self.hoard_target_quantity.setToolTip("每次运行的最大购买数量")

        # 刷新模式
        self.hoard_mode = QComboBox()
        self.hoard_mode.addItems(["默认", "无探测","双端屯仓"])
        self.hoard_mode.setCurrentText("默认")
        self.hoard_mode.setFixedWidth(100)
        self.hoard_mode.setToolTip("默认模式：每次购买31发探测价格\n"
                                   "无探测模式：反复刷新，直接读取价格")
        self.hoard_mode.currentTextChanged.connect(self.set_hoard_mode)

        quantity_price_layout, _ = self.add_form_row([
            ("屯仓数量:", self.hoard_target_quantity),
            ("屯仓模式:", self.hoard_mode),
        ])
        layout.addLayout(quantity_price_layout)
        layout.addStretch(1)

        # ==================== 第2行：买入低价 和 买入单价 ====================
        # 买入底价
        self.hoard_min_price = QSpinBox()
        self.hoard_min_price.setRange(0, 9999)
        self.hoard_min_price.setSingleStep(10)
        self.hoard_min_price.setValue(0)
        self.hoard_min_price.setFixedWidth(100)
        self.hoard_min_price.setToolTip("购买价格下限。")

        # 买入高价
        self.hoard_max_price = QSpinBox()
        self.hoard_max_price.setRange(0, 9999)
        self.hoard_max_price.setSingleStep(10)
        self.hoard_max_price.setValue(0)
        self.hoard_max_price.setFixedWidth(100)
        self.hoard_max_price.setToolTip("购买价格上限。")

        buy_circle_layout, _ = self.add_form_row([
            ("买入低价:", self.hoard_min_price),
            ("买入单价:", self.hoard_max_price)
        ])
        layout.addLayout(buy_circle_layout)
        layout.addStretch(1)

        # ==================== 第3行：购买周期 和 探测周期 ====================
        # 探测数量（已隐藏）
        self.detect_quantity = QComboBox()
        self.detect_quantity.addItem("32")  # 添加 "31"
        self.detect_quantity.addItem("11")  # 添加 "11"
        self.detect_quantity.setCurrentText("32")
        self.detect_quantity.setFixedWidth(100)
        self.detect_quantity.setToolTip("探测时，每次买多少发")

        # 购买周期
        self.buy_circle = QSpinBox()
        self.buy_circle.setRange(0, 10000)
        self.buy_circle.setSingleStep(10)
        self.buy_circle.setValue(430)
        self.buy_circle.setSuffix(" ms")
        self.buy_circle.setFixedWidth(100)
        self.buy_circle.setToolTip("买入低价时，购买的时间间隔")

        # --- 模式 A: 探测周期控件 ---
        self.detect_circle = QSpinBox()
        self.detect_circle.setRange(0, 10000)
        self.detect_circle.setSingleStep(100)
        self.detect_circle.setValue(5000)
        self.detect_circle.setSuffix(" ms")
        self.detect_circle.setFixedWidth(100)
        self.detect_circle.setToolTip("探测时，购买的时间间隔")

        # --- 模式 B: 无探测模式得刷新周期 (默认隐藏) ---
        self.refresh_rate = QSpinBox()
        self.refresh_rate.setRange(0, 10000)
        self.refresh_rate.setSingleStep(10)
        self.refresh_rate.setValue(150)
        self.refresh_rate.setSuffix(" ms")
        self.refresh_rate.setFixedWidth(100)
        self.refresh_rate.setToolTip("探测时，刷新的时间间隔")

        detect_layout, row3_labels = self.add_form_row([
            ("购买周期:", self.buy_circle),
            ("探测周期:", self.detect_circle, False),
            ("刷新速率:", self.refresh_rate),
        ])

        # ----- 从返回的列表里提取标签引用 -----
        self.label_detect_circle = row3_labels[1]
        self.label_refresh_rate = row3_labels[2]

        # ----- 初始状态：隐藏刷新速率相关的控件 -----
        self.label_refresh_rate.hide()
        self.refresh_rate.hide()

        layout.addLayout(detect_layout)
        layout.addStretch(1)

        # ==================== 第4行：子弹名称 和 购买位置 ====================
        # 子弹名称
        self.bullet_name_input = QLineEdit()  # 创建一个行编辑器用于输入
        self.bullet_name_input.setPlaceholderText("例如: 7.62x39")  # 设置提示文本
        self.bullet_name_input.setFixedWidth(150)  # 可以根据需要调整宽度
        self.bullet_name_input.setToolTip("输入要购买的子弹的全名或关键词,记得先在交易行看一下")

        # 购买位置
        self.purchase_location_selector = QComboBox()
        self.purchase_location_selector.setFixedWidth(100)
        self.purchase_location_selector.setToolTip("有的会搜出来多种，请选择正确的位置")
        self.purchase_location_selector.addItem("")  # 添加一个默认的空选项
        positions = [f"{row}行{col}" for row in range(1, 3) for col in range(1, 4)]
        self.purchase_location_selector.addItems(positions)

        bullet_info_layout, _ = self.add_form_row([
            ("子弹名称:", self.bullet_name_input),
            ("购买位置:", self.purchase_location_selector)
        ])
        layout.addLayout(bullet_info_layout)
        layout.addStretch(1)

        # ==================== 进阶设置 (GroupBox) ====================
        adv_data = self.create_advanced_settings_group()
        self.adv_group_hoarding = adv_data["group"] # 记录容器引用以便控制显隐
        self.dynamic_sleep_hoarding = adv_data["dynamic_sleep"]
        self.continuous_buy_hoarding = adv_data["continuous_buy"]
        self.continuous_detect_hoarding = adv_data["continuous_detect"]
        layout.addWidget(self.adv_group_hoarding)

        # ================= 自动挡屎布局 ====================
        # --- 创建双端自动挡屎 ---
        auto_block_data = self.create_auto_block_group("自动调整买入价")
        # 挂载控件引用，方便后续读取数据
        self.auto_block_shit_option_hoarding = auto_block_data["group"]
        self.price_range_hoarding = auto_block_data["combo"]
        self.auto_block_max_hoarding = auto_block_data["max_input"]
        self.price_diff_hoarding = auto_block_data["diff_input"]
        self.auto_block_shit_check_hoarding = auto_block_data["check"]
        self.auto_block_shit_option_hoarding.hide()

        # 隐藏自动挡屎标签
        layout.addWidget(self.auto_block_shit_option_hoarding)

        self.tabs.addTab(tab, "屯仓")

    def create_advanced_settings_group(self, title="进阶设置"):
        """
        创建一个进阶设置组（QGroupBox）。
        返回包含组对象和具体控件引用的字典。
        """
        group = QGroupBox(title)
        # 如果需要像自动挡屎那样带勾选框，可以取消下面两行的注释
        # group.setCheckable(True)
        # group.setChecked(False)

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # 动态休眠
        dynamic_sleep = QCheckBox("动态休眠")
        dynamic_sleep.setToolTip("开启后，如果多次未探测到低价，则会自动逐渐延长探测时间")

        # 连买次数
        continuous_buy = QSpinBox()
        continuous_buy.setRange(0, 100)
        continuous_buy.setValue(0)
        continuous_buy.setFixedWidth(50)
        continuous_buy.setToolTip("探测到低价后，大号最多购买几次，0表示无限次，1表示一探一买")

        # 连探次数
        continuous_detect = QSpinBox()
        continuous_detect.setRange(1, 10)
        continuous_detect.setValue(1)
        continuous_detect.setFixedWidth(50)
        continuous_detect.setToolTip("小号连续探测到多次低价，才会让大号购买")

        # 组装布局
        layout.addWidget(dynamic_sleep)
        layout.addStretch(1)
        layout.addWidget(QLabel("连买次数:"))
        layout.addWidget(continuous_buy)
        layout.addStretch(1)
        layout.addWidget(QLabel("连探次数:"))
        layout.addWidget(continuous_detect)

        group.setLayout(layout)

        return {
            "group": group,
            "dynamic_sleep": dynamic_sleep,
            "continuous_buy": continuous_buy,
            "continuous_detect": continuous_detect
        }

    def create_auto_block_group(self, title="自动挡屎"):
        """
        创建一个自动挡屎的配置组。
        返回一个包含控件引用的字典。
        """
        # 1. 创建容器
        group = QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(False)
        group.setToolTip('勾选后会自动调整买入价，需要输入挡位差价')

        # 绑定显示/隐藏逻辑
        group.toggled.connect(lambda x: self.set_visible_group(x, group))

        # 2. 创建内部控件
        # 档位选择 (ComboBox)
        range_combo = QComboBox()
        range_combo.addItems([f"低{i}档" for i in range(1, 6 + 1)])
        range_combo.setCurrentText("低3档")
        range_combo.setFixedWidth(80)

        # 最高挡屎价
        max_price_input = QSpinBox()
        max_price_input.setRange(1,99999)
        max_price_input.setFixedWidth(70)
        max_price_input.setToolTip("自动买入的最高价格，不会超过这个价格")

        # 档位差价
        price_diff_input = QSpinBox()
        price_diff_input.setFixedWidth(50)
        price_diff_input.setRange(1, 999)
        price_diff_input.setToolTip("就是游戏内交易行该商品两个柱子之间的差价")

        # 3. 布局组装
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        layout.addWidget(QLabel("档位:"))
        layout.addWidget(range_combo)
        layout.addStretch(1)

        layout.addWidget(QLabel("最高价:"))
        layout.addWidget(max_price_input)
        layout.addStretch(1)

        layout.addWidget(QLabel("差价:"))
        layout.addWidget(price_diff_input)

        group.setLayout(layout)

        # 3.1 【核心逻辑】定义验证与提取函数
        def get_params() -> tuple[bool, int, int, int]:
            """
            返回: (是否开启,  档位数字, 最高价, 挡位差价)
            """
            # 情况 A: 不开启 自动调整
            if not group.isChecked():
                return False, 0, 0, 0

            # 情况 B: 开启 自动调整
            match = re.search(r'\d+', range_combo.currentText())
            rank = int(match.group()) if match else 0
            return True, rank, max_price_input.value(),price_diff_input.value()

        # 4. 返回字典，方便外部调用
        return {
            "group": group,
            "combo": range_combo,
            "max_input": max_price_input,
            "diff_input": price_diff_input,
            "check": get_params,
        }

    @staticmethod
    def set_visible_group(checked, group_box):
        """设置 QGroupBox 内部所有控件的可见状态"""
        pass
        # # 获取 GroupBox 的布局
        # layout = group_box.layout()
        # if layout is None:
        #     return
        #
        # # 遍历布局里的每一个项目
        # for i in range(layout.count()):
        #     item = layout.itemAt(i)
        #     widget = item.widget()
        #     if widget:
        #         # 设置控件的可见性
        #         widget.setVisible(checked)

        # 可选：如果希望隐藏后 GroupBox 自身也缩小，可以调整它的高度
        # group_box.setFixedHeight(group_box.sizeHint().height() if checked else 30)

    def create_skin_tab(self):
        """创建“抢皮肤”选项卡，并填充相关控件。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row1_layout = QHBoxLayout()
        # ==================== 购买次数 ========================
        self.skin_buy_times = QSpinBox()
        self.skin_buy_times.setRange(1, 99)
        self.skin_buy_times.setValue(1)
        self.skin_buy_times.setFixedWidth(100)

        row1_layout.addWidget(QLabel('购买次数:'))
        row1_layout.addWidget(self.skin_buy_times)
        # ====================================================

        layout.addLayout(row1_layout)
        layout.addStretch(1)

        self.tabs.addTab(tab, "枪皮")

    def create_test_tab(self):
        """创建“测试”选项卡，并填充相关控件。"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.tabs.addTab(tab, "测试")

    def set_dual_mode(self, is_dual: bool):
        """
        切换单端/双端模式

        Args:
            is_dual: True 为双端模式（显示小号），False 为单端模式（隐藏小号）
        """
        if is_dual:
            self.small_account_container.show()
        else:
            self.small_account_container.hide()
            # 可选：切换回单端时，清空小号绑定的信息
            # self.info_label_small.setText("未绑定 (请拖动左侧图标到游戏窗口)")

    def set_hoard_mode(self):
        """根据选择的屯仓模式，禁用或启用相关控件"""
        mode = self.hoard_mode.currentText().strip()

        # ----- 默认的单端设置 -----
        detect_quantity_set = True      # 每次探测数量
        detect_circle_set = True        # 探测时间
        bullet_name_input_set = True    # 输入物品名称
        purchase_location_set = True    # 购买位置
        auto_block_shit = False         # 自动挡屎是否显示
        adv_settings_visible = True     # 进阶设置
        label_detect_circle = True      # 显示探测周期文字
        detect_circle_visible = True    # 显示探测周期输入框

        if mode == "默认":
            self._log("[屯仓] 默认为单端屯仓", color='blue')
        elif mode == "无探测":
            self._log("[屯仓] 无探测模式，默认只买收藏第一个物品（可设置购买位置）",color='blue')
            detect_quantity_set = False     # 每次探测数量
            detect_circle_set = False       # 探测时间
            # bullet_name_input_set = False   # 输入物品名称
            # purchase_location_set = False   # 购买位置
            auto_block_shit = True
            adv_settings_visible = False    # 无探测模式下隐藏进阶设置
            label_detect_circle = False     # 隐藏探测周期文字
            detect_circle_visible = False   # 隐藏探测周期输入框

        elif mode == "双端屯仓":
            self._log("[屯仓] 双端屯仓模式，小号探测价格，大号购买。请两个号都在购买界面。", color='blue')
            # detect_quantity_set = True      # 每次探测数量
            # detect_circle_set = True        # 探测时间
            bullet_name_input_set = False   # 输入物品名称
            purchase_location_set = False   # 购买位置

        self.detect_quantity.setEnabled(detect_quantity_set)
        self.detect_circle.setEnabled(detect_circle_set)
        self.bullet_name_input.setEnabled(bullet_name_input_set)
        self.purchase_location_selector.setEnabled(purchase_location_set)
        self.auto_block_shit_option_hoarding.setVisible(auto_block_shit)
        self.adv_group_hoarding.setVisible(adv_settings_visible)
        self.label_detect_circle.setVisible(label_detect_circle)
        self.detect_circle.setVisible(detect_circle_visible)
        self.label_refresh_rate.setVisible(not label_detect_circle)
        self.refresh_rate.setVisible(not detect_circle_visible)

        # 启动/隐藏 小号选择器
        if mode == "双端屯仓":
            self.need_dual = True
        else:
            self.need_dual = False

        self.set_dual_mode(self.need_dual)

    def on_tab_changed(self, index):
        """当标签页切换时，调用不同的处理函数。"""
        current_tab_text = self.tabs.tabText(index)
        if current_tab_text == "双端":
            self.need_dual = True
        elif current_tab_text == "屯仓":
            if self.hoard_mode.currentText() == "双端屯仓":
                self.need_dual = True
            else:
                self.need_dual = False
        else:
            self.need_dual = False

        self.set_dual_mode(self.need_dual)

    def _create_loadout_row(self, layout, index):
        """
        创建包含复选框、标签和两个价格输入框的“配装方案”行。（旧版）
        """
        hbox = QHBoxLayout()
        # checkbox = QCheckBox(f"配装方案{index}")
        checkbox = QRadioButton(f"配装方案{index}")
        checkbox.setChecked(False)

        max_price_label = QLabel("挡屎价:")
        max_price_entry = QLineEdit("0")
        max_price_entry.setFixedWidth(80)
        max_price_entry.setToolTip("当市场价格低于或等于此价格时，尝试购买。")

        min_price_label = QLabel("最低价:")
        min_price_entry = QLineEdit("30")
        min_price_entry.setFixedWidth(80)
        min_price_entry.setToolTip("用于防止价格识别错误。\n如果识别到的价格低于此值，则视为无效价格。")

        hbox.addWidget(checkbox)
        hbox.addStretch(1)
        hbox.addWidget(max_price_label)
        hbox.addWidget(max_price_entry)
        # 隐藏挡屎价
        max_price_label.hide()
        max_price_entry.hide()
        # hbox.addStretch(1)
        hbox.addWidget(min_price_label)
        hbox.addWidget(min_price_entry)
        min_price_label.hide()
        min_price_entry.hide()

        layout.addLayout(hbox)
        layout.addStretch(1)

        return checkbox, max_price_entry, min_price_entry

    def _create_loadout_dropdown_row(self, layout, combo_box):
        """
        创建包含下拉菜单和价格输入框的单行布局
        """
        hbox = QHBoxLayout()

        # 价格输入框（保持你原来的逻辑）
        max_price_label = QLabel("挡屎价:")
        max_price_entry = QLineEdit("0")
        max_price_entry.setFixedWidth(80)

        min_price_label = QLabel("最低价:")
        min_price_entry = QLineEdit("30")
        min_price_entry.setFixedWidth(80)

        # 布局添加顺序
        hbox.addWidget(combo_box)  # 下拉菜单放在最左边
        hbox.addStretch(1)
        hbox.addWidget(max_price_label)
        hbox.addWidget(max_price_entry)
        hbox.addWidget(min_price_label)
        hbox.addWidget(min_price_entry)

        # 根据你原来的需求，默认隐藏价格标签和输入框
        # 如果你想选了方案后再显示，可以给 combo_box 加一个信号连接
        max_price_label.hide()
        max_price_entry.hide()
        min_price_label.hide()
        min_price_entry.hide()

        layout.addLayout(hbox)
        # layout.addStretch(1) # 如果需要紧凑排列，可以注释掉这行

        # 返回元组，方便后续获取数据
        return combo_box, max_price_entry, min_price_entry, max_price_label, min_price_label

    def open_schedule_dialog(self):
        """
        打开定时任务设置对话框。
        """
        dialog = ScheduleDialog(self)
        # 将【配置】加载到对话框中
        dialog.set_settings(self.schedule_settings)

        if dialog.exec_() == QDialog.Accepted:
            # 验证通过后，用对话框返回的新【配置】替换旧的
            self.schedule_settings = dialog.get_settings()

            # 当设置更新后，需要重置【状态】标志
            self.reset_schedule_states()

            self._log("[定时任务] 设置已更新。",color='blue')
            self.update_sentinel_status()
        else:
            self._log("[定时任务] 设置未更改。",color='gray')

    def reset_schedule_states(self):
        """每次设置定时计划后，重置所有定时任务的状态标志。"""
        for task_key in self.schedule_states['tasks']:
            self.schedule_states['tasks'][task_key]['start_triggered'] = False
            self.schedule_states['tasks'][task_key]['end_triggered'] = False
        self.schedule_states['shutdown']['triggered_this_session'] = False

    def update_sentinel_status(self):
        """
        根据最新的设置，决定是否启动或停止哨兵定时器。
        """
        # 检查是否有任何任务或关机计划被启用（从配置字典中读取）
        should_run = self.schedule_settings['shutdown']['enabled']
        if not should_run:
            should_run = any(task['start_enabled'] for task in self.schedule_settings['tasks'].values())

        # 根据结果控制哨兵状态
        if should_run and not self.schedule_sentinel.isActive():
            self._log("[定时任务] 已启动，将定时检查。",color='blue')
            self.schedule_sentinel.start()
        elif not should_run and self.schedule_sentinel.isActive():
            self._log("[定时任务] 所有定时计划均已关闭。",color='blue')
            self.schedule_sentinel.stop()

    def check_schedules(self):
        """
        定时检测定时任务是否要启动
        """
        # 使用 QTime 进行比较
        now = QTime.currentTime()

        def is_time_to_trigger(target_time: QTime, enabled: bool, triggered: bool) -> bool:
            """辅助函数，检查是否到达触发时间点。"""
            return (enabled and not triggered and
                    now.hour() == target_time.hour() and
                    now.minute() == target_time.minute())

        # --- 检查所有任务的开始和结束事件 ---
        for task_key, config in self.schedule_settings['tasks'].items():

            # 如果键不存在，就添加它并设置默认值False；如果存在，就返回它的当前值。
            start_triggered = config.setdefault('start_triggered', False)
            end_triggered = config.setdefault('end_triggered', False)

            # 检查【开始】事件
            if is_time_to_trigger(config['start_time'], config['start_enabled'], start_triggered):
                self._log(f"[定时任务] 已到达 '{config['name']}' 的开始时间，准备启动...",color='purple')
                # 直接修改 config 字典，因为 setdefault 已经确保了键的存在
                config['start_triggered'] = True

                if not self.start_btn.isEnabled():
                    self.stop_automation()
                    time.sleep(1)

                self.tabs.setCurrentIndex(config['tab_index'])
                self.auto_plan = True   # 标记是自动开始的
                self.auto_tasks.append(config['tab_index']) # 记录一下是哪个任务
                self.start_automation_signal.emit()
                return

            # 检查【结束】事件
            if is_time_to_trigger(config['end_time'], config['end_enabled'], end_triggered):
                self._log(f"[定时任务] 已到达 '{config['name']}' 的结束时间，自动停止。",color='purple')
                config['end_triggered'] = True

                self.stop_automation()
                return

        # --- 检查定时关机事件 ---
        shutdown_cfg = self.schedule_settings['shutdown']

        # 【核心修改】同样为关机任务动态检查状态标志
        shutdown_triggered = shutdown_cfg.setdefault('triggered_this_session', False)

        if is_time_to_trigger(shutdown_cfg['time'], shutdown_cfg['enabled'], shutdown_triggered):
            self._log(f"[定时关机] 已到达设定时间，执行关机...",color='purple')
            shutdown_cfg['triggered_this_session'] = True

            if not self.start_btn.isEnabled():
                self.stop_automation()
                time.sleep(2)

            self.execute_shutdown_dialog()

    def execute_shutdown_dialog(self):
        """
        封装了弹出和处理关机对话框的逻辑。
        """
        shutdown_dialog = ShutdownDialog(countdown_seconds = 180,parent=self)
        result = shutdown_dialog.exec_()  # exec_() 会阻塞，直到对话框关闭

        if result == QDialog.Rejected:
            self._log("[操作] 用户手动取消了定时关机。")
            # 用户取消了，我们可以选择重新启动哨兵，让他明天再提醒
        else:
            # 用户没有取消，关机流程已启动或结束
            self._log("[操作] 关机流程已启动或结束。")
            # 此时程序可能很快就要关闭了，无需再做操作

    def update_hover_status(self, hwnd: int, title: str) -> None:
        """更新显示当前鼠标悬停的窗口信息。"""
        if hwnd:
            # self.hover_status_label.show()
            self.hover_status_label.setText(f"当前悬停: {title}")
            # self.hover_status_label.setText(f"当前悬停: HWND=0x{hwnd:X}, '{title}'")
        else:
            self.hover_status_label.setText(f"当前悬停: {title}")

    def update_selected_window(self, hwnd: int, title: str, selector_name: str) -> None:
        """
        当一个窗口被选定时调用此槽函数。
        将选择的窗口绑定到对应的 WindowOperator 实例，并正确管理置顶状态。
        """
        # self.hover_status_label.hide()
        target_op = self.op_large if selector_name == "大号" else self.op_small
        info_label = self.info_label_large if selector_name == "大号" else self.info_label_small

        # --- 获取此操作前，大号绑定的旧句柄 ---
        old_large_hwnd = self.op_large.hwnd

        if hwnd:  # 用户提供了一个有效的窗口句柄
            if target_op.bind(hwnd):
                # ==================== 新增：分辨率检查逻辑 ====================
                info = target_op.get_info()
                if info and info['client_size']:
                    curr_w, curr_h = info['client_size']
                    if (curr_w, curr_h) != (1440, 1080):
                        # 弹出警告对话框
                        self._log("[错误] 分辨率不是 1440x1080",color='red')
                        QMessageBox.warning(
                            self,
                            "分辨率错误",
                            f"检测到【{selector_name}】窗口分辨率为: {curr_w}x{curr_h}\n\n"
                            f"该工具仅支持 1440x1080 分辨率。\n"
                            f"请查看教程设置。\n"
                            f"否则脚本无法正常使用！"
                        )
                # =============================================================

                # 绑定成功，更新UI
                info_label.setText(f"已绑定: '{target_op.window_title}'")
                QApplication.beep()

                # --- 置顶逻辑管理 ---
                if selector_name == "大号":
                    # 1. 检查是否存在一个由我们设置的、且不是当前新选窗口的置顶窗口
                    if self.currently_topmost_hwnd and self.currently_topmost_hwnd != hwnd:
                        # 用一个临时的 operator 来取消旧窗口的置顶
                        # 这样做可以避免影响 self.op_large 或 self.op_small 的状态
                        temp_op = WindowOperator()
                        if temp_op.bind(self.currently_topmost_hwnd):
                            temp_op.set_topmost(False)

                    # 2. 设置新窗口为置顶
                    target_op.set_topmost(True)
                    self.currently_topmost_hwnd = hwnd  # 更新记录

            else:  # 绑定失败
                info_label.setText(f"<font color='red'>绑定失败: {target_op.last_error}</font>")

        else:  # 无效选择 (hwnd为0), 意味着要解绑
            # --- 解绑逻辑 ---
            # 如果要解绑的是之前的大号窗口，且它正好是置顶窗口，则取消其置顶
            if selector_name == "大号" and old_large_hwnd and old_large_hwnd == self.currently_topmost_hwnd:
                target_op.set_topmost(False)
                self.currently_topmost_hwnd = 0  # 清除记录
                self._log(f"[置顶管理] 已取消置顶窗口 HWND: {old_large_hwnd}")

            target_op.bind(None)  # 执行解绑
            info_label.setText(f"未绑定 ({title})")

    def restart_game(self,hwnd:int):
        """重启游戏后，重启worker"""
        if self.start_btn.isEnabled() == True and not self.active_worker:
            self.op_large.bind(hwnd)
            self.op_large.show()
            self.op_large.set_topmost(True)
            self.auto_plan = True
            self.start_automation()
        else:
            QTimer.singleShot(3000,lambda :self.restart_game(hwnd))

    def get_task_params(self) -> dict:
        """
        从UI收集所有任务模式的参数，并根据当前激活的标签页设置 task_type。
        预先转换所有坐标，并打包成一个统一的字典。
        """
        # --- 0. 确定当前任务类型 ---
        current_index = self.tabs.currentIndex()
        # 假设索引 0:单端, 1:屯仓, 2:双端
        task_type_map = {
            0: "single_client_settings",
            1: "hoarding_settings",
            2: "double_client_settings",
            3: "skin_settings",
            4: "test_mode",
            5: "settings",
        }
        # 如果在“设置”页按下开始，提示用户并返回
        if current_index == 5:
            self._log("[提示] 请先切换到具体的任务页面，再开始自动化。", color='orange')
            return {}

        self.task_type = task_type_map.get(current_index, "unknown")

        if self.task_type == "unknown":
            self._log(f"[错误] 无效的标签页索引: {current_index}",color='red')
            return {}

        # --- 1. 窗口绑定检查和坐标转换 (所有任务都需要) ---
        if self.need_dual:
            # 双端模式
            if not self.op_large.is_bound or not self.op_small.is_bound:
                self._log("[错误] 请先绑定游戏窗口！",color='red')
                return {}

            if not self.op_large.is_valid_hwnd(self.op_large.hwnd) or \
                    not self.op_small.is_valid_hwnd(self.op_small.hwnd):
                self._log("[错误] 绑定的窗口已失效，请重新绑定！",color='red')
                return {}

            coords_large_abs = self.op_large.client_to_screens(resolution_position.get('large', {}))
            coords_small_abs = self.op_small.client_to_screens(resolution_position.get('small', {}))
            coords_large_hoarding_abs = self.op_large.client_to_screens(resolution_position.get('small', {}))   # 双端屯仓需要
            if coords_large_abs is None or coords_small_abs is None:
                self._log("[错误] 请确保游戏窗口已显示且未最小化。",color='red')
                return {}
        else:
            # 单端模式
            if not self.op_large.is_bound:
                self._log("[错误] 请先绑定游戏窗口！",color='red')
                return {}

            if not self.op_large.is_valid_hwnd(self.op_large.hwnd):
                self._log("[错误] 绑定的窗口已失效，请重新绑定！",color='red')
                return {}

            coords_large_abs = self.op_large.client_to_screens(resolution_position.get('large', {}))
            coords_small_abs = self.op_large.client_to_screens(resolution_position.get('small', {}))
            coords_large_hoarding_abs = coords_small_abs   # 单端屯仓直接复制小号设置

            if coords_large_abs is None or coords_small_abs is None:
                self._log("[错误] 请确保游戏窗口已显示且未最小化。",color='red')
                return {}

        # --- 2. 收集所有任务的参数 ---
        try:
            single_client_settings = {}
            double_client_settings = {}
            hoarding_settings = {}
            skin_settings = {}
            loadout_coord_keys = ["empty_loadout","loadout1", "loadout2", "loadout3", "loadout4", "loadout5"]

            if self.task_type == "single_client_settings":
                # (A) 收集单端配装设置
                single_loadouts = []
                bullet_quantity_single = int(self.bullet_quantity.text())
                for i, (checkbox, max_p, min_p) in enumerate(self.loadout_widgets):
                    if checkbox.isChecked():
                        single_loadouts.append({
                            "id": i + 1,
                            "max_price": int(max_p.text().replace(",", "")) * bullet_quantity_single,
                            "min_price": int(min_p.text().replace(",", "")) * bullet_quantity_single,
                            "click_coord": coords_large_abs[loadout_coord_keys[i]],
                        })
                if len(single_loadouts) < 1:
                    self._log(f"[错误] 请选择一个配装。",color='red')
                    return {}
                if self.auto_block_shit_option.isChecked():
                    if len(single_loadouts)>1:
                        self._log(f"[错误] 自动挡屎模式下只能选一个配装。",color='red')
                        return {}
                    try:
                        price_diff = int(self.price_diff.text())
                        auto_block_max = int(self.auto_block_max.text())
                    except ValueError:
                        self._log(f"[错误] 请输入正确的档位差价与最高挡屎价。",color='red')
                        return {}
                else:
                    price_diff = 0
                    auto_block_max = 99999

                single_client_settings = {
                    "loadouts": single_loadouts,                                # 4个配装的配置
                    "bullet_quantity": bullet_quantity_single,                  # 配装购买的子弹数量
                    "delay_loadout": float(self.delay_loadout.text()) / 1000,   # 配装延迟
                    "delay_small": float(self.delay_small.text()) / 1000,       # 刷新延迟
                    "min_sell_price": int(self.min_sell_price.text()),          # 最低出售价
                    "refresh_interval": int(self.refresh_interval.text()),      # 去大战场的刷新间隔
                    "delay_eat_min": min(self.delay_eat_min.value(), self.delay_eat_max.value()),   # 延迟吃下限
                    "delay_eat_max": max(self.delay_eat_min.value(), self.delay_eat_max.value()),   # 延迟吃上限
                    "auto_sell": self.auto_sell.isChecked(),                    # 是否自动卖子弹
                    "auto_sell_price": self.auto_sell_price.currentIndex(),     # 自动售卖的挡位
                    "receive_mail": self.receive_mail.value(),                  # 领邮件的频率
                    "fast_eat": self.fast_eat.isChecked(),                      # 是否用秒吃模式
                    'auto_block_shit_option':self.auto_block_shit_option.isChecked(),   # 是否自动挡屎
                    'price_range':self.price_range.currentText(),               # 自动挡屎的挡位
                    'price_diff':price_diff,                            # 挡位差价
                    "auto_block_max":auto_block_max,   # 最高挡屎价
                }
            elif self.task_type == "double_client_settings":
                # (B) 收集双端设置
                double_loadouts = []
                bullet_quantity_dual = self.bullet_quantity_double.value()
                loadout_index = self.loadout_combo.currentIndex()

                if loadout_index == 0:
                    self._log(f"[错误] 请选择一个配装", color='red')
                    return {}

                double_loadouts.append({
                    "id": 1,
                    "max_price": 0 * bullet_quantity_dual,  # 挡屎价
                    "min_price": 20 * bullet_quantity_dual, # 最低价
                    "click_coord": coords_large_abs[loadout_coord_keys[loadout_index]],
                })

                if self.auto_block_shit_option_double.isChecked():
                    if len(double_loadouts)>1:
                        self._log(f"[错误] 自动挡屎模式下只能选一个配装",color='red')
                        return {}
                    try:
                        price_diff = self.price_diff_double.value()
                        auto_block_max = self.auto_block_max_double.value()
                    except ValueError:
                        self._log(f"[错误] 请输入正确的档位差价与最高挡屎价",color='red')
                        return {}
                else:
                    price_diff = 0
                    auto_block_max = 99999

                double_client_settings = {
                    "loadouts": double_loadouts,                                    # 选择的配装的配置
                    "loadout_index": loadout_index,                                 # 选哪个配装
                    "bullet_quantity": bullet_quantity_dual,                        # 配装购买的子弹数量
                    "delay_loadout": self.delay_loadout_double.value() / 1000,# 双端的配装延迟
                    "small_buy_circle": self.small_buy_circle.value() / 1000, # 小号的购买周期
                    "delay_see_price": self.delay_see_price.value() / 1000,   # 小号的看价时间
                    "target_price": self.target_price_double.value(),           # 小号的期望价格
                    "min_sell_price": self.min_sell_price_double.value(),       # 双端的最低出售价
                    "refresh_interval": self.refresh_interval_double.value(),   # 双端的去大战场刷新间隔
                    "detect_quantity": int(self.detect_quantity_double.text()),     # 小号每次探测购买数量
                    "auto_sell": self.auto_sell_double.isChecked(),                 # 双端是否自动出售
                    "auto_sell_price": self.auto_sell_price_double.currentIndex(),  # 双端的自动出售挡位
                    "receive_mail": self.receive_mail_double.value(),               # 双端的自动领邮件频率
                    'auto_block_shit_option': self.auto_block_shit_option_double.isChecked(),  # 是否自动挡屎
                    'price_range': self.price_range_double.currentText(),  # 自动挡屎的挡位
                    "auto_block_max": auto_block_max,  # 最高挡屎价
                    'price_diff': price_diff,  # 挡位差价
                }
            elif self.task_type == "hoarding_settings":
                # (C) 收集屯仓设置
                hoard_mode = self.hoard_mode.currentText()  # 用的什么模式

                hoard_min_price = self.hoard_min_price.value()  # 屯仓的买入低价
                hoard_max_price = self.hoard_max_price.value()  # 屯仓的买入高价
                auto_block_enabled, rank, auto_block_max, price_diff = self.auto_block_shit_check_hoarding()
                if auto_block_enabled:  # 开启挡屎
                    if hoard_max_price>auto_block_max:
                        self._log("[错误] 最高价必须 >= 买入单价（最低价）",color='red')
                        return {}

                if hoard_min_price>hoard_max_price:
                    self._log("[错误] 买入单价 不能小于 买入低价", color='red')
                    return {}

                hoarding_settings = {
                    "hoard_target_quantity": self.hoard_target_quantity.value(),# 屯仓的总购买数量
                    "hoard_min_price": self.hoard_min_price.value(),        # 最低价格
                    "hoard_max_price": self.hoard_max_price.value(),        # 最高价格
                    "buy_circle": self.buy_circle.value() / 1000,           # 屯仓买入周期
                    "detect_quantity": int(self.detect_quantity.currentText()),     # 屯仓的买入数量
                    "detect_circle": self.detect_circle.value() / 1000,       # 屯仓检测周期
                    "refresh_rate":self.refresh_rate.value()/1000,          # 无探测模式的刷新速度
                    "bullet_name_input":self.bullet_name_input.text(),              # 自动搜索名称
                    "purchase_location_selector":self.purchase_location_selector.currentIndex(), # 自动搜索情况下的子弹位置
                    "hoard_mode":hoard_mode,                     # 用的什么模式
                    "dynamic_sleep": self.dynamic_sleep_hoarding.isChecked(),   # 是否启用动态探测时间
                    "continuous_buy": self.continuous_buy_hoarding.value(),     # 最大连续购买次数
                    "continuous_detect": self.continuous_detect_hoarding.value(),  # 连续探测低价的次数
                    # 是否启用挡屎，挡位，最高价，价差
                    "auto_block_shit_settings": self.auto_block_shit_check_hoarding(),
                }
                if hoarding_settings["bullet_name_input"] and hoarding_settings["purchase_location_selector"] == 0:
                    self._log(f"[错误] 请选择 购买位置",color='red')
                    return {}
            elif self.task_type == "skin_settings":
                # (D) 收集买皮肤设置
                skin_settings = {
                    "buy_times":self.skin_buy_times.value(),
                }

        except ValueError as e:
            self._log(f"[错误] 参数设置有误，请检查所有标签页的输入是否为纯数字: {e}",color='red')
            return {}
        except Exception as e:
            self._log(f"[错误] 收集参数时发生未知错误: {e}",color='red')
            return {}

        # --- 4. 组装最终的 task_params 字典 ---
        task_params = {
            "task_type": self.task_type,
            "auto_plan": self.auto_plan,
            # 包含所有任务模式的参数
            "single_client_settings": single_client_settings,
            "double_client_settings": double_client_settings,
            "hoarding_settings": hoarding_settings,
            "skin_settings": skin_settings,

            # 通用资源
            "coords": {"large": coords_large_abs, "small": coords_small_abs,"large_hoarding":coords_large_hoarding_abs},
            "op_large": self.op_large,
            "op_small": self.op_small,
            "flag": self.flag,
            "test": self.test.isChecked(),
            "parent":self,
        }

        return task_params

    @staticmethod
    def format_number(line_edit) -> None:
        text = line_edit.text().replace(",", "")
        if text.isdigit():
            formatted_text = "{:,}".format(int(text))
            line_edit.blockSignals(True)
            line_edit.setText(formatted_text)
            line_edit.blockSignals(False)

    def setup_hotkeys(self):
        """
        初始化快捷键监听服务，并同步UI显示
        """
        # 1. 创建监听器实例（逻辑、校验、文件IO全在里面）
        self.listener = GlobalListener(self.config_folder)

        # 2. 连接业务信号
        self.listener.start_signal.connect(self.start_automation)
        self.listener.stop_signal.connect(self.stop_buy_user)

        # 3. 启动监听
        self.listener.start()

        # 4. 初始化“设置”页面中的按钮文字显示
        # 处理录制状态切换
        def handle_pause(is_recording):
            if is_recording:
                self.listener.paused = True
            else:
                # 核心修复：录制结束时，延迟500ms再恢复监听
                # 这样可以避开用户抬起按键的动作
                QTimer.singleShot(500, lambda: setattr(self.listener, 'paused', False))

        self.hk_start.record_status_signal.connect(handle_pause)
        self.hk_stop.record_status_signal.connect(handle_pause)
        # self.hk_start.record_status_signal.connect(lambda b: setattr(self.listener, 'paused', b))
        # self.hk_stop.record_status_signal.connect(lambda b: setattr(self.listener, 'paused', b))
        # 启动时同步 UI，此时不应报“更新成功”
        self.update_hotkey_ui_display()

    def update_hotkey_ui_display(self):
        """同步监听器配置到UI按钮上，并临时阻塞信号防止触发日志"""
        self.hk_start.blockSignals(True)
        self.hk_stop.blockSignals(True)
        self.hk_start.set_cfg(self.listener.start_cfg)
        self.hk_stop.set_cfg(self.listener.stop_cfg)
        self.hk_start.blockSignals(False)
        self.hk_stop.blockSignals(False)

    def on_hotkey_changed(self):
        """当用户手动在设置页按键后触发"""
        # 调用监听器的校验更新逻辑
        success, msg = self.listener.update_keys(
            self.hk_start.current_cfg,
            self.hk_stop.current_cfg
        )

        if success:
            self._log(f"[设置] {msg}", color='blue')
            # 使用现有变量 hk_warning 展示成功信息
            self.hk_warning.setText("配置已保存")
            self.hk_warning.setStyleSheet("color: green;")
        else:
            self._log(f"[错误] {msg}", color='red')
            self.hk_warning.setText(msg)
            self.hk_warning.setStyleSheet("color: red;")
            # 【重要】如果冲突了，把UI按钮显示的值还原回监听器当前生效的值
            self.update_hotkey_ui_display()

    def save_log(self):
        """
        将 QTextEdit 中的当前内容保存到 "运行日志" 文件夹下的一个新文件中。
        """
        try:
            # os.path.exists() 检查路径是否存在
            if not os.path.exists(self.log_folder):
                # os.makedirs() 创建文件夹
                os.makedirs(self.log_folder)
        except Exception as e:
            # 如果因为权限等问题创建失败，在控制台打印错误
            self._log(f"[错误] 创建日志文件夹 '{self.log_folder}' 时发生错误: {e}",color='red')

        try:
            text_to_save = self.log_area.toPlainText()

            if not text_to_save.strip():return

            # 1. 生成不带路径的文件名
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            base_file_name = f"{timestamp}.txt"

            # 2. 使用 os.path.join() 来构建完整的文件路径
            full_file_path = os.path.join(self.log_folder, base_file_name)

            # 3. 将内容写入指定路径的文件
            with open(full_file_path, "w", encoding="utf-8") as f:
                f.write(text_to_save)

            # 4. 给用户的反馈信息中包含文件夹和文件名
            self._log(f"[日志] 当前日志已保存到文件夹《{self.log_folder}》",color='blue')

        except Exception as e:
            self._log(f"[错误] 保存日志时发生错误: {e}",color='red')

    def log_message(self, message: str) -> None:
        self.log_area.append(message)

    @staticmethod
    def _get_widget_value(widget):
        """自动判断控件类型并取值"""
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        elif isinstance(widget, QLineEdit):
            return widget.text()
        elif isinstance(widget, (QCheckBox, QRadioButton, QGroupBox)):
            return widget.isChecked()
        elif isinstance(widget, QComboBox):
            # 约定：如果需要存索引则手动处理，默认存文本
            return widget.currentText()
        return None

    @staticmethod
    def _set_widget_value(widget, value, default):
        """
        自动判断类型并赋值，支持默认值回退
        """
        # 如果 value 为 None，则使用提供的 default
        val = value if value is not None else default

        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(val))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(val))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(val))
        elif isinstance(widget, (QCheckBox, QRadioButton, QGroupBox)):
            widget.setChecked(bool(val))
        elif isinstance(widget, QComboBox):
            # 智能处理 ComboBox: 如果默认值是数字，按索引设；如果是字符串，按文本设
            if isinstance(val, int):
                widget.setCurrentIndex(val)
            else:
                index = widget.findText(str(val))
                if index >= 0:
                    widget.setCurrentIndex(index)

    def _setup_config_registry(self):
        """
        记录要保存/读取的配置
        """
        #     (self.delay_loadout,    'setText',      'delay_loadout', '0.1'),
        #     (self.bullet_quantity,  'setText',      'bullet_quantity', '1'),
        #     (self.min_sell_price,   'setText',      'min_sell_price', '0'),
        #     (self.delay_small,      'setText',      'delay_small', '300'),
        #     (self.refresh_interval, 'setText',      'refresh_interval', '10'),
        #     (self.delay_eat_min,    'setValue',     'delay_eat_min', 1.0),
        #     (self.delay_eat_max,    'setValue',     'delay_eat_max', 5.0),
        #     (self.auto_block_shit_option, 'setChecked', 'auto_block_shit_option', False),
        #     (self.price_range,      'setCurrentText', 'price_range', '第 3 档'),
        #     (self.price_diff,       'setText',      'price_diff', ''),
        #     (self.auto_block_max,   'setText',      'auto_block_max', ''),

        self.config_registry = {
            # 单端滚仓设置
            # "main_settings": {
            #     'loadouts': loadouts_data,                          # 4个配装
            #     'delay_loadout': (self.delay_loadout, 0.1),                 #
            #     'bullet_quantity': self.bullet_quantity.text(),
            #     'delay_small': self.delay_small.text(),
            #     'min_sell_price': self.min_sell_price.text(),
            #     'refresh_interval': self.refresh_interval.text(),
            #     'delay_eat_min': self.delay_eat_min.value(),
            #     'delay_eat_max': self.delay_eat_max.value(),
            #     'auto_block_shit_option':self.auto_block_shit_option.isChecked(),
            #     'price_range':self.price_range.currentText(),
            #     'price_diff':self.price_diff.text(),
            #     'auto_block_max':self.auto_block_max.text(),
            # },
            # ------------------- 收集双端滚仓设置 ----------------------
            "double_client_settings": {
                # "键名": (控件对象, 默认值)
                "loadouts_new":     (self.loadout_combo, 1),            # 选择配装
                "delay_loadout":    (self.delay_loadout_double, 300),   # 识别延迟
                "small_buy_circle": (self.small_buy_circle, 450),       # 小号周期
                'delay_see_price':  (self.delay_see_price, 100),        # 看价时间
                "target_price":     (self.target_price_double, 0),      # 期望单价
                "min_sell_price":   (self.min_sell_price_double, 0),    # 最低售价
                "bullet_quantity":  (self.bullet_quantity_double, 1),   # 配装一次购买的子弹数量
                "refresh_interval": (self.refresh_interval_double, 15), # 去大战场的时间
                'detect_quantity':  (self.detect_quantity_double, 31),  # 探测数量
                "auto_block_shit_option": (self.auto_block_shit_option_double, False),  # 自动挡屎开关
                # ----- 下面是自动挡屎内容，暂时不用 -----
                "price_range":      (self.price_range_double, "第 3 档"),# 自动挡屎
                "price_diff":       (self.price_diff_double, 1),        # 差价
                "auto_block_max":   (self.auto_block_max_double, 1),    # 自动挡屎最高价
            },
            # ------------------- 收集屯仓设置 ----------------------
            "hoarding_settings": {
                "target_quantity":  (self.hoard_target_quantity, 10000),# 屯仓购买的子弹数量
                "max_price":        (self.hoard_max_price, 0),          # 买入单价
                "buy_circle":       (self.buy_circle, 430),             # 购买周期
                "detect_quantity":  (self.detect_quantity, "32"),       # 探测数量
                'detect_circle':    (self.detect_circle, 5000),         # 探测周期
                "bullet_name":      (self.bullet_name_input, ""),       # 子弹名称
                "purchase_location": (self.purchase_location_selector, ""), # 购买位置
                # ----- 进阶设置 -----
                "dynamic_sleep": (self.dynamic_sleep_hoarding, False),  # 动态休眠
                "continuous_buy": (self.continuous_buy_hoarding, 10),  # 连买次数
                "continuous_detect": (self.continuous_detect_hoarding, 10),  # 连探次数
                # ----- 下面是自动挡屎内容 -----
                "auto_block_shit_option": (self.auto_block_shit_option_hoarding, False),    # 自动调整买入价
                'price_range':      (self.price_range_hoarding, '第 3 档'),
                'price_diff':       (self.price_diff_hoarding, 1),
                'auto_block_max':   (self.auto_block_max_hoarding, 1),
            }
        }

    def save_config(self):
        """将所有UI配置保存到JSON文件中"""
        os.makedirs(self.config_folder, exist_ok=True)  # 先创建文件夹
        filePath, _ = QFileDialog.getSaveFileName(
            self, "保存配置", self.config_path, "JSON (*.json)")
        if not filePath:return

        # 1. 自动从注册表收集数据
        config = {}
        for section, widgets_info in self.config_registry.items():
            # section 是每个功能的名称
            # widgets_info 是具体内容
            info = {}
            for name, (widget, default_value) in widgets_info.items():
                info[name] = self._get_widget_value(widget)

            config[section] = info.copy()

        # 2. 写入文件
        try:
            with open(filePath, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            self._log(f"[配置] 成功保存至: {filePath}")
        except Exception as e:
            self._log(f"[错误] 保存失败: {e}", color='red')

    def load_config(self):
        """全自动加载配置（含默认值回退逻辑）"""
        filePath, _ = QFileDialog.getOpenFileName(
            self, "加载配置", self.config_folder, "JSON (*.json)")
        if not filePath:
            return

        try:
            with open(filePath, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 1. 自动从注册表分发数据
            for section, widgets_info in self.config_registry.items():
                section_data = config.get(section, {})  # 获取该区块，若无则为空字典

                for key, (widget, default_value) in widgets_info.items():
                    val = section_data.get(key)  # 获取具体值
                    self._set_widget_value(widget, val, default_value)

            self._log(f"[配置] 成功从 {filePath} 加载配置。")
        except Exception as e:
            self._log(f"[错误] 加载配置失败: {type(e).__name__} {str(e)}",color='red')

    # def save_config(self):
    #     """将所有UI配置保存到JSON文件中，采用结构化字典。"""
    #     # 1. 收集主设置（原单端配置）
    #     main_settings = {}
    #     # loadouts_data = []
    #     # for checkbox, max_price_entry, min_price_entry in self.loadout_widgets:
    #     #     data = {
    #     #         'enabled': checkbox.isChecked(),
    #     #         'max_price': max_price_entry.text(),
    #     #         'min_price': min_price_entry.text()
    #     #     }
    #     #     loadouts_data.append(data)
    #     #
    #     # main_settings = {
    #     #     'loadouts': loadouts_data,                          # 4个配装
    #     #     'delay_loadout': self.delay_loadout.text(),                 #
    #     #     'bullet_quantity': self.bullet_quantity.text(),
    #     #     'delay_small': self.delay_small.text(),
    #     #     'min_sell_price': self.min_sell_price.text(),
    #     #     'refresh_interval': self.refresh_interval.text(),
    #     #     'delay_eat_min': self.delay_eat_min.value(),
    #     #     'delay_eat_max': self.delay_eat_max.value(),
    #     #     'auto_block_shit_option':self.auto_block_shit_option.isChecked(),
    #     #     'price_range':self.price_range.currentText(),
    #     #     'price_diff':self.price_diff.text(),
    #     #     'auto_block_max':self.auto_block_max.text(),
    #     # }
    #
    #     # 2. 收集双端设置
    #     # loadouts_data_double = []
    #     # for checkbox, max_price_entry, min_price_entry in self.loadout_widgets_double:
    #     #     data = {
    #     #         'enabled': checkbox.isChecked(),
    #     #         'max_price': max_price_entry.text(),
    #     #         'min_price': min_price_entry.text()
    #     #     }
    #     #     loadouts_data_double.append(data)
    #
    #     double_client_settings = {
    #         # 'loadouts': loadouts_data_double,
    #         'loadouts_new':self.loadout_combo.currentIndex(),
    #         'delay_loadout': self.delay_loadout_double.value(),
    #         'small_buy_circle': self.small_buy_circle.value(),
    #         'delay_see_price': self.delay_see_price.value(),
    #         'target_price': self.target_price_double.value(),
    #         'min_sell_price': self.min_sell_price_double.value(),
    #         'bullet_quantity': self.bullet_quantity_double.value(),
    #         'refresh_interval': self.refresh_interval_double.value(),
    #         'detect_quantity': self.detect_quantity_double.text(),
    #         'auto_block_shit_option': self.auto_block_shit_option_double.isChecked(),
    #         'price_range': self.price_range_double.currentText(),
    #         'auto_block_max': self.auto_block_max_double.value(),
    #         'price_diff': self.price_diff_double.value(),
    #     }
    #
    #     # ------------------- 收集屯仓设置 ----------------------
    #     hoarding_settings = {
    #         'target_quantity': self.hoard_target_quantity.value(),
    #         'max_price': self.hoard_max_price.value(),
    #         'buy_circle': self.buy_circle.value(),
    #         'detect_quantity': self.detect_quantity.currentText(),
    #         'detect_circle': self.detect_circle.value(),
    #         'bullet_name': self.bullet_name_input.text(),
    #         'purchase_location': self.purchase_location_selector.currentText(),
    #         'auto_block_shit_option': self.auto_block_shit_option_hoarding.isChecked(),
    #         'price_range': self.price_range_hoarding.currentText(),
    #         'auto_block_max': self.auto_block_max_hoarding.value(),
    #         'price_diff': self.price_diff_hoarding.value(),
    #     }
    #
    #     # 3. 组合成最终的配置字典
    #     config = {
    #         'main_settings': main_settings,
    #         'double_client_settings': double_client_settings,
    #         "hoarding_settings":hoarding_settings,
    #     }
    #
    #     # 4. 文件保存逻辑 (保持不变)
    #     default_dir = os.path.join(os.path.dirname(sys.argv[0]), self.config_folder)
    #     os.makedirs(default_dir, exist_ok=True)
    #     default_filename = os.path.join(default_dir, "delta_loadouts_config.json")
    #     options = QFileDialog.Options()
    #     filePath, _ = QFileDialog.getSaveFileName(
    #         self, "保存配置", default_filename, "JSON 文件 (*.json);;所有文件 (*.*)", options=options
    #     )
    #     if filePath:
    #         if not filePath.lower().endswith('.json'):
    #             filePath += '.json'
    #         try:
    #             with open(filePath, 'w', encoding='utf-8') as f:
    #                 json.dump(config, f, indent=4, ensure_ascii=False)
    #             self._log(f"[配置] 所有设置已保存至: {filePath}")
    #         except Exception as e:
    #             self._log(f"[错误] 保存配置到 {filePath} 失败: {str(e)}",color='red')
    #
    # def load_params_from_dict(self,source: dict, config_map: list):
    #     """
    #     根据一个配置映射，从源字典中读取数据并更新UI控件。
    #
    #     Args:
    #         source (dict): 包含设置数据的源字典。
    #         config_map (list): 一个配置元组的列表，格式为:
    #                            (widget, setter_method_name, key, default_value)
    #     """
    #     for widget, setter_name, key, default in config_map:
    #         try:
    #             # 从 source 字典中获取值，如果key不存在，则使用默认值
    #             value_to_set = source.get(key, default)
    #
    #             # 动态地获取控件的 setter 方法
    #             setter_method = getattr(widget, setter_name)
    #
    #             # 调用方法，并传入我们要设置的值
    #             setter_method(value_to_set)
    #         except Exception as e:
    #             # 增加一个错误处理，以防控件不存在或方法名错误
    #             self._log(f"更新UI时出错 (key: '{key}'): {e}")
    #
    # def load_config(self):
    #     """从JSON文件加载配置，兼容新旧两种格式。"""
    #     default_dir = os.path.join(os.path.dirname(sys.argv[0]), self.config_folder)
    #     os.makedirs(default_dir, exist_ok=True)
    #     options = QFileDialog.Options()
    #     filePath, _ = QFileDialog.getOpenFileName(
    #         self, "加载配置", default_dir, "JSON 文件 (*.json);;所有文件 (*.*)", options=options
    #     )
    #     if not filePath:
    #         return
    #
    #     try:
    #         with open(filePath, 'r', encoding='utf-8') as f:
    #             config = json.load(f)
    #
    #         # # 1. 加载主设置（原单端配置），兼容新旧格式
    #         # main_settings = config.get('main_settings')
    #         # if main_settings:  # 新格式
    #         #     source = main_settings
    #         # else:  # 兼容旧格式
    #         #     source = config
    #         #
    #         # # 从确定的源（source）加载数据
    #         # loadouts_data = source.get('loadouts')
    #         # if loadouts_data and isinstance(loadouts_data, list):
    #         #     for i in range(min(len(self.loadout_widgets), len(loadouts_data))):
    #         #         widgets = self.loadout_widgets[i]
    #         #         data = loadouts_data[i]
    #         #         checkbox, max_price_entry, min_price_entry = widgets
    #         #         checkbox.setChecked(data.get('enabled', True))
    #         #         max_price_entry.setText(data.get('max_price', '0'))
    #         #         min_price_entry.setText(data.get('min_price', '0'))
    #         #
    #         # single_config_map = [
    #         #     # (UI控件,               'setter方法名',  '字典中的key',             默认值)
    #         #     (self.delay_loadout,    'setText',      'delay_loadout', '0.1'),
    #         #     (self.bullet_quantity,  'setText',      'bullet_quantity', '1'),
    #         #     (self.min_sell_price,   'setText',      'min_sell_price', '0'),
    #         #     (self.delay_small,      'setText',      'delay_small', '300'),
    #         #     (self.refresh_interval, 'setText',      'refresh_interval', '10'),
    #         #     (self.delay_eat_min,    'setValue',     'delay_eat_min', 1.0),
    #         #     (self.delay_eat_max,    'setValue',     'delay_eat_max', 5.0),
    #         #     (self.auto_block_shit_option, 'setChecked', 'auto_block_shit_option', False),
    #         #     (self.price_range,      'setCurrentText', 'price_range', '第 3 档'),
    #         #     (self.price_diff,       'setText',      'price_diff', ''),
    #         #     (self.auto_block_max,   'setText',      'auto_block_max', ''),
    #         # ]
    #         # self.load_params_from_dict(source,single_config_map)
    #
    #         # 2. 加载双端配置 (如果存在)
    #         double_client_settings = config.get('double_client_settings')
    #         if double_client_settings and isinstance(double_client_settings, dict):
    #         #     loadouts_data_double = double_client_settings.get('loadouts')
    #         #     if loadouts_data_double and isinstance(loadouts_data_double, list):
    #         #         for i in range(min(len(self.loadout_widgets_double), len(loadouts_data_double))):
    #         #             widgets = self.loadout_widgets_double[i]
    #         #             data = loadouts_data_double[i]
    #         #             checkbox, max_price_entry, min_price_entry = widgets
    #         #             checkbox.setChecked(data.get('enabled', True))
    #         #             max_price_entry.setText(data.get('max_price', '0'))
    #         #             min_price_entry.setText(data.get('min_price', '0'))
    #
    #             double_client_ui_map = [
    #                 # (UI控件,                       'setter方法名',  '字典中的key',     默认值)
    #                 (self.loadout_combo,            'setCurrentIndex','loadouts_new',   0),
    #                 (self.delay_loadout_double,     'setValue',     'delay_loadout', 100),
    #                 (self.small_buy_circle,         'setValue',     'small_buy_circle', 450),
    #                 (self.delay_see_price,          'setValue',     'delay_see_price', 100),
    #                 (self.target_price_double,      'setValue',     'target_price', 0),
    #                 (self.min_sell_price_double,    'setValue',     'min_sell_price', 0),
    #                 (self.bullet_quantity_double,   'setValue',     'bullet_quantity', 1),
    #                 (self.refresh_interval_double,  'setValue',     'refresh_interval', 15),
    #                 (self.detect_quantity_double,   'setText',      'detect_quantity', '31'),
    #                 (self.auto_block_shit_option_double, 'setChecked', 'auto_block_shit_option', False),
    #                 (self.price_range_double,       'setCurrentText', 'price_range', '第 3 档'),
    #                 (self.price_diff_double,        'setValue',     'price_diff', 1),
    #                 (self.auto_block_max_double,    'setValue',     'auto_block_max', 1),
    #             ]
    #
    #             self.load_params_from_dict(double_client_settings, double_client_ui_map)
    #
    #         # ------------------- 新增：加载屯仓配置 (如果存在) -------------------
    #         hoarding_settings = config.get('hoarding_settings')
    #         if hoarding_settings and isinstance(hoarding_settings, dict):
    #             hoarding_ui_map = [
    #                 # (UI控件,                      'setter方法名',   '字典中的key',       默认值)
    #                 (self.hoard_target_quantity,    'setValue',     'target_quantity', 10000),
    #                 (self.hoard_max_price,          'setValue',     'max_price', 0),
    #                 (self.buy_circle,               'setValue',     'buy_circle', 430),
    #                 (self.detect_quantity,          'setCurrentText', 'detect_quantity', '32'),
    #                 (self.detect_circle,            'setValue',      'detect_circle', 5000),
    #                 (self.bullet_name_input,        'setText',      'bullet_name', ''),
    #                 (self.purchase_location_selector, 'setCurrentText', 'purchase_location', ''),
    #                 (self.auto_block_shit_option_hoarding, 'setChecked', 'auto_block_shit_option', False),
    #                 (self.price_range_hoarding,     'setCurrentText', 'price_range', '第 3 档'),
    #                 (self.price_diff_hoarding,      'setValue', 'price_diff', 1),
    #                 (self.auto_block_max_hoarding,  'setValue', 'auto_block_max', 1),
    #             ]
    #
    #             self.load_params_from_dict(hoarding_settings, hoarding_ui_map)
    #
    #         self._log(f"[配置] 成功从 {filePath} 加载所有配置。")
    #
    #     except Exception as e:
    #         self._log(f"[错误] 加载配置失败: {type(e).__name__} {str(e)}",color='red')

    def start_automation(self):
        """开始自动化任务。"""
        if not self.start_btn.isEnabled():
            self._log("[警告] 任务已在运行中，请勿重复启动。",color='orange')
            return

        self.flag.stop = False
        self.user_stopped = False
        self._set_widgets_enabled(running=True)

        try:
            task_data = self.get_task_params()
            if not task_data:
                self._set_widgets_enabled(running=False)
                return

            task_data["flag"] = self.flag
            task_data["item_name"] = "单个任务"  # 任务名硬编码

            self.active_worker = Worker(task_data)
            self.active_worker.log_signal.connect(self.log_message)
            self.active_worker.save_log_signal.connect(self.save_log)
            self.active_worker.finished_signal.connect(self.on_single_task_finished)
            self.active_worker.restart_game_signal.connect(self.restart_game)
            self.active_worker.start()
        except (ValueError, Exception) as e:
            self._log(f"[错误] {type(e).__name__}: {str(e)}",color='red')
            self._set_widgets_enabled(running=False)
            return

    def _set_widgets_enabled(self, running: bool):
        """
        根据运行状态，启用或禁用所有控件。
        """
        self.start_btn.setEnabled(not running)
        self.load_config_btn.setEnabled(not running)
        self.save_config_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def on_single_task_finished(self):
        """处理单个任务 Worker 完成的信号。"""
        if self.force_kill_timer.isActive():
            self.force_kill_timer.stop()

        if self.user_stopped:
            self._log("[任务] 被用户成功停止。")
        else:
            self._log("[任务] 任务执行完成。")

        # 清理worker引用并更新UI
        self.active_worker = None
        self._set_widgets_enabled(running=False)    # 恢复按钮

    def force_kill_worker(self):
        """
        由 force_kill_timer 超时后调用，用于强制终止worker线程。
        """
        # 再次检查，确保worker真的还活着
        if self.active_worker and self.active_worker.isRunning():

            self._log("[错误] 正在执行强制终止...",color='red')

            # 【核心】调用 terminate()，这是一个“不友好”的终止方法
            self.active_worker.terminate()
            # 等待一小会儿，让操作系统完成终止
            self.active_worker.wait(1000)

            # 强制终止后，也需要清理状态
            self.active_worker = None
            self._set_widgets_enabled(running=False)  # 重置UI
        else:
            # 这通常不会发生，说明在定时器触发前，worker已经自己结束了
            self._log("[信息] 强制终止被触发，但任务已结束。")

    def toggle_window_topmost(self, checked: bool):
        """
        槽函数：根据复选框的状态，设置或取消主窗口的“总在最前”属性。

        Args:
            checked (bool): 复选框是否被选中。
        """
        try:
            # 1. 获取当前窗口的句柄 (HWND)
            # self.winId() 是 PyQt 提供的、获取当前QWidget窗口句柄的方法
            hwnd = self.winId()

            # 2. 获取当前窗口的样式标志
            # GWL_EXSTYLE 获取的是扩展窗口样式
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

            if checked:
                # --- 设置为置顶 ---
                self._log("[界面] 窗口已置顶。")
                new_style = style | win32con.WS_EX_TOPMOST
                z_order = win32con.HWND_TOPMOST
            else:
                # --- 取消置顶 ---
                self._log("[界面] 窗口已取消置顶。")
                new_style = style & ~win32con.WS_EX_TOPMOST
                z_order = win32con.HWND_NOTOPMOST

            # 3. 应用新的样式
            # 先设置扩展样式，再调用 SetWindowPos 来刷新窗口层级
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)

            # 4. 使用 SetWindowPos 强制刷新窗口的 Z-order
            # SWP_NOMOVE | SWP_NOSIZE 确保在改变层级时不移动或改变窗口大小
            win32gui.SetWindowPos(hwnd, z_order, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_FRAMECHANGED)

        except Exception as e:
            self._log(f"[错误] 设置窗口置顶失败: {e}",color='red')
            # 如果失败了，把复选框的状态恢复回去
            self.topmost_checkbox.blockSignals(True)  # 临时阻止信号，防止无限循环
            self.topmost_checkbox.setChecked(not checked)
            self.topmost_checkbox.blockSignals(False)

    def stop_automation(self):
        """停止自动化任务，可以被程序触发，或者按下鼠标中键触发（此时肯定是用户触发得）。"""
        self._set_widgets_enabled(running=False)
        if not self.flag.stop:
            self.flag.stop = True
            self._log("[操作] 已触发停止命令，等待当前操作完成...",color='red')
            self.force_kill_timer.start(3000)  # 5000毫秒 = 5秒

        if self.user_stopped and self.schedule_settings['close_small_checkbox'] and \
            self.schedule_settings['tasks']['dual']['start_enabled']:
            self._log("[操作] 被用户手动停止，请重新设置关闭小号",color='blue')

        # 只有 1.开启关闭小号 2.不是被用户手动停止的 3.任务是双端 才可以关闭小号
        if (self.schedule_settings['close_small_checkbox'] and (not self.user_stopped)
                and self.task_type == "double_client_settings"):
            # 说明是被定时程序停止的
            self.op_small.close()
            self._log("[操作] 已关闭小号",color='blue')

        self.auto_plan = False

    def stop_buy_user(self):
        """当鼠标中键按下时调用，确保是被用户按下的"""
        self.user_stopped = True
        self.stop_automation()

    def closeEvent(self, event):
        """
        处理主窗口关闭事件，执行所有必要的清理工作，并安全地关闭后台服务。
        """
        # 取消窗口置顶
        if hasattr(self, 'currently_topmost_hwnd') and self.currently_topmost_hwnd and win32gui.IsWindow(
                self.currently_topmost_hwnd):
            try:
                cleanup_op = WindowOperator()
                if cleanup_op.bind(self.currently_topmost_hwnd):
                    cleanup_op.set_topmost(False)
            except Exception as e:
                self._log(f"[错误] 清理置顶时发生异常: {e}",color='red')

        # 清理高亮覆盖窗口
        if hasattr(self, 'selector_btn_large') and self.selector_btn_large._overlay_window.isWindow():
            self.selector_btn_large._overlay_window.hide()
            self.selector_btn_large._overlay_window.deleteLater()
        if hasattr(self, 'selector_btn_small') and self.selector_btn_small._overlay_window.isWindow():
            self.selector_btn_small._overlay_window.hide()
            self.selector_btn_small._overlay_window.deleteLater()

        event.accept()