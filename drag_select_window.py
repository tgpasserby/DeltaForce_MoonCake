# drag_select_window.py

# ----- 导入官方库 -----
import sys
from typing import Optional

# ----- 导入三方库 -----
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLabel
from PyQt5.QtGui import  QPainter, QPen, QColor
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QTimer
import win32gui
import win32api
import win32con

class OverlayHighlightWindow(QWidget):
    """
    一个全透明的顶层窗口，用于在屏幕上绘制高亮边框，以指示被选中的窗口。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |    # 移除窗口的所有边框和标题栏
            Qt.WindowStaysOnTopHint |   # 让这个窗口永远“置顶”
            Qt.Tool |                   # 将窗口标记为一个“工具窗口”
            Qt.WindowTransparentForInput  # 不会被鼠标选中
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 启用窗口背景的 "全透明" 能力。
        self.setStyleSheet("background-color: transparent;")
        self.highlight_rect_on_screen: QRect = QRect()
        self.border_color: QColor = QColor(255, 0, 0, 200)
        self.border_thickness: int = 3

    def set_highlight_geometry(self, screen_rect: Optional[QRect]) -> None:
        """
        根据提供的屏幕矩形区域，设置并显示高亮边框。

        这个函数是该覆盖窗口的核心控制器。它接收一个 QRect 对象，
        该对象定义了我们想要在其周围绘制边框的目标窗口在屏幕上的位置和大小。
        如果传入 None 或者一个空的 QRect，则隐藏高亮边框。

        Args:
            screen_rect (Optional[QRect]): 目标窗口在屏幕上的几何矩形 (x, y, width, height)。
                                           如果为 None，则表示不显示任何高亮。
        """
        # --- 步骤 1: 检查输入是否有效 ---
        if screen_rect and not screen_rect.isNull():
            # --- 步骤 2: 更新并调整几何信息 ---
            self.highlight_rect_on_screen = screen_rect
            # 为了确保边框线本身完全可见，我们需要将覆盖窗口的实际大小向外扩展。
            adjusted_geom = screen_rect.adjusted(
                -self.border_thickness,
                -self.border_thickness,
                self.border_thickness,
                self.border_thickness)
            self.setGeometry(adjusted_geom)

            # --- 步骤 3: 显示与更新窗口 ---
            if not self.isVisible():
                self.show()
            self.update()
        else:
            # --- 步骤 4: 处理无效输入，隐藏窗口 ---
            # 如果传入的 screen_rect 是 None 或空的，意味着我们应该隐藏高亮框。
            self.highlight_rect_on_screen = QRect()
            if self.isVisible():
                self.hide()

    def paintEvent(self, event) -> None:
        """
        Qt 的绘图事件处理函数。

        当窗口需要被重绘时（例如，首次显示、大小改变、或者被其他窗口遮挡后又重新出现，
        以及我们手动调用 update() 时），这个方法会被 Qt 自动调用。

        Args:
            event (QPaintEvent): 包含了关于重绘请求信息的事件对象，我们通常不需要直接使用它。
        """
        # --- 步骤 1: 前置检查 ---
        # 在开始绘图前，进行安全检查，确保有东西可画。
        if not self.highlight_rect_on_screen.isNull() and self.isVisible():
            # --- 步骤 2: 初始化绘图工具 ---
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)     # 开启“抗锯齿”渲染提示

            # --- 步骤 3: 设置画笔 (QPen) 属性 ---
            pen = QPen(self.border_color)
            pen.setWidth(self.border_thickness)
            pen.setStyle(Qt.SolidLine)
            painter.setPen(pen)

            # --- 步骤 4: 计算精确地绘制矩形区域 ---
            rect_to_draw_inside_overlay = self.rect().adjusted(
                self.border_thickness // 2,
                self.border_thickness // 2,
                -(self.border_thickness // 2) - (self.border_thickness % 2 > 0),
                -(self.border_thickness // 2) - (self.border_thickness % 2 > 0)
            )
            # --- 步骤 5: 执行绘图操作 ---
            painter.drawRect(rect_to_draw_inside_overlay)

class DraggableSelectorWithOverlay(QPushButton):
    """
    一个可拖动的按钮，用于通过鼠标拖放选择屏幕上的窗口。
    """
    window_hover_signal = pyqtSignal(int, str)          # 开始拖动以及拖动过程中触发，发送选中的 hwnd 和 标题
    window_selected_signal = pyqtSignal(int, str, str)  # 释放鼠标时触发，发送选中的 hwnd、标题、选择器名称

    def __init__(self, selector_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.selector_name: str = selector_name
        self.setFixedSize(32, 32)
        self.setText("🎯")
        self.setToolTip(f"拖动此图标到目标窗口上以选择 '{selector_name}'")
        self._is_dragging: bool = False
        self._current_hover_hwnd: int = 0
        self._overlay_window: OverlayHighlightWindow = OverlayHighlightWindow()

        # 采用轮询来检测拖动过程
        self.polling_timer: QTimer = QTimer(self)
        self.polling_timer.setInterval(50)
        self.polling_timer.timeout.connect(self.poll_mouse_position)

    def mousePressEvent(self, event) -> None:
        """鼠标左键按下后执行一次"""
        if event.button() == Qt.LeftButton: # 鼠标左键按下后，进行初始化
            self._is_dragging = True        # 标记为正在选中
            self._current_hover_hwnd = 0    # 重置当前选中的窗口
            self._overlay_window.set_highlight_geometry(None)   # 清除高亮框
            QApplication.setOverrideCursor(Qt.CrossCursor)  # 把鼠标指针改成 "+"
            self.polling_timer.start()      # 开始轮询
            self.window_hover_signal.emit(0, "开始拖动...")

    def poll_mouse_position(self) -> None:
        """鼠标拖动过程中，检测当前落在什么窗口上，如果指向的窗口发生了变化，就更新高亮框并发出信号"""
        # --- 步骤 1: 状态检查 (安全阀) ---
        # 如果没在拖动，则关闭轮询
        if not self._is_dragging:
            if self.polling_timer.isActive():
                self.polling_timer.stop()
            return
        # --- 步骤 2: 获取最原始得输入信息 ---
        physical_cursor_pos = win32gui.GetCursorPos()   # 获取鼠标指针所在位置
        hwnd_under_cursor: int = win32gui.WindowFromPoint(physical_cursor_pos)  # 获取鼠标指针处得窗口句柄
        target_hwnd: int = 0
        window_title: str = ""
        new_hover_rect: Optional[QRect] = None

        if (hwnd_under_cursor and   # 规则1: 必须得有个窗口 (句柄不能是0或None)。
            hwnd_under_cursor != self.winId() and   # 规则2: 不能是选择器按钮自己。
            (self.parentWidget() is None or hwnd_under_cursor != self.parentWidget().winId()) and    # 规则3: 不能是包含选择器按钮的父窗口
            hwnd_under_cursor != win32gui.GetDesktopWindow() and    # 规则4: 不能是整个桌面。
            hwnd_under_cursor != self._overlay_window.winId()       # 规则5: 也不能是我们用来画高亮框的那个透明覆盖层窗口。
        ):

            # --- 步骤 4: 查找真正的顶级父窗口 ---
            root_hwnd: int = win32gui.GetAncestor(hwnd_under_cursor, win32con.GA_ROOTOWNER) or \
                             win32gui.GetAncestor(hwnd_under_cursor, win32con.GA_ROOT) or \
                             hwnd_under_cursor

            # --- 步骤 5: 验证并获取窗口信息 ---
            try:
                if win32gui.IsWindow(root_hwnd) and win32gui.IsWindowVisible(root_hwnd):
                    # 获取这个窗口在屏幕上的几何矩形 (x1, y1, x2, y2)。
                    rect_tuple = win32gui.GetWindowRect(root_hwnd)
                    # 再次过滤，排除掉那些非常小的、可能是工具提示或不可见元素的窗口。
                    if (rect_tuple[2] - rect_tuple[0]) > 20 and (rect_tuple[3] - rect_tuple[1]) > 20:
                        # 如果所有检查都通过了，我们就确定了本次轮询的目标！
                        target_hwnd = root_hwnd
                        window_title = win32gui.GetWindowText(target_hwnd) or "[无标题]"   # 获取窗口标题
                        # 根据物理坐标创建一个 Qt 的 QRect 对象，准备交给高亮框窗口去绘制。
                        new_hover_rect = QRect(rect_tuple[0], rect_tuple[1],
                                               rect_tuple[2] - rect_tuple[0],
                                               rect_tuple[3] - rect_tuple[1])
            except win32api.error:
                window_title = "[信息获取失败]"

        # --- 步骤 6: 检查变化并更新UI ---
        # 这是为了优化性能，避免在鼠标没移动到新窗口时，还不断地重绘和发信号。
        # 只有当本次找到的窗口句柄 (target_hwnd) 和上一次存储的句柄 (_current_hover_hwnd) 不一样时，才执行更新操作。
        if target_hwnd != self._current_hover_hwnd:
            self._current_hover_hwnd = target_hwnd  # 记录当前选中的窗口
            current_title = window_title if self._current_hover_hwnd else "在无效区域"
            self.window_hover_signal.emit(self._current_hover_hwnd, current_title)  # 发送 hwnd 和 标题
            # 更新高亮框：调用高亮框窗口的 set_highlight_geometry 方法，
            # 将新的窗口矩形传递给它去绘制。如果 new_hover_rect 是 None，高亮框就会被隐藏。
            self._overlay_window.set_highlight_geometry(new_hover_rect if self._current_hover_hwnd else None)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标松开时执行"""
        if event.button() == Qt.LeftButton and self._is_dragging:   # 松开鼠标触发
            self._is_dragging = False   # 标记为取消选中
            self.polling_timer.stop()   # 停止轮询
            QApplication.restoreOverrideCursor()    # 恢复鼠标指针
            self._overlay_window.set_highlight_geometry(None)   # 清除高亮框
            final_hwnd: int = self._current_hover_hwnd  # 获取最后选中的 hwnd
            if final_hwnd and win32gui.IsWindow(final_hwnd):
                try:
                    final_title = win32gui.GetWindowText(final_hwnd) or "[无标题]" # 获取标题
                except win32api.error:
                    final_title = "[获取标题失败]"
                self.window_selected_signal.emit(final_hwnd, final_title, self.selector_name)
            else:
                self.window_selected_signal.emit(0, "[未选择有效窗口]", self.selector_name)
            self._current_hover_hwnd = 0


