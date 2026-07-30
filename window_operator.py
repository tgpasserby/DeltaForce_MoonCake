# window_operator.py

# ----- 导入官方库 -----
import os
import sys
import re
import time
import random
from collections.abc import Sequence
import logging
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple, Literal, Union, TypeVar, Dict, Any, Callable, List

# ----- 导入三方库 -----
import numpy as np
import win32clipboard
import win32gui
import win32api
import win32con
import win32ui
import win32process

# ----- 隔离加载 user32.dll -----
_user32 = ctypes.WinDLL('user32', use_last_error=True)

# 为 WindowOperator 用到的 API 声明类型
_user32.SetProcessDPIAware.argtypes = []
_user32.SetProcessDPIAware.restype = wintypes.BOOL

_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL

_user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
_user32.SwitchToThisWindow.restype = None

_user32.GetSystemMetrics.argtypes = [wintypes.INT]
_user32.GetSystemMetrics.restype = wintypes.INT

# 为 InputSimulator 用到的 API 声明类型
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT

_user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
_user32.VkKeyScanW.restype = ctypes.c_short

_user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_user32.MapVirtualKeyW.restype = wintypes.UINT

_user32.GetClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
_user32.GetClipCursor.restype = wintypes.BOOL
# -----------------------------------------------

_user32.SetProcessDPIAware()   # 开启物理坐标模式

# 创建日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

__version__ = "1.0.2"
__update__ = "2026.07.28"

T = TypeVar("T")    # 占位的类型

