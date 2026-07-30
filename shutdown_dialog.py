# -*- coding: utf-8 -*-

# shutdown_dialog.py

"""自动关机倒计时对话框。

该模块提供一个置顶的 PyQt5 对话框，用于在执行自动关机前展示倒计时，
并允许用户在倒计时结束前取消关机。
"""

# ----- 标准库 -----
import os
import platform
import sys

# ----- 第三方库 -----
from PyQt5.QtCore import Qt, QTime, QTimer
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

__version__ = "1.0.1"
__update__ = "2026.07.28"

class ShutdownDialog(QDialog):
    """
    显示自动关机倒计时，并提供取消关机按钮的模态对话框。

    Attributes:
        countdown_seconds: 初始倒计时秒数，用于记录对话框创建时的完整等待时间。
        remaining_seconds: 当前剩余秒数，每次定时器触发时递减。
        timer: 每秒触发一次的倒计时定时器，触发后调用 update_countdown()。
        label: 倒计时提示文本，由 init_ui() 创建。
        cancel_button: 取消自动关机按钮，由 init_ui() 创建。
    """

    def __init__(self, countdown_seconds:int=300, parent=None):
        """初始化自动关机倒计时对话框。

        Args:
            countdown_seconds (int): 倒计时时长，单位为秒。默认 300 秒，即 5 分钟。
            parent (QWidget | None): 父级窗口对象，默认没有父窗口。
        """
        super().__init__(parent)

        self.countdown_seconds:int = countdown_seconds
        self.remaining_seconds:int = countdown_seconds

        # 使用 Qt 定时器驱动倒计时，避免阻塞 UI 事件循环。
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)

        self.init_ui()

        # 保持窗口置顶，确保用户能看到自动关机提示。
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Dialog)

        # 立即启动倒计时，之后每 1000 ms 更新一次。
        self.timer.start(1000)

    def init_ui(self):
        """创建对话框控件并初始化布局。"""
        self.setWindowTitle("自动关机提示")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)

        font = self.label.font()
        font.setPointSize(14)
        self.label.setFont(font)

        self.cancel_button = QPushButton("取消关机")
        self.cancel_button.clicked.connect(self.cancel_shutdown)

        layout.addWidget(self.label)
        layout.addWidget(self.cancel_button)
        self.setLayout(layout)

        # 初始化倒计时文案。
        self.update_label()

    def update_label(self):
        """根据当前剩余秒数刷新倒计时标签。"""
        time_str = QTime(0, 0, 0).addSecs(self.remaining_seconds).toString("mm:ss")
        self.label.setText(f"系统将在 <font color='red'>{time_str}</font> 后自动关机\n点击下方按钮取消")

    def update_countdown(self):
        """处理每秒一次的倒计时更新，并在倒计时结束时执行关机。"""
        self.remaining_seconds -= 1
        self.update_label()

        if self.remaining_seconds <= 0:
            self.timer.stop()
            self.perform_shutdown()

    def perform_shutdown(self):
        """执行系统关机命令。

        当前只支持 Windows。非 Windows 系统会弹出警告并关闭对话框。
        """
        self.label.setText("正在执行关机...")
        self.cancel_button.setEnabled(False)

        # 立即刷新界面，避免关机命令执行前用户看不到状态变化。
        self.repaint()
        QApplication.processEvents()

        system = platform.system()
        try:
            if system == "Windows":
                # /s: 关机。
                # /t 0: 立即执行；等待过程已经由本对话框完成。
                # /f: 强制关闭正在运行的应用。
                # /c: 写入关机原因。
                os.system('shutdown /s /t 0 /f /c "自动化任务完成，系统将关机"')
            else:
                QMessageBox.warning(self, "关机失败", f"不支持在 {system} 操作系统上自动关机。")
                self.accept()
                return
        except Exception as e:
            QMessageBox.critical(self, "关机失败", f"执行关机命令时出错：\n{e}")
            self.accept()
            return

        # os.system 不会可靠返回关机是否已经完成；命令发出后关闭对话框。
        self.accept()

    def cancel_shutdown(self):
        """取消自动关机倒计时，并以 reject 状态关闭对话框。"""
        self.timer.stop()
        QMessageBox.information(self, "操作取消", "自动关机已取消。")
        self.reject()

    def closeEvent(self, event):
        """处理用户点击窗口关闭按钮的情况。

        关闭窗口等同于点击“取消关机”，因此这里忽略默认关闭事件，
        由 cancel_shutdown() 负责停止定时器并关闭对话框。
        """
        self.cancel_shutdown()
        event.ignore()


# ----- 独立测试入口 -----
if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = ShutdownDialog(countdown_seconds=60)
    dialog.exec_()
    sys.exit()