# ==============================================================================
#                      ==== 测试案例 ====
# ==============================================================================
class TestMainWindow(QWidget):
    """
    一个简单的主窗口，用于承载和测试 DraggableSelectorWithOverlay 控件。
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("拖放选择器 - 测试窗口")
        self.setGeometry(300, 300, 400, 150)  # x, y, width, height

        # 创建一个布局
        layout = QVBoxLayout(self)

        # 创建一个标签，用于显示选择器的状态信息
        self.status_label = QLabel("请拖动下面的图标到其他窗口上", self)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; color: #333; border: 1px solid #ccc; padding: 5px;")

        # 创建我们的拖放选择器实例
        self.selector = DraggableSelectorWithOverlay("游戏窗口", self)

        # 将标签和选择器按钮添加到布局中
        layout.addWidget(self.status_label)
        layout.addWidget(self.selector, alignment=Qt.AlignCenter)  # 让按钮居中

        # 连接选择器的信号到我们的槽函数，以便更新标签内容
        self.selector.window_hover_signal.connect(self.on_window_hover)
        self.selector.window_selected_signal.connect(self.on_window_selected)

    # 当鼠标悬停在某个窗口上时，此函数被调用
    def on_window_hover(self, hwnd: int, title: str):
        self.status_label.setText(f"悬停: {title}")

    # 当释放鼠标并最终选定一个窗口时，此函数被调用
    def on_window_selected(self, hwnd: int, title: str, selector_name: str):
        self.status_label.setText(f"已为'{selector_name}'选择: {title}")
        self.status_label.setStyleSheet("font-size: 14px; color: #1a73e8; border: 1px solid #1a73e8; padding: 5px;")


if __name__ == '__main__':
    # 创建应用程序实例
    app = QApplication(sys.argv)

    # 创建并显示我们的测试主窗口
    main_window = TestMainWindow()
    main_window.show()

    # 启动应用程序的事件循环
    # 注意：在PyQt5中，通常使用 exec_() 以避免与Python的关键字`exec`冲突
    sys.exit(app.exec_())