class WindowOperator:
    """
    一个绑定并操作特定窗口句柄(HWND)的操作器。
    功能包括：点击、截图、置顶、聚焦、转换坐标等等
    """
    def __init__(self, hwnd: Optional[int] = None):
        """
        初始化 WindowOperator。

        Args:
            hwnd: 目标窗口的句柄 (HWND)。
        """
        self.hwnd: Optional[int] = None                 # 窗口的句柄
        self.window_title: Optional[str] = "[未绑定]"    # 窗口的名称
        self.last_error: Optional[str] = None           # 最后一次出错的内容

        if hwnd:
            self.bind(hwnd)

    @property
    def is_bound(self) -> bool:
        """
        判断当前是否已经持有窗口句柄。
        只要 hwnd 不为 None，就认为处于绑定状态。
        """
        return self.hwnd is not None

    def unbind(self):
        """
        重新初始化 WindowOperator。
        """
        self.hwnd: Optional[int] = None                 # 窗口的句柄
        self.window_title: Optional[str] = "[未绑定]"    # 窗口的名称
        logger.debug("已解除窗口绑定。")

    def __str__(self) -> str:
        """返回对象的字符串表示。"""
        if self.hwnd:
            return f"<绑定到窗口 HWND:{self.hwnd} 标题:'{self.window_title}'>"
        else:
            return f"<未绑定窗口>"

    @staticmethod
    def is_valid_hwnd(hwnd_to_check: int) -> bool:
        """检查 HWND 是否是有效的窗口。"""
        if not hwnd_to_check:
            return False

        return win32gui.IsWindow(hwnd_to_check) != 0

    def is_valid(self):
        """检查自身绑定的是不是有效窗口"""
        return self.is_valid_hwnd(self.hwnd)

    def is_effectively_invalid(self) -> bool:
        """
        检查窗口是否已经“失效”（不仅是句柄消失，隐藏也算失效）。
        适合处理微信这种关闭后仍留驻后台的窗口。
        """
        # 1. 句柄彻底消失了
        if not win32gui.IsWindow(self.hwnd):
            return True

        # 2. 句柄还在，但窗口不可见了（微信、QQ 这种点 X 后进入后台的情况）
        if not win32gui.IsWindowVisible(self.hwnd):
            return True
        return False

    def _find_hwnd_by_title(self,
                            title_substring: str,
                            exact_match: bool = False,
                            find_top_level_parent: bool = True, ) -> Optional[int]:
        """
        根据标题子字符串查找窗口句柄。

        Args:
            title_substring: 要匹配的窗口标题子字符串（不区分大小写）。
            exact_match: 如果为 True，则标题必须完全相等（忽略大小写）；
                         如果为 False (默认)，则标题包含子串即可。
            find_top_level_parent: 如果为 True (默认)，则在找到匹配窗口后，
                                   会向上追溯并返回其最顶层的父窗口。
                                   这对于处理嵌套窗口结构的程序非常有用。
                                   如果为 False，则直接返回第一个找到的匹配窗口。

        Returns:
            找到的窗口句柄，如果未找到则返回 None。
        """
        self.last_error = None
        matched_hwnd: Optional[int] = None
        needle = title_substring.lower()

        def callback(hwnd: int, _) -> bool:
            """定义枚举函数"""
            nonlocal matched_hwnd

            # 已经找到后，后续窗口直接跳过，但仍继续枚举到结束
            if matched_hwnd is not None:
                return True

            try:
                # 检查窗口是否可见
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                current_title = win32gui.GetWindowText(hwnd) or ""
                haystack = current_title.lower()

                if exact_match:
                    is_match = (haystack == needle)
                else:
                    is_match = (needle in haystack)

                if is_match:
                    matched_hwnd = hwnd

            except Exception as e:
                # 单个窗口异常不影响整体枚举
                logger.debug(f"枚举窗口时跳过异常 hwnd={hwnd}: {e}")

            return True

        try:
            win32gui.EnumWindows(callback, None)
        except Exception as e:
            self.last_error = f"枚举窗口时出错: {e}"
            logger.error(self.last_error)
            return None

        if matched_hwnd is None:
            self.last_error = f"未找到标题包含 '{title_substring}' 的可见窗口。"
            logger.error(f"{self.last_error}")
            return None

        # --- 核心升级：向上追溯父窗口 ---
        if find_top_level_parent:
            top_level_hwnd = self.get_top_level_hwnd(matched_hwnd)
            if top_level_hwnd != matched_hwnd:
                logger.info(f"找到了匹配的子窗口 {matched_hwnd}，已向上追溯到其顶层父窗口 {top_level_hwnd} 进行绑定。")
            return top_level_hwnd or matched_hwnd
        else:
            # 如果不追溯，直接返回最初找到的句柄
            return matched_hwnd

    def move_and_resize(self,
                        x: Optional[int] = None,
                        y: Optional[int] = None,
                        width: Optional[int] = None,
                        height: Optional[int] = None) -> bool:
        """
        移动窗口到指定位置，并且调整其大小（可选）。

        Args:
            x: 左上角顶点x坐标
            y: 左上角顶点y坐标
            width: 宽度
            height: 高度

        Returns:
            bool - 是否执行成功
        """
        if not self.is_valid():
            self.last_error = "无法移动/调整窗口：未绑定到有效窗口或句柄已失效。"
            logger.error(f"{self.last_error}")
            return False

        try:
            # 准备 SetWindowPos 的参数
            flags = 0

            # 获取当前位置和尺寸
            current_rect: tuple[int, int, int, int] = win32gui.GetWindowRect(self.hwnd)
            current_x, current_y = current_rect[0], current_rect[1]
            current_width = current_rect[2] - current_rect[0]
            current_height = current_rect[3] - current_rect[1]

            # 确定目标值
            target_x = x if x is not None else current_x
            target_y = y if y is not None else current_y
            target_width = width if width is not None else current_width
            target_height = height if height is not None else current_height

            # 根据是否提供了参数，来决定 flags
            if x is None and y is None:
                flags |= win32con.SWP_NOMOVE
            if width is None and height is None:
                flags |= win32con.SWP_NOSIZE

            # --- 一些可以尝试的“魔法”标志 ---
            # SWP_NOZORDER: 保持窗口在Z序中的位置不变
            # SWP_NOACTIVATE: 操作后不激活窗口
            # SWP_FRAMECHANGED: 强制窗口重新计算其客户区等，有时能强制刷新布局
            flags |= win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED

            # 调用 SetWindowPos
            # 参数: (HWND, hWndInsertAfter, x, y, cx, cy, uFlags)
            # hWndInsertAfter 设为 0 表示忽略
            win32gui.SetWindowPos(self.hwnd, 0, target_x, target_y, target_width, target_height, flags)

            logger.info(f"已将窗口 '{self.window_title}' 移动/调整至 ({target_x}, {target_y}, {target_width}, {target_height})")
            return True

        except win32api.error as e:
            # 检查是否因为句柄失效导致的错误
            if e.winerror == 1400:  # ERROR_INVALID_WINDOW_HANDLE
                self.last_error = "窗口在操作前已经关闭。"
            else:
                self.last_error = f"移动/调整窗口时发生 win32api 错误: {e}"

            logger.error(f"{self.last_error}")
            return False

    @staticmethod
    def get_top_level_hwnd(hwnd: int) -> int:
        """
        向上追溯并返回其最顶层的可见父窗口句柄。
        这对于处理嵌套窗口结构的程序非常有用，防止绑定到无法接收键鼠消息的逻辑容器。

        Args:
            hwnd: 初始查找到的窗口句柄。

        Returns:
            最顶层的可见窗口句柄。如果无效则返回 0。
        """
        if not hwnd or not win32gui.IsWindow(hwnd):
            return 0

        top_level_hwnd = hwnd
        parent_hwnd = win32gui.GetParent(top_level_hwnd)

        # 只要还能找到父窗口，就继续向上
        while parent_hwnd != 0:
            # 检查父窗口是否也是可见的（更安全的做法）
            if win32gui.IsWindowVisible(parent_hwnd):
                top_level_hwnd = parent_hwnd
                parent_hwnd = win32gui.GetParent(top_level_hwnd)
            else:
                # 如果父窗口不可见，它可能只是一个逻辑容器，停止追溯
                break

        return top_level_hwnd

    def bind(self, target: Union[int, str], exact_match: bool = False) -> bool:
        """
        将操作器绑定到一个窗口。可以根据窗口句柄(int)或窗口标题(str)进行绑定。

        Args:
            target: 目标窗口的句柄(int)或标题中包含的字符串(str)。
            exact_match: 当 target 为字符串时，是否要求标题完全一致。

        Returns:
            bool - 绑定是否成功。
        """
        self.last_error = None
        found_hwnd = None

        # 1. 判断输入类型
        if isinstance(target, int):     # 按句柄 (标号) 绑定
            if self.is_valid_hwnd(target):
                found_hwnd = target
            else:
                self.last_error = f"提供的句柄 {target} 无效或窗口不存在。"
                logger.error(f"{self.last_error}")
        elif isinstance(target, str):  # 按标题 (名称) 绑定
            found_hwnd = self._find_hwnd_by_title(target, exact_match)
        else:
            self.last_error = f"绑定目标类型无效: 必须是 int (句柄) 或 str (标题)，但收到了 {type(target)}。"
            logger.error(f"{self.last_error}")
            return False

        # 2. 如果成功找到句柄，则完成绑定
        if found_hwnd:
            self.hwnd = found_hwnd
            try:
                self.window_title = win32gui.GetWindowText(self.hwnd) or "[无标题]"
            except win32api.error:
                self.window_title = "[已失效窗口]"

            logger.info(f"已成功绑定到窗口: '{self.window_title}' (句柄: {self.hwnd})")
            return True
        else:
            # 如果未找到句柄, 清理状态
            self.hwnd = None
            self.window_title = "[未绑定]"

            if not self.last_error:
                self.last_error = f"未能通过目标 '{target}' 找到有效的窗口。"

            logger.error(f"绑定失败: {self.last_error}")
            return False

    def lock_cursor_to_window(self) -> bool:
        """
        将鼠标光标的活动范围锁定在当前绑定的窗口内。

        Returns:
            bool - 如果锁定成功，则返回 True，否则返回 False。
        """
        if not self.is_valid():
            self.last_error = "无法锁定鼠标：未绑定到有效窗口或句柄已失效。"
            logger.error(f"{self.last_error}")
            return False

        try:
            # 1. 获取客户区的矩形（相对于窗口左上角）
            client_rect:tuple[int, int, int, int] = win32gui.GetClientRect(self.hwnd)

            # 2. 将客户区左上角和右下角的坐标转换为屏幕绝对坐标
            left_top_screen:tuple[int, int] = win32gui.ClientToScreen(self.hwnd, (client_rect[0], client_rect[1]))
            right_bottom_screen:tuple[int, int] = win32gui.ClientToScreen(self.hwnd, (client_rect[2], client_rect[3]))

            # 3. 构造一个用于 ClipCursor 的屏幕坐标矩形
            # 格式为 (left, top, right, bottom)
            screen_clip_rect:tuple[int, int, int, int] = (*left_top_screen, *right_bottom_screen)

            # 4. 调用 ClipCursor 进行锁定
            win32api.ClipCursor(screen_clip_rect)
            logger.info(f"鼠标已成功锁定到窗口 '{self.window_title}' 的客户区。")
            return True

        except win32api.error as e:
            self.last_error = f"锁定鼠标时发生 win32api 错误: {e}"
            logger.error(f"{self.last_error}")
            return False

    @staticmethod
    def _get_virtual_screen_rect() -> tuple[int, int, int, int]:
        """
        获取整个虚拟屏幕（多显示器拼接后的总桌面）的矩形范围。

        Returns:
            tuple[int, int, int, int]: (left, top, right, bottom)
        """
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return (left, top, left + width, top + height)

    @staticmethod
    def _get_clip_cursor_rect() -> tuple[int, int, int, int]:
        """
        读取当前系统鼠标裁剪矩形。

        Returns:
            tuple[int, int, int, int]: 当前 ClipCursor 矩形 (left, top, right, bottom)

        Raises:
            ctypes.WinError: 当调用 GetClipCursor 失败时抛出。
        """
        rect = wintypes.RECT()
        ok = _user32.GetClipCursor(ctypes.byref(rect))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return (rect.left, rect.top, rect.right, rect.bottom)

    @staticmethod
    def is_cursor_unlocked() -> bool:
        """
        判断鼠标当前是否已处于未裁剪状态（即可在整个虚拟屏幕范围内自由移动）。

        Returns:
            bool: 若当前裁剪矩形等于整个虚拟屏幕范围，则返回 True，否则返回 False。
        """
        try:
            return WindowOperator._get_clip_cursor_rect() == WindowOperator._get_virtual_screen_rect()
        except Exception as e:
            logger.debug(f"检测鼠标解锁状态失败: {e}")
            return False

    @staticmethod
    def unlock_cursor(check_interval: float = 0.01) -> bool:
        """
        持续解除鼠标光标的范围限制，直到确认已经恢复为全屏自由移动。

        这是一个阻塞式的可靠解锁方案：
        - 每轮先调用一次 ClipCursor(None) 尝试解除限制；
        - 随后立即读取当前裁剪矩形；
        - 若仍未解锁，则继续循环，直到确认成功。

        注意：
            如果有其他线程、定时器、外部程序或游戏持续重新调用 ClipCursor
            把鼠标锁回去，这个函数可能会长时间阻塞，直到外部锁定行为停止。

        Args:
            check_interval: 每次重试之间的等待时间（秒）。

        Returns:
            bool: 仅当确认已解除限制时返回 True。
        """
        while True:
            try:
                # 向 ClipCursor 传递 (0, 0, 0, 0) 即可解除锁定
                win32api.ClipCursor((0, 0, 0, 0))

                if WindowOperator.is_cursor_unlocked():
                    logger.info("鼠标已成功解锁，恢复全屏移动。")
                    return True

                logger.debug(
                    f"鼠标尚未完全解锁，继续重试。"
                )

                time.sleep(check_interval)

            except win32api.error as e:
                logger.error(f"解锁鼠标时发生错误: {e}")
                time.sleep(check_interval)

            except Exception as e:
                logger.warning(f"解锁鼠标时发生异常: {e}，继续重试。")
                time.sleep(check_interval)

    # @staticmethod
    # def unlock_cursor() -> bool:
    #     """
    #     解除对鼠标光标的所有范围限制，使其可以在整个屏幕上自由移动。
    #
    #     Returns:
    #         bool - 如果解锁成功，则返回 True，否则返回 False。
    #     """
    #     try:
    #         # 向 ClipCursor 传递 (0, 0, 0, 0) 即可解除锁定
    #         win32api.ClipCursor((0, 0, 0, 0))
    #         logger.info("鼠标已成功解锁，恢复全屏移动。")
    #         return True
    #     except win32api.error as e:
    #         # ClipCursor 很少失败，但以防万一
    #         logger.error(f"解锁鼠标时发生错误: {e}")
    #         return False

    def client_to_screens(self, relative_coords:T)->T:
        """
        递归地将 客户区相对坐标(x,y) 或 区域(x,y,w,h) 转换为屏幕绝对坐标。（核心方法）

        Args:
            relative_coords: 相对坐标数据。可以是元组(x,y), 列表[x,y]/[(x1,y1),(x2,y2)], 或字典{k1:(x1,y1),k2:(x2,y2),...}。

        Returns:
            转换后的绝对坐标数据，如果转换失败则返回 None。
        """
        if not self.is_valid():
            self.last_error = "未绑定到有效窗口，无法转换坐标。"
            logger.error(f"{self.last_error}")
            return None

        if win32gui.IsIconic(self.hwnd):
            self.last_error = f"窗口 '{self.window_title}' 已最小化，无法进行操作。"
            logger.error(f"{self.last_error}")
            return None

        if isinstance(relative_coords, (list, tuple)):
            # 如果是 (x, y)/[x, y] 坐标点
            if len(relative_coords) == 2 and all(isinstance(i, int) for i in relative_coords):
                abs_coords = self._client_to_screen(relative_coords)
                if abs_coords is None:
                    logger.error(f"坐标转换失败: {relative_coords} on window '{self.window_title}'")
                    return None
                return abs_coords
            # 如果是 (x, y, w, h) 区域
            elif len(relative_coords) == 4 and all(isinstance(i, int) for i in relative_coords):
                top_left_abs = self._client_to_screen((relative_coords[0], relative_coords[1]))
                if top_left_abs is None:
                    logger.error(f"区域左上角坐标转换失败: {relative_coords} on window '{self.window_title}'")
                    return None
                # 返回绝对坐标的区域 (abs_x, abs_y, width, height)
                return top_left_abs[0], top_left_abs[1], relative_coords[2], relative_coords[3]
            # 如果是坐标列表，递归处理
            else:
                converted_list = [self.client_to_screens(item) for item in relative_coords]
                # 只要列表中有一个转换失败，就认为整个列表失败
                if None in converted_list:
                    return None
                return converted_list

        # 如果是字典，递归处理其值
        elif isinstance(relative_coords, dict):
            converted_dict = {}
            for key, value in relative_coords.items():
                converted_value = self.client_to_screens(value)
                if converted_value is None:
                    return None # 任何一个子项转换失败，则整体失败
                converted_dict[key] = converted_value
            return converted_dict
        # 如果是数字或其他类型，直接返回
        else:
            return relative_coords

    def _client_to_screen(self, client_coords: Tuple[int, int]|list, clip_to_bounds: bool = True) -> Optional[Tuple[int, int]]:
        """
        将客户区坐标转换为屏幕绝对坐标。

        Args:
            client_coords: 一个包含 (x, y) 的元组，代表客户区坐标。
            clip_to_bounds: 是否截断到窗口区域内

        Returns:
            转换后的屏幕坐标元组 (screen_x, screen_y)，如果失败则返回 None。
        """
        try:
            if clip_to_bounds:
                # 把坐标限制到到窗口内
                # 1. 获取客户区的尺寸矩形
                client_rect = win32gui.GetClientRect(self.hwnd)
                client_width = client_rect[2]
                client_height = client_rect[3]
                client_coords = (
                    max(0, min(client_coords[0], client_width  - 1)),
                    max(0, min(client_coords[1], client_height - 1))
                )

            return win32gui.ClientToScreen(self.hwnd, client_coords)

        except win32api.error as e:
            self.last_error = f"坐标转换失败 (HWND: {self.hwnd}): {e}"
            logger.error(f"{self.last_error}")
            return None

    def set_topmost(self, enable: bool) -> bool:
        """
        设置或取消窗口的 置顶 状态。

        Args:
            enable: True 则设置为总在最前，False 则取消。

        Returns:
            bool - 操作是否成功。
        """
        if not self.is_valid():
            self.last_error = "无法置顶：窗口句柄无效或未绑定。"
            logger.error(f"{self.last_error}")
            return False

        # 只有设置置顶的时候才显示
        if enable:
            if not self.show():
                return False

        try:
            # 根据 enable 参数选择置顶或取消置顶的标志
            z_order_flag = win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST

            # 设置窗口位置的标志：
            # SWP_NOMOVE: 保持窗口位置不变
            # SWP_NOSIZE: 保持窗口大小不变
            # SWP_NOACTIVATE: 不激活窗口（重要，避免不必要的焦点切换）
            flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE

            # 调用 SetWindowPos 函数来改变窗口的 Z-order (层级)
            win32gui.SetWindowPos(self.hwnd, z_order_flag, 0, 0, 0, 0, flags)

            status_text = "设置" if enable else "取消"
            logger.info(f"已成功对窗口 '{self.window_title}' {status_text} '置顶' 状态。")
            return True
        except win32api.error as e:
            status_text = "设置" if enable else "取消"
            self.last_error = f"{status_text}窗口置顶状态失败: {e}"
            logger.error(f"{self.last_error}")
            return False

    def click(self,
              click_sequence: list[list] | list | tuple,
              button: Literal['left', 'right', 'middle'] = 'left',
              times: int = 1,
              delay: float = 0.02,
              hold_duration: float = 0.02,
              interval: float = 0.1,
              ) -> bool:
        """
        在窗口的指定客户区坐标处点击。

        Args:
            click_sequence: 点击坐标, (x, y) 或 [(x1, y1), (x2, y2)]
            button: 'left', 'right', 'middle'。
            times: 点击次数。
            delay: 点击前的等待时间。
            hold_duration: 模拟按住鼠标的精确时长（秒）。
            interval: 多次点击间的间隔。

        Returns:
            bool - 操作是否成功。
        """
        self.last_error = None

        if not self.is_valid():
            logger.error("请先绑定到有效窗口再操作。")
            return False

        # 1. 转换坐标并进行有效性检查
        screen_coords = self.client_to_screens(click_sequence)
        if not screen_coords:return False

        # 2. 统一坐标形式为 list[array]
        if isinstance(screen_coords, (list, tuple)) and len(screen_coords) > 0:
            if isinstance(screen_coords[0], int):
                points = [screen_coords]
            else:
                points = screen_coords
        elif isinstance(screen_coords, dict):
            points = list(screen_coords.values())
        else:
            return False

        # 3. 遍历执行点击
        try:
            for pt in points:
                InputSimulator.mouse_click(
                    *pt,
                    button=button,
                    times=times,
                    delay=delay,
                    hold_duration=hold_duration,
                    interval=interval
                )
            return True

        except Exception as e:
            logger.error(f"点击指令发送失败: {e}")
            return False

    def click_background(self,
                         client_coords: tuple[int, int],
                         button: Literal['left', 'right'] = 'left',
                         hold_duration: float = 0.05
                         ) -> bool:
        """
        在不移动鼠标光标的情况下，向窗口客户区的特定坐标点发送后台点击。

        此方法会找到该坐标下的窗口，并将点击消息直接发送给它。
        注意：对许多使用 DirectInput的游戏或 非标准UI的程序可能无效。
        已知三角洲部分按钮可以通过该方法点击（很多按钮要求鼠标在按钮上点击才有用）
        例如：主页面开始游戏按钮，在仓库或者交易行卖东西时候点击物品，交易行输入框

        Args:
            client_coords: (x, y) 窗口的相对坐标。
            button: 'left' 或 'right'。
            hold_duration: 点击持续时长

        Returns:
            bool - 如果成功找到窗口并发送消息，则返回 True，否则返回 False。
        """
        if not self.is_valid:
            logger.error("请先绑定到有效窗口再操作。")
            return False

        try:
            # 1. 确定鼠标事件标志位 (包含 wParam 标志)
            if button == 'left':
                down_msg = win32con.WM_LBUTTONDOWN
                up_msg = win32con.WM_LBUTTONUP
                wparam_down = win32con.MK_LBUTTON
            elif button == 'right':
                down_msg = win32con.WM_RBUTTONDOWN
                up_msg = win32con.WM_RBUTTONUP
                wparam_down = win32con.MK_RBUTTON
            else:
                return False

            # 2. 将 (x, y) 转换为 lParam
            lparam = win32api.MAKELONG(*client_coords)

            # --- 核心欺骗逻辑开始 ---

            # 第一步：发送 WM_MOUSEMOVE
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.02)  # 给引擎一帧的时间去更新内部虚拟光标

            # 第二步：发送按下消息 (携带 wParam_down 标志)
            win32gui.PostMessage(self.hwnd, down_msg, wparam_down, lparam)

            # 模拟人类按住鼠标的微小时间差
            time.sleep(hold_duration)

            # 第三步：发送弹起消息
            win32gui.PostMessage(self.hwnd, up_msg, 0, lparam)

            # 善后：某些 UI 需要鼠标移开才能完成 Click 判定 (可选)
            # win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(0, 0))

            return True

        except Exception as e:
            logger.error(f"后台点击异常: {e}")
            return False

    def capture(self,
                region: Optional[Tuple[int, int, int, int]] = None,
                use_print_window: bool = True) -> Optional[np.ndarray]:
        """
        【后台截图方案】支持窗口被遮挡时的画面抓取。
        注意：窗口不能最小化

        Args:
            region: 相对坐标区域 (x, y, w, h)。如果不填，则截取整个窗口。
            use_print_window: 是否使用 PrintWindow 模式（抗遮挡）。

        Returns:
            OpenCV 格式的 BGR 图像数组 (numpy array)。
        """
        # 1. 状态检查与尺寸获取
        if not self.is_valid():
            logger.error("窗口无效，无法截图")
            return None

        # 1. 获取窗口实时尺寸
        info = self.get_info()
        if not info or info['state'] == 'minimized':
            logger.warning("窗口最小化，无法截图。")
            return None

        width, height = info['window_size']

        # 2. 准备画布 (对齐 capture_region 流程)
        hwindc = win32gui.GetWindowDC(self.hwnd)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, width, height)
        memdc.SelectObject(bmp)

        # 3. 执行抓取 (核心差异：后台模式用 PrintWindow)
        if use_print_window:
            # 优先尝试标志位 2 (PW_RENDERFULLCONTENT), 失败则用 0
            if not _user32.PrintWindow(self.hwnd, memdc.GetSafeHdc(), 2):
                _user32.PrintWindow(self.hwnd, memdc.GetSafeHdc(), 0)
        else:
            memdc.BitBlt((0, 0), (width, height), srcdc, (0, 0), win32con.SRCCOPY)

        # 4. 获取原始数据并转换为 NumPy 数组
        signed_ints_array = bmp.GetBitmapBits(True)
        img_np = np.frombuffer(signed_ints_array, dtype='uint8')
        img_np.shape = (height, width, 4)  # BGRA 格式

        # 5. 转换颜色并处理局部裁剪
        img_np = img_np[:, :, :3]  # 截取 BGR

        if region:
            rx, ry, rw, rh = region
            # NumPy 切片实现局部裁剪 [y:y+h, x:x+w]
            img_np = img_np[max(0, ry):min(height, ry + rh), max(0, rx):min(width, rx + rw)]

        # 6. 释放资源
        srcdc.DeleteDC()
        memdc.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, hwindc)
        win32gui.DeleteObject(bmp.GetHandle())

        return img_np.copy()

    def capture_region(self,x: int|Sequence[int], y:int=None, width:int=None, height:int=None) -> np.ndarray:
        """
        截取窗口的相对坐标区域。

        Args:
            x (int): 截图区域的左上角 x 坐标，或者一个包含 (x, y, w, h) 的序列。
            y (int): 截图区域的左上角 y 坐标。
            width (int): 截图区域的宽度。
            height (int): 截图区域的高度。

        Returns:
            np.ndarray: 返回一个 OpenCV BGR 格式的图像数组。
        """
        # 如果第一个参数是列表或元组，就认为是序列模式

        if isinstance(x, (list, tuple)):
            if len(x) != 4:
                raise ValueError("如果提供一个序列，它必须包含4个整数 (x, y, width, height)")
            # 从序列中解包出所有变量
            x, y, width, height = x
        x, y = self._client_to_screen((x, y))

        hwin = win32gui.GetDesktopWindow()
        hwindc = win32gui.GetWindowDC(hwin)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, width, height)
        memdc.SelectObject(bmp)
        memdc.BitBlt((0, 0), (width, height), srcdc, (x, y), win32con.SRCCOPY)
        signed_ints_array = bmp.GetBitmapBits(True)
        img_np = np.frombuffer(signed_ints_array, dtype='uint8')
        img_np.shape = (height, width, 4)  # BGRA 格式
        srcdc.DeleteDC()
        memdc.DeleteDC()
        win32gui.ReleaseDC(hwin, hwindc)
        win32gui.DeleteObject(bmp.GetHandle())
        return img_np[:, :, :3].copy()

    @staticmethod
    def get_clipboard_content() -> Optional[str]:
        """获取剪贴板文本内容。"""
        content = None
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                content = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception as e:
            # 如果剪贴板被其他程序占用，打开可能会失败
            logger.error(f"获取剪贴板内容失败: {e}")

        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass # 如果关闭也失败，忽略

        return content

    @staticmethod
    def set_clipboard_content(text: str) -> bool:
        """设置剪贴板文本内容。"""
        if text is None:
            text = ""

        # CF_UNICODETEXT = UTF-16LE + 双字节 \0 结尾
        data = bytearray(str(text).encode("utf-16le") + b"\x00\x00")

        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, data)
            return True
        except Exception as e:
            logger.error(f"设置剪贴板内容失败: {e}")
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @staticmethod
    def typewrite(text: str,) -> bool:
        """
        在窗口中通过模拟 Ctrl+V 快速输入文本。

        Args:
            text: 要输入的字符串。

        Returns:
            操作是否成功。
        """
        return InputSimulator.typewrite(text)

    def minimize(self) -> bool:
        """
        将当前绑定的窗口最小化。

        Returns:
            bool - 操作是否成功。
        """
        if not self.is_valid():
            self.last_error = "无法最小化窗口：未绑定到有效窗口或句柄已失效。"
            logger.error(self.last_error)
            return False

        try:
            # 判断是否已经是最小化状态
            if not win32gui.IsIconic(self.hwnd):
                logger.info(f"正在最小化窗口 '{self.window_title}'...")
                # SW_MINIMIZE 会最小化窗口并激活 Z 序中的下一个顶层窗口
                win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
                return True
            else:
                logger.info(f"窗口 '{self.window_title}' 已经处于最小化状态。")
                return True
        except win32api.error as e:
            self.last_error = f"最小化窗口时发生 win32api 错误: {e}"
            logger.error(self.last_error)
            return False

    def maximize(self, force_focus: bool = True, wait_for_ready: float = 0.5) -> bool:
        """
        将当前绑定的窗口最大化。

        Args:
            force_focus: 最大化后是否强制将其设为前台活动窗口。
            wait_for_ready: 等待最大化动画完成的时间（秒）。

        Returns:
            操作是否成功。
        """
        if not self.is_valid:
            self.last_error = "无法最大化窗口：未绑定到有效窗口或句柄已失效。"
            logger.error(self.last_error)
            return False

        try:
            # 1. 检查当前状态，避免重复操作导致屏幕闪烁
            info = self.get_info()
            if info and info['state'] == 'normal/maximized':
                # GetWindowPlacement[1] (showCmd) 返回 SW_SHOWMAXIMIZED (3) 表示真正最大化
                placement = win32gui.GetWindowPlacement(self.hwnd)
                if placement[1] == win32con.SW_SHOWMAXIMIZED:
                    logger.info(f"窗口 '{self.window_title}' 已经是最大化状态。")
                    if force_focus:
                        self.show()  # 如果要求聚焦，调用我们强大的 show 方法
                    return True

            logger.info(f"正在最大化窗口 '{self.window_title}'...")

            # 2. 执行最大化操作
            # SW_MAXIMIZE (3): 最大化指定的窗口。
            win32gui.ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)

            # 3. 等待 Windows 动画和重绘完成
            time.sleep(wait_for_ready)

            # 4. 可选：强制拉到前台
            if force_focus:
                self.show()

            return True

        except win32api.error as e:
            self.last_error = f"最大化窗口时发生 win32api 错误: {e}"
            logger.error(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"最大化窗口时发生未知异常: {e}"
            logger.error(self.last_error)
            return False

    # def bind_by_details(self, query: str, match_index: int = 0) -> bool:
    #     """
    #     通过字符串表达式过滤并绑定窗口。
    #     支持语法示例:
    #     "title == '记事本' and state == 'normal/maximized'"
    #     "name == '三角洲行动' and client_size != (1, 2)"
    #
    #     Args:
    #         query: 过滤条件字符串。可用变量: title, state, hwnd, window_size, client_size
    #         match_index: 匹配到的第几个窗口
    #     """
    #     self.last_error = None
    #
    #     # 1. 获取系统中所有可见窗口的详细信息 (传入空字符串匹配所有)
    #     all_windows = self.find_windows_with_details("")
    #
    #     # 2. 预处理查询字符串，提高容错性
    #     # 把用户可能写的 "title = 'xxx'" 替换为 "title == 'xxx'"
    #     # 使用正则防止把 !=, >=, <= 里的等号给换了
    #     processed_query = re.sub(r'(?<![<>!=])=(?!=)', '==', query)
    #
    #     # 3. 执行过滤
    #     matched_windows = []
    #     for info in all_windows:
    #         try:
    #             # 为了方便用户，增加一个 'name' 别名指向 'title'
    #             info['name'] = info['title']
    #
    #             # 在 info 字典的上下文中执行表达式
    #             # eval 的第二个参数是全局变量(设为空)，第三个是局部变量(即我们的窗口信息)
    #             if eval(processed_query, {"__builtins__": None}, info):
    #                 matched_windows.append(info)
    #         except Exception as e:
    #             # 如果某个窗口信息缺失字段导致报错，跳过它
    #             continue
    #
    #     if not matched_windows:
    #         self.last_error = f"查询条件 '{query}' 未匹配到任何窗口。"
    #         logger.error(self.last_error)
    #         return False
    #
    #     if match_index >= len(matched_windows):
    #         self.last_error = f"查询到 {len(matched_windows)} 个窗口，但指定的索引 {match_index} 越界。"
    #         logger.error(self.last_error)
    #         return False
    #
    #     # 4. 获取句柄并绑定 (同样经过顶层追溯)
    #     target_hwnd = self.get_top_level_hwnd(matched_windows[match_index]['hwnd'])
    #     return self.bind(target_hwnd)

    @classmethod
    def find_windows_with_details(cls, target_title: str= "") -> list[dict]:
        """
        查找所有标题匹配的窗口，并返回包含窗口和客户区详细信息的字典列表。
        能正确处理最小化的窗口。

        Args:
            target_title (str): 目标窗口标题的一部分或全部。

        Returns:
            list[dict]: 字典列表，包含每个窗口的详细信息。
        """
        found_windows = []

        # 内部处理函数：提取并过滤
        def process_hwnd(hwnd):
            # 只处理可见的、有标题的窗口
            if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
                return

            info = cls.get_window_details(hwnd)
            if not info or not info['title']: return

            # 标题匹配逻辑 (忽略大小写)
            if target_title.lower() in info['title'].lower():
                # 过滤掉宽高为 0 的异常窗口
                if info['window_size'][0] > 0 and info['window_size'][1] > 0:
                    found_windows.append(info)

        # 策略 A：标准 EnumWindows
        try:
            win32gui.EnumWindows(lambda h, _: process_hwnd(h), None)

        except Exception:
            # 策略 B：备用 GetWindow 循环 (解决 126 错误)
            h = win32gui.GetDesktopWindow()
            h = win32gui.GetWindow(h, win32con.GW_CHILD)
            while h:
                process_hwnd(h)
                h = win32gui.GetWindow(h, win32con.GW_HWNDNEXT)

        return found_windows

    def get_info(self) -> Optional[Dict[str, Any]]:
        """
        获取当前绑定的窗口的详细信息，包括状态、位置、尺寸等。
        能正确处理最小化的窗口。

        Returns:
            一个包含窗口详细信息的字典，如果窗口无效或未绑定，则返回 None。
             字典结构:
             {
                 "hwnd": int,   # 窗口句柄
                 "title": str,  # 窗口标题
                 "state": str ("normal/maximized" 或 "minimized"),   # 状态，正常/最小化
                 "window_rect": tuple (left, top, right, bottom),   # 窗口占据的位置（包含标题）
                 "window_position": tuple (x, y),   # 左上角坐标（包含标题）
                 "window_size": tuple (width, height),  # 窗口占据大小（包含标题）
                 "client_position": tuple (x, y) 或 None,       # 画面内容左上角在屏幕上的坐标（最小化时为 None）
                 "client_size": tuple (width, height) 或 None,  # 纯净的画面大小（最小化时为 None）
             }
        """
        if not self.is_valid():
            self.last_error = "无法获取信息：未绑定到有效窗口或句柄已失效。"
            return None

        try:
            return self.get_window_details(self.hwnd)

        except win32api.error as e:
            self.last_error = f"获取窗口信息时发生 win32api 错误: {e}"
            logger.error(f"{self.last_error}")
            return None

    @staticmethod
    def get_window_details(hwnd: int) -> Optional[Dict[str, Any]]:
        """
        获取指定句柄窗口的完整详细信息。
        Args:
            hwnd: 指定句柄窗口

        Returns:
            完整详细信息，如果没有找到窗口则返回 None
        """
        if not win32gui.IsWindow(hwnd):
            return None

        try:
            # --- 1. 获取整个窗口的信息 (使用 GetWindowPlacement) ---
            # GetWindowPlacement 是获取窗口状态（最小化/最大化/正常）和位置的最可靠方法
            placement = win32gui.GetWindowPlacement(hwnd)
            show_cmd = placement[1]
            title = win32gui.GetWindowText(hwnd)

            # 判断窗口状态
            if show_cmd == win32con.SW_SHOWMINIMIZED:
                state = "minimized"
                # 对于最小化的窗口，GetWindowPlacement[4] 存放的是它恢复后的位置矩形
                window_rect = placement[4]
            else:
                state = "normal/maximized"
                # 对于正常显示的窗口，直接用 GetWindowRect 获取当前精确的屏幕位置
                window_rect = win32gui.GetWindowRect(hwnd)

            # 解析窗口位置和大小
            wx, wy, wr, wb = window_rect
            ww, wh = wr - wx, wb - wy

            # 2. 获取客户区信息 (只有非最小化才有意义)
            client_pos = None
            client_size = None

            if state != "minimized":
                try:
                    # 客户区左上角在屏幕上的绝对坐标
                    c_tl = win32gui.ClientToScreen(hwnd, (0, 0))
                    client_pos = (c_tl[0], c_tl[1])
                    # 客户区的纯净大小
                    c_rect = win32gui.GetClientRect(hwnd)
                    client_size = (c_rect[2], c_rect[3])
                except Exception:
                    # 某些高权限窗口可能无法获取客户区
                    pass

            # 3. 组装字典 (增加 name 别名，方便)
            return {
                "hwnd": hwnd,
                "title": title,
                # "name": title,
                "state": state,
                "window_rect": (wx, wy, wr, wb),
                "window_position": (wx, wy),
                "window_size": (ww, wh),
                "client_position": client_pos,
                "client_size": client_size,
            }
        except Exception as e:
            logger.debug(f"获取窗口 {hwnd} 详细信息失败: {e}")
            return None

    def focus(self, use_click_fallback: bool = False, attempts: int = 3, interval: float = 0.05) -> bool:
        """
        用于将窗口设为前台活动窗口（聚焦），它会循环尝试多次，每次尝试都会按顺序使用多种策略。

        Args:
            use_click_fallback: 如果为 True，将使用模拟鼠标点击作为最后的聚焦手段。
            attempts: 总共尝试的次数。
            interval: 每次完整尝试失败后的等待间隔（秒）。

        Returns:
            如果在任何一次尝试中成功激活窗口，则为True，否则为False。
        """
        if not self.is_valid():
            self.last_error = "无法聚焦：窗口句柄无效或未绑定。"
            logger.error(f"{self.last_error}")
            return False

        # --- 步骤 1: 确保窗口可见且已恢复 ---
        if not self.show():
            return False

        # 检查是否已是前景窗口
        if win32gui.GetForegroundWindow() == self.hwnd:
            return True

        # --- 进入主循环，进行多次尝试 ---
        for attempt in range(attempts):
            # 打印当前尝试次数，让日志更清晰
            logger.info(f"\n--- 第 {attempt + 1}/{attempts} 次尝试聚焦 '{self.window_title}', hwnd={self.hwnd} ---")

            # --- 策略 1: 尝试标准 SetForegroundWindow 方法 ---
            logger.info(f"尝试策略1：标准聚焦方法...")
            try:
                win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(0.05)
                if win32gui.GetForegroundWindow() == self.hwnd:
                    logger.info(f"已通过标准方法成功聚焦！")
                    return True
            except win32api.error as e:
                logger.warning(f"标准方法被阻止 (错误: {e.winerror})，继续...")

            # --- 策略 2: 尝试可靠的 "Alt-Tab 技巧" ---
            logger.info(f"尝试策略2：'Alt-Tab技巧'...")
            try:
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                time.sleep(0.05)
                try:
                    win32gui.SetForegroundWindow(self.hwnd)
                finally:
                    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)

                if win32gui.GetForegroundWindow() == self.hwnd:
                    logger.info(f"已通过'Alt-Tab技巧'成功聚焦！")
                    return True
            except win32api.error as e:
                logger.info(f"'Alt-Tab技巧'也被阻止 (错误: {e.winerror})，继续...")

            # --- 策略 3: (可选) 尝试模拟鼠标点击作为最后手段 ---
            if use_click_fallback:
                logger.info(f"尝试策略3：模拟点击聚焦...")
                try:
                    rect = win32gui.GetWindowRect(self.hwnd)
                    self.click(rect[0] + 10, rect[1] + 10)
                    time.sleep(0.1)
                    if win32gui.GetForegroundWindow() == self.hwnd:
                        logger.info(f"已通过模拟点击成功聚焦！")
                        return True
                except Exception as e:
                    logger.info(f"模拟点击时发生意外错误: {e}")

            # 如果本次尝试的所有策略都失败了，并且还不是最后一次尝试，则等待一段时间
            if attempt < attempts - 1:
                logger.info(f"--- 第 {attempt + 1} 次尝试失败，等待 {interval} 秒后重试... ---")
                time.sleep(interval)

        # 如果循环结束都没有成功，才宣布最终失败
        self.last_error = f"在 {attempts} 次尝试后，所有方法都无法将窗口 '{self.window_title}' (句柄: {self.hwnd}) 设为前台。"
        logger.error(f"{self.last_error}")
        return False

    def show(self, wait_for_ready: float = 0.5) -> bool:
        """
        强制显示并聚焦窗口（获取焦点）。
        尝试顺序：1.基础恢复 -> 2.Alt键诱骗 -> 3.Z序刷新+深度激活 -> 4.方案A(最小化恢复)

        Args:
            wait_for_ready: 最终操作完成后的缓冲等待时间。

        Returns:
            bool - 如果窗口最终成功成为前台活动窗口，返回 True。
        """
        if not self.is_valid():
            self.last_error = "无法显示窗口：未绑定或句柄失效。"
            logger.error(self.last_error)
            return False

        # --- 阶梯 0：状态自检 ---
        if win32gui.GetForegroundWindow() == self.hwnd:
            logger.info(f"窗口 '{self.window_title}' 已经是前台活动窗口，无需操作。")
            return True

        try:
            # --- 阶梯 1：基础显示恢复 (Basic Visibility) ---
            logger.info(f"正在尝试[基础恢复]模式: {self.window_title}")
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)

            time.sleep(0.03)
            if win32gui.GetForegroundWindow() == self.hwnd:
                logger.info("-> [基础恢复]成功！")
                return True

            # --- 阶梯 2：Alt 键诱骗法 (Alt-Key Bypass) ---
            # 这种方法干扰最小，且能绕过大部分 Foreground Lock
            logger.info("-> [基础恢复]未取得焦点，尝试[Alt键诱骗]...")
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # 按下 Alt
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)  # 释放 Alt

            time.sleep(0.03)
            if win32gui.GetForegroundWindow() == self.hwnd:
                logger.info("-> [Alt键诱骗]成功！")
                return True

            # --- 阶梯 3：Z序强制刷新 + 深度激活 (Z-Order & SwitchTo) ---
            # 有些窗口被压在后台，需要刷一下 Z 序并调用底层 Switch API
            logger.info("-> 尝试[Z序刷新]...")
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOP,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            )
            # SwitchToThisWindow 是 user32 的深层 API
            _user32.SwitchToThisWindow(self.hwnd, True)

            time.sleep(0.03)
            if win32gui.GetForegroundWindow() == self.hwnd:
                logger.info("-> [Z序刷新]成功！")
                return True

            # --- 阶梯 4：暴力方案 ---
            # 这是最后的兜底手段：先瞬间最小化，再瞬间恢复，强迫系统重新分配焦点
            logger.info("-> 尝试[最小化恢复闪现]...")
            win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            time.sleep(0.03)
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)

            # 再次配合一次深度激活
            _user32.SwitchToThisWindow(self.hwnd, True)

            # --- 阶梯 5：最终验证 ---
            time.sleep(wait_for_ready)
            if win32gui.GetForegroundWindow() == self.hwnd:
                logger.info("-> [最小化恢复闪现]成功！")
                return True
            else:
                self.last_error = f"所有方案均已尝试，无法将窗口 '{self.window_title}' 切换至前台（请检查是否具备管理员权限）。"
                logger.warning(self.last_error)
                return False

        except Exception as e:
            self.last_error = f"执行 show 策略链时发生异常: {e}"
            logger.error(self.last_error)
            return False

    @staticmethod
    def start_item(path: str) -> bool:
        """
        启动一个指定路径的文件、程序、文件夹或URL。
        其行为类似于在Windows中双击该项目。

        Args:
            path: 目标项目的完整路径或URL。

        Returns:
            是否成功启动
        """
        # 检查路径是否存在 (注意: 这对URL无效，但对本地文件系统路径有效)
        # 对于URL，os.path.exists会返回False，但os.startfile依然能处理
        if not path.startswith(('http://', 'https://')) and not os.path.exists(path):
            logger.error(f"路径不存在 -> '{path}'")
            return False
        else:
            logger.info(f"正在尝试启动: '{path}'...")
            try:
                # 核心代码：os.startfile 可以处理各种类型的路径
                os.startfile(path)
                return True
            except OSError as e:
                # 常见错误：找不到与文件类型关联的程序
                logger.error(f"启动时发生错误: {e}")
                if e.winerror == 1155:  # "No application is associated..."
                    logger.error(f"没有默认程序来打开这种类型的文件:{e}。")
                    return False
                else:
                    return False
            except Exception as e:
                logger.error(f"发生未知错误: {e}")
                return False

    def close(self, timeout: float = 3.0) -> bool:
        """
        向窗口发送关闭指令 (WM_CLOSE)。
        程序可以拦截此消息（例如弹出“是否保存”），或者缩小到托盘。

        Args:
            timeout: 等待窗口消失或隐藏的超时时间。

        Returns:
            bool - 如果窗口成功关闭或隐藏，返回 True。
        """
        if not self.is_valid():
            logger.info("窗口已不存在或未绑定，无需关闭。")
            return True

        try:
            logger.info(f"正在请求关闭窗口: '{self.window_title}'...")
            # 发送标准关闭信号
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

            # 循环检查窗口是否已经“消失”或“隐藏”
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.is_effectively_invalid():
                    logger.info(f"窗口 '{self.window_title}' 已成功关闭(或转入后台)。")
                    return True
                time.sleep(0.2)

            self.last_error = f"关闭窗口 '{self.window_title}' 超时，程序可能正在运行或拦截了关闭请求。"
            logger.warning(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"执行 close 时发生异常: {e}"
            logger.error(self.last_error)
            return False

    def terminate(self) -> bool:
        """
        【强制终止】直接杀死窗口所属的整个进程。
        不进行任何数据保存，瞬间抹除。适用于程序卡死或必须彻底退出的场景。

        Args:
            bool - 如果进程被成功终止，返回 True。
        """
        if not self.is_valid():
            logger.info("句柄已失效，进程可能已经退出。")
            return True

        try:
            # 1. 通过窗口句柄获取进程 PID
            _, pid = win32process.GetWindowThreadProcessId(self.hwnd)
            if pid == 0:
                return False

            logger.info(f"正在强行终止进程 PID: {pid} (窗口: '{self.window_title}')...")

            # 2. 使用 Windows API 强杀进程（比 os.kill 更底层、更可靠）
            # PROCESS_TERMINATE = 0x0001
            handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            if handle:
                win32api.TerminateProcess(handle, 0)
                win32api.CloseHandle(handle)

            logger.info(f"进程 {pid} 已被强制抹除。")

            self.hwnd = None
            return True

        except Exception as e:
            self.last_error = f"强制终止进程失败: {e}"
            logger.error(self.last_error)
            return False


# --- Windows 底层结构体定义 (C 语言兼容格式) ---
# 这些结构体告诉 Windows 内存中数据的精确排布
PUL = ctypes.POINTER(ctypes.c_ulong)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class INPUT_UNION(ctypes.Union):
    # Union 意味着这块内存既可以看作鼠标，也可以看作键盘
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("iu", INPUT_UNION)]

class InputSimulator:
    """
    基于 Windows SendInput API 的硬件级模拟器。
    负责处理最底层的鼠标和键盘信号。
    """
    # 常量定义
    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1

    # 鼠标标志位
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_ABSOLUTE = 0x8000  # 绝对坐标模式
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040
    _MOUSEEVENTF_WHEEL = 0x0800

    # 键盘标志位
    _KEYEVENTF_EXTENDEDKEY = 0x0001
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_SCANCODE = 0x0008  # 扫描码模式 (防屏蔽更好)
    _KEYEVENTF_UNICODE = 0x0004  # Unicode 模式 (支持中文/Emoji)

    # 扩展键列表 (这些键在发送 ScanCode 时通常需要 EXTENDEDKEY 标志)
    _EXTENDED_KEYS = {
        0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # PgUp, PgDn, End, Home, Arrows
        0x2C, 0x2D, 0x2E,  # PrintScreen, Insert, Delete
        0x90,  # NumLock
        0xA5, 0xA3,  # Right Alt, Right Ctrl
    }

    _VK_MAP = {
        'ctrl': 0x11, 'control': 0x11,
        'win': 0x5B, 'windows': 0x5B,
        'alt': 0x12, 'menu': 0x12,
        'shift': 0x10,
        'tab': 0x09,
        'enter': 0x0D, 'return': 0x0D,
        'space': 0x20,
        'backspace': 0x08, 'back': 0x08,

        # ----- 功能区 -----
        'printscreen': 0x2C, 'prtsc': 0x2C, 'prtscr': 0x2C,
        'pageup': 0x21, 'pgup': 0x21,
        'pagedown': 0x22, 'pgdn': 0x22,
        'end': 0x23,
        'home': 0x24,
        'insert': 0x2D, 'ins': 0x2D,
        'delete': 0x2E, 'del': 0x2E,
        'left': 0x25,
        'up': 0x26,
        'right': 0x27,
        'down': 0x28,

        'numlock': 0x90,

        'rctrl': 0xA3, 'rightctrl': 0xA3,
        'ralt': 0xA5, 'rightalt': 0xA5,

        'esc': 0x1B, 'escape': 0x1B,
        'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
        'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    }

    @staticmethod
    def _send_inputs(inputs: List[INPUT]):
        """执行发送指令序列"""
        n = len(inputs)
        input_array = (INPUT * n)(*inputs)
        return _user32.SendInput(n, ctypes.pointer(input_array), ctypes.sizeof(INPUT))

    @classmethod
    def mouse_click(cls, x: int, y: int,
                    button: Literal['left', 'right', 'middle'] = 'left',
                    times: int = 1,
                    delay: float = 0.02,
                    hold_duration: float = 0.02,
                    interval: float = 0.1):
        """
        在物理屏幕绝对坐标 (x, y) 处执行原子级点击。

        Args:
            x: 点击坐标
            y: 点击坐标
            button: 'left', 'right', 'middle'。
            times: 点击次数。
            delay: 点击前的等待时间。
            hold_duration: 模拟按住鼠标的精确时长（秒）。
            interval: 多次点击间的间隔。
        """
        # 1. 坐标标准化 (Windows 要求坐标在 0-65535 之间)
        screen_w = _user32.GetSystemMetrics(0)
        screen_h = _user32.GetSystemMetrics(1)
        nx = int(x * 65535 / screen_w)
        ny = int(y * 65535 / screen_h)

        # 2. 准备动作序列

        # 确定按键标志
        if button == 'left':
            down, up = cls._MOUSEEVENTF_LEFTDOWN, cls._MOUSEEVENTF_LEFTUP
        elif button == 'right':
            down, up = cls._MOUSEEVENTF_RIGHTDOWN, cls._MOUSEEVENTF_RIGHTUP
        else:
            down, up = cls._MOUSEEVENTF_MIDDLEDOWN, cls._MOUSEEVENTF_MIDDLEUP

        # 动作 A: 瞬移
        m_move = INPUT(type=cls._INPUT_MOUSE)
        m_move.iu.mi = MOUSEINPUT(nx, ny, 0, cls._MOUSEEVENTF_MOVE | cls._MOUSEEVENTF_ABSOLUTE, 0, None)
        cls._send_inputs([m_move])
        time.sleep(delay)

        # 动作 B: 按下
        m_down = INPUT(type=cls._INPUT_MOUSE)
        m_down.iu.mi = MOUSEINPUT(nx, ny, 0,cls._MOUSEEVENTF_MOVE | down | cls._MOUSEEVENTF_ABSOLUTE, 0, None)

        # 动作 C: 弹起
        m_up = INPUT(type=cls._INPUT_MOUSE)
        m_up.iu.mi = MOUSEINPUT(nx, ny, 0,cls._MOUSEEVENTF_MOVE | up | cls._MOUSEEVENTF_ABSOLUTE, 0, None)

        # 4. 执行连点循环
        for i in range(times):
            # 按下
            cls._send_inputs([m_down])
            # 物理按住时长
            time.sleep(hold_duration)
            # 弹起
            cls._send_inputs([m_up])
            # 连点间隔
            if i < times - 1: time.sleep(interval)

    @classmethod
    def typewrite(cls, text: str)->bool:
        """
        直接通过 Unicode 注入文字（支持中文/Emoji/特殊符号）。
        不经过剪贴板，不移动鼠标。
        """
        try:
            utf16_bytes = text.encode('utf-16-le')

            for i in range(0, len(utf16_bytes), 2):
                val = int.from_bytes(utf16_bytes[i:i + 2], byteorder='little')

                events = []
                # 按下
                inp_down = INPUT(type=cls._INPUT_KEYBOARD)
                inp_down.iu.ki = KEYBDINPUT(0, val, cls._KEYEVENTF_UNICODE, 0, None)
                events.append(inp_down)

                # 弹起
                inp_up = INPUT(type=cls._INPUT_KEYBOARD)
                inp_up.iu.ki = KEYBDINPUT(0, val, cls._KEYEVENTF_UNICODE | cls._KEYEVENTF_KEYUP, 0, None)
                events.append(inp_up)

                cls._send_inputs(events)
                time.sleep(0.01)  # 极小延迟防止缓冲区溢出
            return True
        except:
            return False

    @classmethod
    def _parse_vk(cls, key_str: str) -> int:
        """将字符串转换为虚拟键码"""
        key_str = key_str.lower().strip()

        # 1. 检查是否在映射表中 (如 'ctrl')
        if key_str in cls._VK_MAP:
            return cls._VK_MAP[key_str]

        # 2. 如果是单个字母或数字 (如 'v', '1')
        if len(key_str) == 1:
            try:
                # 直接传字符，不要传 ord()，依赖显式定义的 argtypes 处理
                res = _user32.VkKeyScanW(key_str)
                return res & 0xFF if res != -1 else 0
            except:
                return 0
        return 0

    @classmethod
    def press_hotkey(cls, hotkey: str, key_interval=(0.01, 0.03), duration=(0.05, 0.1)):
        """
        直接输入字符串组合键，如 "ctrl v", "ctrl+alt+del", "shift enter"
        """
        # 支持空格或加号分隔
        parts = re.split(r'[\s\+]+', hotkey)
        vk_codes = [cls._parse_vk(p) for p in parts if cls._parse_vk(p)]
        if not vk_codes: return False

        # 1. 阶梯式按下 (Staircase Down)
        # 例如 Ctrl V：先按 Ctrl -> 停顿 -> 再按 V
        for vk in vk_codes:
            cls._send_single_key(vk, is_down=True)
            time.sleep(random.uniform(*key_interval))

        # 2. 核心按住时长 (Holding Duration)
        # 确保所有键都按下后，保持一小段时间
        time.sleep(random.uniform(*duration))

        # 3. 阶梯式抬起 (Staircase Up - 逆序)
        # 物理规律：最后按下的通常最先抬起
        for vk in reversed(vk_codes):
            cls._send_single_key(vk, is_down=False)
            time.sleep(random.uniform(*key_interval))

        # 原子级一次性发射所有动作
        return True

    @classmethod
    def _send_single_key(cls, vk, is_down=True):
        """封装底层的单次输入发送"""
        flags = 0 if is_down else cls._KEYEVENTF_KEYUP
        # 强烈建议在此处加入 ScanCode 转换 logic，增加游戏兼容性
        inp = INPUT(type=cls._INPUT_KEYBOARD)
        inp.iu.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        return cls._send_inputs([inp])

    @classmethod
    def mouse_scroll(cls, clicks: int,
                     direction: Literal['up', 'down'] = 'down',
                     smooth: bool = False,
                     freq: int = 100,):
        """
        精确控制鼠标滚轮滚动。

        Args:
            clicks: 滚动的格数（齿数）。1 齿通常等于网页滚动的 3 行。
            direction: 'up' (向上滚，内容往下走) 或 'down' (向下滚，内容往上走)。
            smooth: 是否平滑滚动（分步发送小增量）。
            freq: 平滑滚动时的帧率（不要超过屏幕刷新帧率）。
        """
        # 1. 计算总增量 (WHEEL_DELTA = 120)
        # down 是负数 (-120)，up 是正数 (+120)
        delta_per_click = -120 if direction == 'down' else 120
        total_delta = clicks * delta_per_click
        step_delay = 1/freq     # 每次滑动后休息时间

        if not smooth:
            # --- 方案 A：瞬间滚动（直接把总值砸过去）---
            inp = INPUT(type=cls._INPUT_MOUSE)
            inp.iu.mi = MOUSEINPUT(0, 0, delta_per_click, cls._MOUSEEVENTF_WHEEL, 0, None)

            for _ in range(clicks):
                cls._send_inputs([inp])
                time.sleep(step_delay)

        else:
            # --- 方案 B：平滑滚动（模拟人类慢慢搓滚轮）---
            # 将每次滚动的增量拆分为更细的 1/3 格 (40) 或 1/2 格 (60)，这里选 40 比较平滑
            step_size = -40 if direction == 'down' else 40
            steps = abs(total_delta) // abs(step_size)

            for _ in range(steps):
                inp = INPUT(type=cls._INPUT_MOUSE)
                inp.iu.mi = MOUSEINPUT(0, 0, step_size, cls._MOUSEEVENTF_WHEEL, 0, None)
                cls._send_inputs([inp])
                time.sleep(step_delay)

            # 补偿可能除不尽的余数（虽然 120/40 能除尽，但养成好习惯）
            remainder = total_delta - (steps * step_size)
            if remainder != 0:
                inp = INPUT(type=cls._INPUT_MOUSE)
                inp.iu.mi = MOUSEINPUT(0, 0, remainder, cls._MOUSEEVENTF_WHEEL, 0, None)
                cls._send_inputs([inp])

    @classmethod
    def cover(cls, pos:tuple[int,int]=(), content:str="Hello World!", click_delay: float = 0.3):
        """
        覆盖输入文本
        Args:
            pos: 可选，按下ctrl + a 前点击一下
            content: 要覆盖的文本
            click_delay: 点击输入框后，等待UI获取焦点和响应的时间。

        Returns:
            None
        """
        # ----- 如果有输入坐标，则点击一下 -----
        if isinstance(pos, (tuple,list)) and len(pos)==2:
            cls.mouse_click(*pos, delay=0.1, hold_duration=0.1)
            time.sleep(click_delay)

        cls.press_hotkey("ctrl a")
        cls.typewrite(content)

    @classmethod
    def smart_cover(cls, pos: tuple[int, int] = (), content: str = "Hello World!", click_delay: float = 0.1) -> bool:
        """
        智能覆盖输入文本。
        流程：点击 -> 全选 -> 复制 -> 校验 -> (一致则跳过 / 不一致则覆盖输入)
        作用：防止重复输入相同的文本，触发游戏内高延迟的联想搜索或网络刷新。

        Args:
            pos: 可选，输入框的绝对屏幕坐标 (x, y)。如果不填则直接在当前鼠标位置操作。
            content: 想要输入的目标文本。
            click_delay: 点击输入框后，等待UI获取焦点和响应的时间。

        Returns:
            bool: 操作是否成功。
        """
        # 1. 预处理目标文本
        target_str = content.strip()

        # 2. 如果提供了坐标，则先点击获取焦点
        if isinstance(pos, (tuple, list)) and len(pos) == 2:
            cls.mouse_click(*pos, delay=0.05, hold_duration=0.05)
            time.sleep(click_delay)

        # 3. 获取当前框内文本
        WindowOperator.set_clipboard_content("")
        cls.press_hotkey("ctrl a c")
        current_str = WindowOperator.get_clipboard_content().strip()

        # 4. 比对内容
        if current_str == target_str:
            logger.info(f"输入框内容已是 '{content}'，跳过输入。")
            # 取消全选的蓝色高亮状态，防止后续误触键盘删掉文本
            cls.press_hotkey("right")
            return True

        elif target_str == "":
            # 场景 A: 目标是清空，且当前框里有东西
            logger.info(f"输入框当前内容为 '{current_str}'，目标为空，执行【删除】。")
            # 因为处于全选状态，敲击一次 Backspace(退格键) 即可彻底清空
            cls.press_hotkey("backspace")
            return True
        else:
            # 场景 B: 目标是新文本，直接覆盖
            logger.info(f"输入框当前内容为 '{current_str}'，执行【覆写】: '{target_str}'")
            WindowOperator.set_clipboard_content(target_str)    # 设置剪贴板
            cls.press_hotkey("ctrl v")

            return True

def demo():
    operator = WindowOperator()
    print("这个案例用于演示功能")
    print(">>> 正在尝试通过标题 '月饼' 绑定游戏窗口...")
    time.sleep(1.0)
    operator.bind("月饼的")
    if operator.is_valid():
        print(">>> 正在展示信息...")
        time.sleep(1.0)
        print(operator.get_info())

# --- 使用示例 ---
if __name__ == '__main__':
    logger.setLevel(logging.INFO)
    demo()