# -*- coding: utf-8 -*-

# template_recognizer.py

# ----- 导入官方库 -----
import os
import logging
import time
from typing import Optional, Literal, Union, Tuple
from collections.abc import Sequence

# ----- 导入三方库 -----
import cv2
from IPython.display import display, Image
import numpy as np
import win32con
import win32gui
import win32print
import win32ui

# ----- 导入自用库 -----
from basic_tools import timing_decorator

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

__version__ = "1.0.2"
__update__ = "2026.07.28"

class ImageProcessor:
    """专用于图像处理的工具类"""

    # 灰度图的统一预处理方法
    PREPROCESS_GRAY = {
        "output_mode": "gray",
        "scale_factor": 5,
        "median_blur": False,
        "sharp": True,
        "enable_cropping": True,
    }

    # 黑白图的统一预处理方法
    PREPROCESS_B = {
        "output_mode": "binary",
        "scale_factor": 5,
        "median_blur": True,
        "sharp": True,
        "enable_cropping": True,
    }

    @staticmethod
    def save_screen(x: int|Sequence[int], y:int=None, width:int=None, height:int=None,
                    file_name:str=r'debug\screen.png')->None:
        """截图并保存"""
        if isinstance(x, (list, tuple)):
            if len(x) != 4:
                raise ValueError("如果提供一个序列，它必须包含4个整数 (x, y, width, height)")
            # 从序列中解包出所有变量
            x, y, width, height = x

        screenshot = ImageProcessor.capture_region(x, y, width, height)
        ImageProcessor.save_image(image_path = file_name, image_np = screenshot)

    @staticmethod
    def capture_full_screen(file_name = 'full_sc.png', save:bool=True)->np.ndarray:
        """截全屏，可选保存"""
        w, h = ImageProcessor.get_real_resolution()

        screenshot = ImageProcessor.capture_region(0, 0, w, h)

        # 可选保存
        if save:
            ImageProcessor.save_image(image_path=file_name, image_np = screenshot,)

        return screenshot

    @staticmethod
    def get_real_resolution() -> tuple[int,int]:
        """
        获取真实的物理分辨率，不受缩放影响。
        如果有多个显示器，则返回主屏幕的分辨率。
        """
        # 1. 获取桌面的设备上下文句柄 (DC)
        hDC = win32gui.GetDC(0)

        try:
            # 2. 获取真实的物理分辨率 (DESKTOPHORZRES, DESKTOPVERTRES)
            # 118: DESKTOPHORZRES (物理宽度)
            # 117: DESKTOPVERTRES (物理高度)
            w_real:int = win32print.GetDeviceCaps(hDC, 118)
            h_real:int = win32print.GetDeviceCaps(hDC, 117)

            return w_real, h_real

        finally:
            # 4. 释放 DC，防止内存泄漏
            win32gui.ReleaseDC(0, hDC)

    @staticmethod
    def capture_region(x: int|Sequence[int], y:int=None, width:int=None, height:int=None) -> np.ndarray:
        """
        使用 Win32 API 截取屏幕指定区域。
        在截图 2560x1600 时最高可以跑 20FPS（不用再优化了，也没法优化了）
        在截图 100x50 时耗时 5ms
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
                raise ValueError("如果提供一个序列，它必须包含4个整数 (x, y, w, h)")
            # 从序列中解包出所有变量
            x, y, width, height = x

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
        return img_np[:, :, :3]

    @staticmethod
    def load_image(image_path: str, mode: str = "bgr") -> np.ndarray:
        """
        从本地读取指定路径的图片，并返回 OpenCV BGR 格式的 np.ndarray。

        Args:
            image_path (str): 图片的绝对或相对路径。
            mode (str): 读取模式，可选：
                - "bgr"  : 读取为 BGR 三通道图像（默认）
                - "gray" : 读取为灰度单通道图像

        Returns:
            np.ndarray:
                - mode="bgr" 时返回 BGR 格式图像数组，shape=(H, W, 3)
                - mode="gray" 时返回灰度图像数组，shape=(H, W)

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: mode 非法，或图片无法读取
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"文件不存在: {image_path}")

        mode_map = {
            "bgr": cv2.IMREAD_COLOR,
            "gray": cv2.IMREAD_GRAYSCALE,
        }

        if mode not in mode_map:
            raise ValueError(
                f"不支持的读取模式: {mode}。可选值为 'bgr' 或 'gray'"
            )

        # 支持中文路径：先读二进制，再由 OpenCV 解码
        data = np.fromfile(image_path, dtype=np.uint8)
        image = cv2.imdecode(data, mode_map[mode])

        if image is None:
            raise ValueError(f"无法读取图片，可能是文件损坏、格式不支持或不是有效图片: {image_path}")

        return image

    @staticmethod
    def save_image(image_path: str, image_np: np.ndarray, ) -> bool:
        """
        将图像保存到本地指定路径。
        支持中文路径。

        Args:
            image_path (str): 输出图片的绝对或相对路径。
            image_np (np.ndarray): 待保存的图像数组 BGR。

        Returns:
            bool: 保存成功返回 True。

        Raises:
            ValueError: 图像为空、格式非法，或保存失败。
            FileNotFoundError: 目标目录不存在。
        """
        # 1. 基础校验
        if image_np is None:
            raise ValueError("image_np 不能为空")

        if not isinstance(image_np, np.ndarray):
            raise ValueError("image_np 必须是 numpy.ndarray")

        if image_np.size == 0:
            raise ValueError("image_np 不能为空数组")

        if not image_path or not isinstance(image_path, str):
            raise ValueError(f"无效路径：{image_path}")

        # 2.提取扩展名
        ext = os.path.splitext(image_path)[1]
        if not ext:
            ext = '.png'
            image_path += ext

        # 3. 自动创建目录
        parent_dir = os.path.abspath(os.path.dirname(image_path))
        if not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                raise OSError(f"无法创建目录 {parent_dir}: {e}")

        # 4. 支持中文路径：先编码，再写入文件
        success, encoded_img = cv2.imencode(ext, image_np)
        if not success or encoded_img is None:
            raise ValueError(f"图片编码失败，可能是不支持的扩展名或图像格式: {image_path}")

        try:
            encoded_img.tofile(image_path)
        except Exception as e:
            raise ValueError(f"图片保存失败: {image_path}, 错误: {e}")

        return True

    @staticmethod
    def draw_and_save_debug(target_img: np.ndarray,
                            top_left: tuple[int, int],
                            w: int,
                            h: int,
                            filename: str):
        """
        内部辅助方法：在测试模式下，绘制匹配框并保存图片。

        Args:
            target_img: 原始背景图（BGR）。
            top_left: 匹配到的左上角坐标 (x, y)。
            w: 模板宽度。
            h: 模板高度。
            filename: 保存的文件名。
        """
        # 1. 复制原图避免污染
        debug_img = target_img.copy()

        # 2. 计算右下角坐标
        bottom_right = (top_left[0] + w, top_left[1] + h)

        # 绘制绿色矩形框 (线宽 3)
        cv2.rectangle(debug_img, top_left, bottom_right, (0, 255, 0), 3)

        # 保存图片
        ImageProcessor.save_image(image_path=filename, image_np=debug_img)
        logger.info(f"测试图片已保存至: {filename}")

    @staticmethod
    def show_image(image_np: np.ndarray):
        """展示 cv2读取的 BGR 格式图片"""
        img_bgr = image_np
        _, buffer = cv2.imencode('.png', img_bgr)
        display(Image(data=buffer.tobytes()))

    @staticmethod
    def find_all_item_slots_by_grid(
            image_np: np.ndarray,
            grid_start_xy: tuple = (0, 0),
            slot_size: tuple = (48, 48),
            slot_gap: tuple = (0, 0),
            grid_dimensions: tuple = (10, 9),
            detection_thresholds: tuple = (0.08, 10.0),
            detection_thresholds2: tuple = (70.0, 90.0, 0.25),
            debug: bool = False,
            filename = 'find_items_hybrid',
            method :int= 1,
    ) -> tuple[bool, tuple[int, int] | None]:
        """
        通过【混合特征法】在网格中寻找第一个非空物品格子。

        - 核心逻辑：一个格子被认为是“有物品”的，如果它的【边缘密度】和【亮度标准差】都超过了设定的阈值。
        - 生产模式(debug=False): 找到第一个物品后立即返回，以获得最快速度。
        - 调试模式(debug=True): 遍历所有格子，并保存一张可视化结果图。

        Args:
            image_np:             要检测的图片 np 数组
            grid_start_xy:        检测起始像素
            slot_size:            每个格子的大小
            slot_gap:             每个格子之间的间隙
            grid_dimensions:      划分的网格, n 行 m 列
            detection_thresholds: (边缘密度阈值, 亮度标准差阈值)
            detection_thresholds2:饱和度阈值，亮度阈值，比例阈值）
            debug:                是否采用测试模式
            filename:             测试模式下保存的图片名称
            method:               用什么检测算法。1表示(边缘密度,亮度标准差)；2表示（饱和度，亮度，比例）；-1 表示 1和 2结合起来

        Returns:
            tuple[bool, tuple[int, int] | None]:
            - 第一个元素 (bool): 是否找到了非空格子。
            - 第二个元素 (tuple | None): 如果找到，则返回【第一个】找到的格子中心的(x, y)坐标；否则返回 None。
        """
        try:
            # --- 步骤 1: 初始化和参数解包 ---
            debug_image = image_np.copy() if debug else None
            found_item_coords = []  # 用于存储找到的所有7有内容的格子中心点坐标

            start_x, start_y = grid_start_xy
            slot_w, slot_h = slot_size
            gap_x, gap_y = slot_gap
            rows, cols = grid_dimensions

            # 解包混合阈值
            edge_density_thresh, v_std_thresh = detection_thresholds
            sat_thresh, val_thresh, non_gray_ratio_thresh = map(float, detection_thresholds2)

            # --- 步骤 2: 遍历网格并分析每个格子 ---
            for c in range(cols):
                for r in range(rows):
                    # a. 计算当前格子的精确坐标
                    top_left_x = start_x + c * (slot_w + gap_x)
                    top_left_y = start_y + r * (slot_h + gap_y)

                    # b. 提取当前格子的图像区域 (Region of Interest)
                    # 同时为两种计算做准备
                    slot_roi_bgr = image_np[top_left_y: top_left_y + slot_h,
                                            top_left_x: top_left_x + slot_w]    # 每个格子的切片

                    # c. 确保提取的区域有效，主要是去掉裁剪剩下的边角料
                    if slot_roi_bgr.shape[0] != slot_h or slot_roi_bgr.shape[1] != slot_w:
                        continue

                    # d. 计算核心特征
                    if method == 1 or method == -1:
                        #   特征1: 边缘密度 (Edge Density)
                        slot_roi_gray = cv2.cvtColor(slot_roi_bgr, cv2.COLOR_BGR2GRAY)
                        edges = cv2.Canny(slot_roi_gray, 50, 150)
                        edge_density = np.count_nonzero(edges) / (edges.size or 1)

                        #   特征2: 亮度标准差 (Value Standard Deviation)
                        slot_roi_hsv = cv2.cvtColor(slot_roi_bgr, cv2.COLOR_BGR2HSV)
                        v_std = np.std(slot_roi_hsv[:, :, 2])

                        # e. 进行混合判断
                        is_item_found1 = (edge_density > edge_density_thresh) and (v_std > v_std_thresh)

                    if method == 2 or method == -1:
                        # --- 计算非黑灰占比 ---
                        roi_hsv = cv2.cvtColor(slot_roi_bgr, cv2.COLOR_BGR2HSV)
                        s = roi_hsv[:, :, 1]
                        v = roi_hsv[:, :, 2]

                        # # 黑/灰判定：低饱和 或 低亮度
                        # gray_mask = (s < sat_thresh) | (v < val_thresh)

                        # 黑/灰判定：低饱和 且 低亮度
                        gray_mask = (s < sat_thresh) & (v < val_thresh)
                        total = gray_mask.size
                        non_gray_ratio = 1.0 - (np.count_nonzero(gray_mask) / total if total > 0 else 1.0)
                        is_item_found2 = (non_gray_ratio > non_gray_ratio_thresh)

                    if method == 1:
                        is_item_found = is_item_found1
                    elif method == 2:
                        is_item_found = is_item_found2
                    elif method == -1:
                        is_item_found = is_item_found1 and is_item_found2
                    else:
                        is_item_found = False
                    # 在非调试模式下直接退出，返回第一个格子的中心坐标
                    if is_item_found:
                        center_x = top_left_x + slot_w // 2
                        center_y = top_left_y + slot_h // 2
                        if not debug:
                            return True, (center_x, center_y)
                        else:
                            found_item_coords.append((center_x, center_y))

                    if debug:
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.35
                        thickness = 1
                        color = (0, 255, 0) if is_item_found else (255, 100, 100)
                        box_thickness = 2 if is_item_found else 1
                        cv2.rectangle(debug_image, (top_left_x, top_left_y),
                                      (top_left_x + slot_w, top_left_y + slot_h), color, box_thickness)

                        if method == 1:
                            # 在上下两行分别绘制文本
                            text_e = f"E:{edge_density:.2f}"
                            pos_e = (top_left_x + 2, top_left_y + 10)
                            cv2.putText(debug_image, text_e, pos_e, font, font_scale, color, thickness)

                            text_v = f"V:{v_std:.1f}"
                            pos_v = (top_left_x + 2, top_left_y + slot_h - 5)
                            cv2.putText(debug_image, text_v, pos_v, font, font_scale, color, thickness)

                        elif method == 2:
                            pos = (top_left_x + 2, top_left_y + 10)
                            text = f"{non_gray_ratio:.2f}"
                            cv2.putText(debug_image,text ,pos, font, font_scale, color, thickness)

            # --- 步骤 3: 处理遍历结束后的结果 ---
            if debug:
                if found_item_coords:
                    first_item_center = found_item_coords[0]
                    cv2.circle(debug_image, first_item_center, 5, (0, 0, 255), -1)

                    debug_folder = 'debug'
                    os.makedirs(debug_folder, exist_ok=True)
                    filename = filename+str(method)+'.png'
                    # 使用一个新名字保存，以区别于旧方法的结果
                    save_path = os.path.join(debug_folder, filename)
                    cv2.imwrite(save_path, debug_image)
                    logger.info(f"调试图像已保存到: {save_path}")

                    return True, first_item_center
                else:
                    logger.info("混合特征法：未在任何格子中找到物品。")
                    return False, None
            else:
                # 生产模式下，代码能走到这里意味着整个循环都没有找到物品
                logger.info("混合特征法：未在任何格子中找到物品。")
                return False, None

        except Exception as e:
            logger.error(f"混合特征法寻找物品时出错: {e}", exc_info=True)
            return False, None

    @staticmethod
    def detect_amount(image_np: np.ndarray, first:bool=False,
                      number_height = 30,save_path = None) -> np.ndarray | None:
        """
        通过检测下方的水平分割线来定位并裁剪图像顶部的文本区域。

        该函数使用Sobel算子计算垂直梯度，并从上到下扫描，
        寻找第一个梯度总和超过动态阈值的行作为分割线。

        Args:
            image_np: 输入的OpenCV图像（BGR格式的NumPy数组）。
            first:是不是第一个柱子，第一个柱子要特殊处理。
            number_height: 找到横线后，往上截取的价格高度。
            save_path: 保存的路径，如果填写，则生成一张带有定位标记的调试图片，
                并保存到 save_path。
        Returns:
            np.ndarray | None:
                如果成功，返回裁剪出的文本区域的图像数据（NumPy数组）。
                如果未能找到分割线，则返回 None。

        """
        if image_np is None:
            return None

        DEFAULT_SEARCH_OFFSET_Y = 5

        # --- 步骤1: 计算垂直梯度 ---
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)  # 转换为灰度图
        sobel_y = cv2.Sobel(gray[:, -10:], cv2.CV_64F, 0, 1, ksize=3)
        gradient_image = np.uint8(np.absolute(sobel_y))

        # --- 步骤2: 设定阈值并从上到下寻找第一个匹配项 ---
        # row_energies = np.sum(gradient_image, axis=1)
        row_energies = np.mean(gradient_image, axis=1)

        # 计算一个动态阈值，以适应不同对比度的图片
        max_energy = np.max(row_energies)

        threshold = 0.20 if first else 0.95
        # threshold = 0.95
        gradient_threshold = max_energy * threshold

        y_line_boundary = -1

        # 从顶部偏移量之后开始向下扫描，避免图像顶部边缘的干扰
        for y in range(DEFAULT_SEARCH_OFFSET_Y + number_height, image_np.shape[0]-5):
            if row_energies[y] > gradient_threshold:
                if not first:
                    y_line_boundary = y  # 找到了！
                    break  # 立刻停止搜索
                else:
                    # --- 计算裁剪区域,比较一下是否均匀 ---
                    y1 = max(0, y - number_height)
                    y2 = y

                    # 从原始图像中裁剪出目标区域
                    # 经验阈值：背景很均匀时 CV 很小；含数字/纹理时 CV 增大
                    cropped_image_gray = gray[y1 - 3:y2 - 3, :]
                    m, s = cv2.meanStdDev(cropped_image_gray)
                    cv = float(s[0,0] / m[0,0]+1e-6)
                    if cv < 0.1:    # 如果太相似，则说明不是
                        continue
                    else:
                        y_line_boundary = y
                        break  # 立刻停止搜索

        # --- 步骤3: 如果未找到，返回None ---
        if y_line_boundary == -1:
            return None

        # --- 步骤4: 如果找到，计算裁剪区域 ---
        y1 = max(0, y_line_boundary - number_height)
        y2 = y_line_boundary

        # 从原始图像中裁剪出目标区域
        cropped_image = image_np[y1-3:y2-3, :]

        # --- 步骤5: 如果是测试模式，绘制并保存调试图片 ---
        if save_path:
            # 创建一个副本以进行绘制，不修改原始图像
            debug_image = image_np.copy()

            # 绘制找到的分割线 (红色)
            cv2.line(debug_image, (0, y_line_boundary), (image_np.shape[1], y_line_boundary), (0, 0, 255), 2)

            # 绘制识别框 (绿色)
            cv2.rectangle(debug_image, (0, y1), (image_np.shape[1], y2), (0, 255, 0), 2)

            # 创建debug目录（如果不存在）
            os.makedirs('debug', exist_ok=True)

            # 保存调试图片
            cv2.imwrite(save_path, debug_image)
            logger.info(f"调试图片已保存至: {save_path}")

        # --- 步骤6: 返回裁剪后的图像数据 ---
        return cropped_image

    def detect_amount_process(self, image_np: np.ndarray,columns:int= 4, width:int=150, dx = 205,number_height = 30,
                              test:bool=False) -> np.ndarray|None:
        """
        输入柱子图片，把数量截取，并合并返回一个大图片

        Args:
            image_np: 输入的柱子图片
            columns:  要识别的柱子数量
            width:    价格宽度
            dx:       柱子间隔
            number_height: 找到横线后，往上截取的价格高度。
            test:     是否保存结果

        Returns:
            返回截取的价格图片，如果没有则返回 None
        """
        total_h, total_w, _ = image_np.shape
        detected_prices = []
        for i in range(columns):
            current_x = i*dx
            is_first = i == 0
            # 1. 裁剪出当前的垂直柱状图
            pillar_image = image_np[:, current_x: current_x + width]
            # 2. 对这个柱状图调用我们的价格区域检测函数
            if test:
                price_area = self.detect_amount(pillar_image,first=is_first,number_height = number_height,
                                                save_path=f'debug/detect_price{i}.png')
            else:
                price_area = self.detect_amount(pillar_image,first=is_first,number_height = number_height)
            # 3. 如果成功检测到，就将其存入列表
            if price_area is not None:
                # price_area = self.preprocess_image(price_area,enable_cropping = False)  # 每个图片单独预处理
                price_area = self.preprocess_image(price_area,scale_factor=(3,5),erosion_kernel_size=2,enable_cropping = True)  # 每个图片单独预处理,只识别一个价格的花可以裁剪
                detected_prices.append(price_area)
            else:
                logger.warning("未能探测到柱子上的价格")

        # 拼接所有图片
        if detected_prices:
            combined_image = cv2.vconcat(detected_prices)   # 垂直方向拼接
            cv2.imwrite('debug//combined_image.png',combined_image)
            return combined_image
        else:
            return None

    @timing_decorator("识别稳定帧耗时: {duration:.3f} s", logger.info)
    def capture_stable_frame(self,
                             region_coords: tuple,
                             max_duration_s: float = 1.0,
                             fps: int = 30,
                             initial_diff_thresh: float = 5.0,
                             stable_diff_thresh: float = 1.0,
                             min_stable_frames: int = 1,
                             check_for_green: bool = True,  # 是否检查绿色文本作为提前成功信号
                             green_threshold : int = 30,    # 绿色像素点阈值
                             only_check_for_green: bool = False,    # 是否只检测绿色文本
                             save_all_frames: bool = False,
                             save_folder: str = 'debug'
                             ) -> tuple[str, np.ndarray | None]:
        """
        捕捉指定区域，直到找到稳定帧、检测到绿色文本或超时。
        内部处理捕捉、帧保存、绿色检测和稳定性判断。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)
            max_duration_s: 最长捕捉时间
            fps: 截图帧率
            initial_diff_thresh:初始变化阈值
            stable_diff_thresh: 稳定判断阈值
            min_stable_frames:  最小稳定帧数
            check_for_green: 是否启用绿色文本提前退出
            green_threshold: 绿色像素点阈值
            only_check_for_green: 是否只检测绿色文本，不检测稳定帧
            save_all_frames: 是否保存所有捕捉到的帧
            save_folder: 保存帧的文件夹

        Returns:
            一个元组 (status, frame_or_none):
            - status (str): 描述退出原因: "STABLE", "GREEN_FOUND", "TIMEOUT_STABLE", "TIMEOUT_UNSTABLE", "NO_FRAMES", "ERROR"
            - frame_or_none (np.ndarray | None): 如果 status 是 "STABLE" 或 "TIMEOUT_STABLE"，则为找到的稳定帧 (BGR)，否则为 None。
        """
        # 0. 防呆设计：处理参数冲突
        if only_check_for_green and not check_for_green:    # 防止空转
            check_for_green = True

        # 1. 初始化
        interval = 1.0 / fps
        start_time = time.perf_counter()
        frame_count = 0

        # 稳定性状态变量
        baseline_gray = None    # 初始帧
        last_frame_gray = None  # 最新帧灰度图
        potential_start_detected = False
        stable_streak:int = 0       # 连续稳定的帧数
        last_potential_stable_frame = None  # 记录最后一个可能是稳定的帧

        # --- 创建保存文件夹 ---
        if save_all_frames:
            try:
                os.makedirs(save_folder, exist_ok=True)
                logger.info(f"将保存所有帧到 '{os.path.abspath(save_folder)}'")
            except OSError as e:
                logger.warning(f"无法创建文件夹 '{save_folder}': {e}. 禁用帧保存。")
                save_all_frames = False

        logger.info(f"开始捕捉与等待稳定，最长 {max_duration_s:.2f} 秒...")
        while time.perf_counter() - start_time < max_duration_s:
            loop_start = time.perf_counter()

            # --- 1. 捕捉图像 ---
            try:
                frame_bgr = self.capture_region(region_coords)
                if frame_bgr is None or frame_bgr.size == 0:
                    time.sleep(0.02)
                    continue
            except Exception as e:
                logger.error(f"捕捉帧 {frame_count + 1} 时异常: {e}", exc_info=True)
                time.sleep(0.02)
                continue
            frame_count += 1

            # --- 保存帧 (如果启用) ---
            if save_all_frames:
                save_path = os.path.join(save_folder, f"frame_{frame_count:04d}.png")
                try:
                    cv2.imwrite(save_path, frame_bgr)
                except Exception as e:
                    logger.warning(f"保存帧 {frame_count} 到 '{save_path}' 失败: {e}")

            # --- 2. 检查绿色文本 (如果启用) ---
            if check_for_green:
                try:
                    has_green, _ = self.has_green(frame_bgr,green_threshold)
                    if has_green:
                        logger.info(f"在第 {frame_count} 帧检测到绿色文本，提前成功退出。")
                        return "GREEN_FOUND", None  # 返回绿色信号（不返回照片了，没有用）
                except Exception as e:
                    logger.error(f"检查绿色文本时异常: {e}", exc_info=True)

            # --- 3. 稳定性判断 ---
            if not only_check_for_green:
                try:
                    current_frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)    # 转为灰度图
                    if baseline_gray is None:  # 捕获第一帧
                        baseline_gray = current_frame_gray
                        last_frame_gray = current_frame_gray
                    else:
                        if not potential_start_detected:  # 检测初始变化
                            # ----- 计算两张图之间的差异 -----
                            diff_base = cv2.absdiff(baseline_gray, current_frame_gray)
                            mean_diff_base = cv2.mean(diff_base)[0]
                            # ----- 只有这一帧与初始帧不同，才开始计算稳定帧 -----
                            if mean_diff_base > initial_diff_thresh:
                                logger.info(f"帧 {frame_count}: 检测到初始变化 (差异: {mean_diff_base:.2f})")
                                potential_start_detected = True
                                stable_streak = 0
                                last_potential_stable_frame = frame_bgr  # 记录这个刚变化的帧

                        if potential_start_detected:  # 检测帧间稳定
                            diff_inter = cv2.absdiff(last_frame_gray, current_frame_gray)
                            mean_diff_inter = cv2.mean(diff_inter)[0]
                            # ----- 差异很小，稳定帧计数 +1 -----
                            if mean_diff_inter < stable_diff_thresh:
                                stable_streak += 1
                                last_potential_stable_frame = frame_bgr  # 更新为当前更稳定的帧
                                if stable_streak >= min_stable_frames:
                                    logger.info(f"帧 {frame_count}: 达到稳定状态 ({stable_streak} 帧相似)，退出。")
                                    return "STABLE", frame_bgr  # 返回稳定状态和稳定帧

                            # ----- 不稳定，重置计数 -----
                            else:
                                stable_streak = 0
                                last_potential_stable_frame = frame_bgr  # 记录这个刚变化的帧
                        last_frame_gray = current_frame_gray  # 更新上一帧
                except Exception as e:
                    logger.error(f"处理或判断帧 {frame_count} 稳定性时异常: {e}", exc_info=True)
                    # 如果判断出错，最好不要继续依赖这个状态
                    return "ERROR", None

            # --- 4. 控制帧率 ---
            elapsed = time.perf_counter() - loop_start
            sleep_time = interval - elapsed
            if sleep_time > 0: time.sleep(sleep_time)

        # --- 超时处理 ---
        logger.info(f"捕捉超时 (总帧数: {frame_count})。")
        if frame_count == 0:
            return "NO_FRAMES", None
        if potential_start_detected:
            # 检测到变化但未稳定，返回最后一个可能是稳定的帧
            logger.warning("超时，曾检测到变化但未能确认稳定。返回最后候选帧。")
            return "TIMEOUT_STABLE", last_potential_stable_frame  # 返回超时但有候选帧的状态
        else:
            logger.info("超时，且未检测到显著变化。")
            return "TIMEOUT_UNSTABLE", None  # 返回超时且未变化的状态

    @staticmethod
    def _crop_icon_by_contour(image_np: np.ndarray, extra_margin: int = 2) -> np.ndarray | None:
        """
        使用轮廓检测，智能地找到并移除最左侧的图标。
        这种方法对于亮色图标和深色背景的图像非常有效。

        Args:
            image_np: 要移除图标得图片
            extra_margin:裁剪后额外补充得白色边界厚度

        Returns:
            object: 移除图标后得图片
        """
        try:
            gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                logger.warning("轮廓分割辅助函数: 未找到任何轮廓。")
                return None

            leftmost_contour = min(contours, key=lambda c: cv2.boundingRect(c)[0])
            x, y, w, h = cv2.boundingRect(leftmost_contour)
            crop_start_x = x + w + extra_margin

            if crop_start_x >= image_np.shape[1]:
                logger.warning("轮廓分割辅助函数: 计算的裁剪点超出图像宽度。")
                return None

            return image_np[:, crop_start_x:]
        except Exception as e:
            logger.error(f"轮廓分割辅助函数: 分割时发生意外错误: {e}", exc_info=True)
            return None

    def preprocess_image(self,
                         image_np: np.ndarray,
                         scale_factor: float|tuple[float, float] = 5.0,
                         output_mode: Literal["binary", "gray"] = "gray",
                         remove_icon: bool = False,
                         border_size: int = 10,
                         enable_normalize: bool = True,
                         median_blur: bool = True,
                         median_blur_ksize: int = 3,
                         sharp:bool = False,
                         erosion_kernel_size: int = 0,
                         enable_cropping: bool = True,
                         padding: int = 10,
                         threshold_method: Literal["otsu", "adaptive", "none"] = "otsu",
                         ) -> np.ndarray | None:
        """
        图像预处理方法，耗时大概 1-5ms
        流程：灰度 -> 放大 -> normalize -> median blur -> 反相二值化(OTSU) -> 可选腐蚀 -> 可选裁边。
        Args:
            image_np: 输入图像 (BGR 格式)。
            scale_factor: 放大倍数。
            output_mode: 输出模式：
                - "binary": 返回反相二值图（OCR 常用）；
                - "gray": 返回灰度图。

            remove_icon: 是否启用智能分割来移除左侧图标。
            border_size: 移除图标后，在左侧添加的隔离带宽度。
            enable_normalize: 是否在放大后执行灰度归一化（0~255 拉伸）。
            median_blur: 是否进行中值滤波去噪。
            median_blur_ksize: 中值滤波核大小，必须为正奇数。仅在`median_blur=True` 时生效。
            sharp: 是否锐化增加对比度。
            erosion_kernel_size: 腐蚀核大小。如果大于0，则执行腐蚀以细化笔画。
            enable_cropping: 是否启用最终的白边美化裁剪。
            padding: 如果启动裁剪，则最终裁剪时在内容边界周围保留的像素边距。
            threshold_method: 二值化方式：
                - "otsu": 使用全局 OTSU 阈值；
                - "adaptive": 使用自适应高斯阈值；
                - "none": 不执行二值化，仅适用于 `output_mode="gray"`。


        Returns:
            处理后的图像。如果处理失败，返回 None。
            - 当 `output_mode="binary"` 时，返回单通道二值图；
            - 当 `output_mode="gray"` 时，返回单通道灰度图。
        """
        # --- 参数校验 ---
        if isinstance(scale_factor, (list, tuple)):
            if len(scale_factor) != 2:
                raise ValueError("当 scale_factor 为序列时，必须是 (fx, fy)")
            fx = float(scale_factor[0])
            fy = float(scale_factor[1])
        else:
            fx = float(scale_factor)
            fy = float(scale_factor)

        # 创建输入图像的一个副本，以避免在原始图像上直接修改。
        image_to_process = image_np.copy()

        # --- 步骤A: (可选) 智能分割移除图标 ---
        if remove_icon:
            # logger.info("启用基于轮廓的智能分割流程...")
            # 直接调用新的辅助方法，它会返回裁剪后的图像或None
            numbers_only_image = self._crop_icon_by_contour(image_np)

            if numbers_only_image is not None:
                if border_size > 0:
                    # 如果需要添加左侧隔离带 (这部分逻辑保持不变)
                    h, w, _ = image_np.shape
                    corner_size = 5
                    corners = np.concatenate([
                        image_np[0:corner_size, 0:corner_size].reshape(-1, 3),
                        image_np[0:corner_size, w - corner_size:w].reshape(-1, 3),
                        image_np[h - corner_size:h, 0:corner_size].reshape(-1, 3),
                        image_np[h - corner_size:h, w - corner_size:w].reshape(-1, 3)
                    ])
                    background_color = np.mean(corners, axis=0).astype(int).tolist()

                    image_to_process = cv2.copyMakeBorder(
                        numbers_only_image, 0, 0, border_size, 0,
                        cv2.BORDER_CONSTANT, value=background_color
                    )
                else:
                    # 如果不需要添加隔离带，则直接使用裁剪后的图像。
                    image_to_process = numbers_only_image
            else:
                # 如果找不到分割线或裁剪失败...
                logger.warning("智能分割失败，将继续处理整张图片。")

        try:
            # --- 步骤 B: 转灰度 ---
            if len(image_to_process.shape) == 3:
                # 如果图像是彩色的（有3个通道），则将其转换为灰度图。
                gray = cv2.cvtColor(image_to_process, cv2.COLOR_BGR2GRAY)
            else:
                # 如果图像已经是单通道的，则直接使用。
                gray = image_to_process

            if gray.shape[0] == 0 or gray.shape[1] == 0:
                # 检查图像的尺寸是否有效，防止因裁剪等操作导致图像变空。
                logger.warning("待处理图像尺寸无效，处理中止。")
                return None

            # --- 步骤 C: 使用 cv2.resize 将图像放大 ---
            # interpolation=cv2.INTER_CUBIC 是一种高质量的插值算法，能更好地保留细节。
            gray_scaled = cv2.resize(gray, None, fx=fx, fy=fy, interpolation=cv2.INTER_CUBIC)

            # --- 步骤 D: 归一化（可选） ---
            # 使用 cv2.normalize 将图像的灰度值线性拉伸到0-255的完整范围，以增强对比度。
            if enable_normalize:
                gray_scaled = cv2.normalize(gray_scaled, None, 0, 255, cv2.NORM_MINMAX)

            # --- 步骤 E1: 锐化 ---
            if sharp:
                kernel = np.array([[-0.2, -1, -0.2],
                                   [-1, 6.0, -1],
                                   [-0.2, -1, -0.2]])
                gray_sharped = cv2.filter2D(gray_scaled, -1, kernel)
                gray_sharped = cv2.GaussianBlur(gray_sharped, (3, 3), 0)
            else:
                gray_sharped = gray_scaled

            # --- 步骤 E2: 中值滤波（可选） ---
            if median_blur:
                # 使用中值滤波去除图像中的“椒盐”噪声，平滑图像。
                gray_processed = cv2.medianBlur(gray_sharped, ksize=median_blur_ksize)
            else:
                # 如果不启用模糊，则直接使用上一步的结果。
                gray_processed = gray_sharped

            # --- 步骤 F: 根据输出模式决定是否二值化 ---
            if output_mode == "gray":
                result_image = gray_processed
            else:
                if threshold_method == "otsu":
                    # 使用 cv2.threshold 进行二值化，将灰度图转换为 "白底黑字" 的图像。
                    # cv2.THRESH_OTSU 是一种自动阈值算法，它会分析图像的灰度直方图来找到最佳的全局阈值。
                    _, result_image = cv2.threshold(gray_processed, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                    # logger.debug("应用了OTSU全局阈值。")
                elif threshold_method == "adaptive":
                    # blockSize 必须为奇数，且通常不小于 3。
                    result_image = cv2.adaptiveThreshold(
                        gray_processed,
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY_INV,
                        11,
                        2,
                    )
                else:
                    # 这里理论上不会进入，因为前面已经做了参数校验。
                    raise ValueError(f"未知的 threshold_method: {threshold_method}")

                # 腐蚀只对二值图有意义；灰度图不做腐蚀。
                if erosion_kernel_size > 0:
                    # 创建一个指定大小的正方形结构元素（核），用于形态学操作。
                    kernel = np.ones((erosion_kernel_size, erosion_kernel_size), np.uint8)
                    # 执行腐蚀操作，它会“侵蚀”掉白色区域的边界，使文字笔画变细。
                    result_image = cv2.dilate(result_image, kernel, iterations=1)

            # --- 步骤 G: 最终裁边（可选） ---
            if enable_cropping:
                # - 如果当前输出就是二值图，直接使用；
                if output_mode == "binary":
                    crop_base = result_image
                # - 如果当前输出是灰度图，则临时做一次 OTSU 反相二值化，仅用于裁边，不影响返回类型。
                else:
                    _, crop_base = cv2.threshold(gray_processed,0,255,cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,)

                # 如果启用最终的白边裁剪...
                # 使用 cv2.bitwise_not 将黑白图像反转（黑变白，白变黑）。
                crop_base_inv = cv2.bitwise_not(crop_base)
                # 使用 cv2.findNonZero 找到所有非零（白色）像素的坐标，即找到所有文字内容的位置。
                coords = cv2.findNonZero(crop_base_inv)
                if coords is None:
                    # 如果找不到任何内容...
                    # logger.warning("最终裁剪时未检测到内容，返回未裁剪的二值图。")
                    return result_image

                # 使用 cv2.boundingRect 计算能刚好包围所有内容点的最小矩形。
                # 返回 x, y, 宽度, 高度。
                x, y, w, h = cv2.boundingRect(coords)

                # 在计算出的边界框基础上，向外扩展指定的 padding 值，以在内容周围留出一些空白。
                y_start = max(0, y - padding)
                x_start = max(0, x - padding)
                y_end = min(result_image.shape[0], y + h + padding)
                x_end = min(result_image.shape[1], x + w + padding)

                # 使用NumPy切片操作，根据计算出的新边界，从二值图中裁剪出最终的图像。
                cropped_thresh = result_image[y_start:y_end, x_start:x_end]

                if cropped_thresh.size > 0:
                    # 如果裁剪后的图像不为空...
                    # logger.debug(f"图像已最终裁剪至尺寸: {cropped_thresh.shape}")
                    return cropped_thresh
                else:
                    # 如果裁剪结果为空，则返回裁剪前的图像。
                    logger.warning("最终裁剪后图像尺寸无效，返回未裁剪的二值图。")
                    return result_image
            else:
                # 如果不启用裁剪，则直接返回经过所有处理的二值图。
                return result_image

        except cv2.error as e:
            logger.error(f"OpenCV处理错误: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"preprocess_image: 发生未预料的错误: {e}", exc_info=True)
            return None

    @staticmethod
    def _detect_color_presence(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                               color_name: str,
                               lower_bound: np.ndarray,
                               upper_bound: np.ndarray,
                               threshold: int,
                               verbose: bool) -> tuple[bool, int]:
        """
        颜色检测函数

        Args:
            image_np: 输入的BGR格式图像，如果输入 (x,y,w,h)，则先截图再检测。
            color_name: 颜色的名称（用于日志记录）。
            lower_bound: HSV颜色范围的下限。
            upper_bound: HSV颜色范围的上限。
            threshold: 像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到颜色, 检测到的像素数量)
        """
        try:
            # ----- 预处理 -----
            # 0. 兼容 XYWH 输入：如果不是 ndarray，就按截图区域处理
            if isinstance(image_np, np.ndarray):
                target_img = image_np
            elif isinstance(image_np, Sequence) and len(image_np) == 4:
                x, y, w, h = map(int, image_np)
                if w <= 0 or h <= 0:
                    raise ValueError(f"截图区域宽高必须大于 0，当前为: {(x, y, w, h)}")
                target_img = ImageProcessor.capture_region(x, y, w, h)
            else:
                raise ValueError(
                    "image_np 必须是 BGR 图像 np.ndarray，或包含 4 个整数的截图区域 (x, y, w, h)"
                )
            # -----------------

            # 1. 将图像从BGR转换为HSV颜色空间
            hsv = cv2.cvtColor(target_img, cv2.COLOR_BGR2HSV)

            # 2. 创建一个只保留指定颜色区域的蒙版(mask)
            mask = cv2.inRange(hsv, lower_bound, upper_bound)

            # 3. 计算蒙版中非零像素（即目标颜色像素）的数量
            pixel_count = cv2.countNonZero(mask)

            if verbose:
                # 如果启用详细模式，打印出检测到的像素数和占比
                total_pixels = target_img.shape[0] * target_img.shape[1]
                ratio = pixel_count / max(total_pixels, 1) * 100
                logger.info(f"{color_name}像素数：{pixel_count}，占比：{ratio:.2f}%")

            # 4. 判断像素数是否超过设定的阈值
            return pixel_count >= threshold, pixel_count

        except cv2.error as e:
            logger.error(f"检测{color_name}时发生OpenCV错误: {e}")
            return False, 0
        except Exception as e:
            logger.error(f"检测{color_name}时发生未知错误: {e}")
            return False, 0

    @staticmethod
    def has_green(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                  threshold: int = 30,
                  verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含绿色（通过HSV阈值检测）。

        Args:
            image_np: numpy.ndarray，BGR图像。
            threshold: 绿色像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到绿色, 绿色像素数量)
        """
        lower_green = np.array([40, 50, 50])
        upper_green = np.array([85, 255, 255])
        return ImageProcessor._detect_color_presence(
            image_np, "绿色", lower_green, upper_green, threshold, verbose)

    @staticmethod
    def has_yellow(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                   threshold: int = 50,
                   verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含黄色（通过HSV阈值检测）。

        Args:
            image_np: 输入的BGR格式图像。
            threshold: 黄色像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到黄色, 黄色像素数量)
        """
        lower_yellow = np.array([20, 100, 100])
        upper_yellow = np.array([35, 255, 255])
        return ImageProcessor._detect_color_presence(
            image_np, "黄色", lower_yellow, upper_yellow, threshold, verbose)

    @staticmethod
    def has_gray(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                 threshold: int = 50,
                 verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含灰色（通过HSV阈值检测）。

        Args:
            image_np: 输入的BGR格式图像。
            threshold: 灰色像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到灰色, 灰色像素数量)
        """
        lower_gray = np.array([0, 0, 60])
        upper_gray = np.array([179, 50, 200])
        return ImageProcessor._detect_color_presence(
            image_np, "灰色", lower_gray, upper_gray, threshold, verbose)

    @staticmethod
    def has_white(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                  threshold: int = 50,
                  verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含白色（通过HSV阈值检测）。

        Args:
            image_np: 输入的BGR格式图像。
            threshold: 白色像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到白色, 白色像素数量)
        """
        lower_white = np.array([0, 0, 140])
        upper_white = np.array([179, 35, 255])
        return ImageProcessor._detect_color_presence(
            image_np, "白色", lower_white, upper_white, threshold, verbose)

    @staticmethod
    def has_red(image_np: Union[np.ndarray, Tuple[int, int, int, int]],
                threshold: int = 50,
                verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含红色（通过HSV阈值检测）。

        Args:
            image_np: 输入的BGR格式图像。
            threshold: 红色像素数量阈值。
            verbose: 是否打印调试信息。

        Returns:
            (是否检测到红色, 红色像素数量)
        """
        # 定义红色的HSV范围
        lower_red = np.array([0, 160, 100])
        upper_red = np.array([8, 255, 255])
        return ImageProcessor._detect_color_presence(
            image_np, "红色", lower_red, upper_red, threshold, verbose)

    @staticmethod
    def wait_for_color(region_coords: tuple,
                       color_name: str,
                       delay: float=0.5,
                       timeout_s: float = 5.0,
                       threshold: int = 100,
                       fps: int = 10,
                       verbose: bool = False) -> bool:
        """
        持续检测指定区域，直到目标颜色出现或超时。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            color_name: 要检测的颜色名称，支持：
                - "green" / "绿色"
                - "yellow" / "黄色"
                - "gray"  / "灰色"
                - "white" / "白色"
                - "red" / "红色"
            delay: 首次捕捉前的等待时间。
            timeout_s: 最大等待时间（秒）。
            threshold: 颜色像素数量阈值。
            fps: 检测频率（每秒检测次数）。
            verbose: 是否打印调试信息。

        Returns:
            bool: 在超时时间内检测到目标颜色返回 True，否则返回 False。
        """
        # 0. 输入校验
        if len(region_coords) != 4:
            raise ValueError("输入坐标必须包含 4 个整数 (x, y, w, h)")

        rx, ry, rw, rh = region_coords
        if rw <= 0 or rh <= 0:
            raise ValueError("区域宽高必须大于 0")

        # 1. 颜色检测函数映射
        color_map = {
            "green": ImageProcessor.has_green,
            "绿色": ImageProcessor.has_green,

            "yellow": ImageProcessor.has_yellow,
            "黄色": ImageProcessor.has_yellow,

            "gray": ImageProcessor.has_gray,
            "灰色": ImageProcessor.has_gray,

            "white": ImageProcessor.has_white,
            "白色": ImageProcessor.has_white,

            "red": ImageProcessor.has_red,
            "红色": ImageProcessor.has_red,
        }

        # 确定检测函数
        detect_func = color_map.get(color_name.lower())
        if detect_func is None:
            raise ValueError(
                f"不支持的颜色类型: {color_name}。"
                f"可选值为: green/绿色, yellow/黄色, gray/灰色, white/白色, red/红色"
            )

        # 2. 开始等待循环
        time.sleep(delay)   # 在开始捕捉前等一会
        start_time = time.perf_counter()
        interval = 1.0 / fps

        logger.info(
            f"开始等待颜色 [{color_name}] 出现，最长等待 {timeout_s} 秒 "
            f"(threshold={threshold}, FPS={fps})..."
        )

        while time.perf_counter() - start_time < timeout_s:
            loop_start = time.perf_counter()

            # 截图
            target_img = ImageProcessor.capture_region(region_coords)
            if target_img is None or target_img.size == 0:
                time.sleep(0.02)
                continue

            # 颜色检测
            detected, pixel_count = detect_func(
                target_img,
                threshold=threshold,
                verbose=verbose,
            )

            if detected:
                logger.info(
                    f"检测到颜色 [{color_name}]，像素数={pixel_count}，区域={region_coords}"
                )
                return True

            # 帧率控制
            elapsed_loop = time.perf_counter() - loop_start
            sleep_time = interval - elapsed_loop
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.warning(
            f"等待颜色 [{color_name}] 超时 ({timeout_s} 秒未出现)，区域={region_coords}"
        )
        return False

    @staticmethod
    def has_bright_spot(image_np: np.ndarray,
                        spot_threshold: int = 5,
                        brightness_threshold: int = 35,
                        verbose: bool = False) -> tuple[bool, int]:
        """
        判断图像中是否包含亮斑（通过灰度图和亮度阈值检测）。
        此方法更通用，适用于检测任何比背景明显亮的非彩色区域（如灰色光点）。

        Args:
            image_np: 输入 BGR 格式图像。
            spot_threshold: 亮点像素数量阈值，超过则判定为检测到。
            brightness_threshold: ,灰度亮度阈值 (0-255)，高于此值的像素才会被计为“亮点”。
            verbose: bool,默认 False,是否输出调试信息。

        Returns:
            tuple[bool, int]:
                - 第 1 个元素：是否检测到亮斑 (True / False)
                - 第 2 个元素：检测到的亮点像素数量
        """
        try:
            # 1. BGR → Grayscale
            gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)

            # 2. 应用亮度阈值生成蒙版
            _, mask = cv2.threshold(gray, brightness_threshold, 255, cv2.THRESH_BINARY)

            # 3. 统计亮点像素
            bright_pixels = cv2.countNonZero(mask)

            if verbose:
                total_pixels = image_np.shape[0] * image_np.shape[1]
                bright_ratio = bright_pixels / total_pixels * 100
                logger.info(
                    f"[灰度图方法] 亮点素数(Gray>{brightness_threshold})：{bright_pixels}，占比：{bright_ratio:.2f}%")

            # 4. 阈值判定
            return bright_pixels >= spot_threshold, bright_pixels

        except cv2.error as e:
            logger.error(f"检测亮斑时发生 OpenCV 错误: {e}")
            return False, 0
        except Exception as e:
            logger.error(f"检测亮斑时发生未知错误: {e}")
            return False, 0

    @timing_decorator("监控亮斑消失总耗时: {duration:.3f} s", logger.info)
    def wait_and_detect_spot_disappearance(self,
                                           region_coords: tuple,
                                           wait_duration_s: float,
                                           max_capture_duration_s: float = 5.0,
                                           fps: int = 10,
                                           spot_threshold: int = 50,
                                           brightness_threshold: int = 60,
                                           ) -> tuple[str, np.ndarray | None]:
        """
        特化版本：等待指定时间后，监控区域直到亮斑出现后又消失。
        工作流程:
        1. 沉睡 `wait_duration_s` 秒。
        2. 开始以 `fps` 频率捕捉 `region_coords` 区域，持续最多 `max_capture_duration_s` 秒。
        3. 如果连续2次未检测到亮斑，则认为亮斑从未出现，提前失败退出。
        4. 如果检测到亮斑，则进入“监控消失”状态。
        5. 在“监控消失”状态下，一旦首次检测到亮斑消失，则成功退出。
        6. 如果在 `max_capture_duration_s` 内亮斑一直存在未消失，则超时失败退出。

        Args:
            region_coords (tuple): 截图区域坐标 (top, left, width, height)。
            wait_duration_s (float): 初始等待的秒数。
            max_capture_duration_s (float): 捕捉循环的最大持续时间（不包括初始等待）。
            fps (int): 捕捉和检测的频率。
            spot_threshold (int): 传递给 has_bright_spot 的像素数量阈值。
            brightness_threshold (int): 传递给 has_bright_spot 的亮度阈值。

        Returns:
            tuple[str, np.ndarray | None]:
            - status (str):
                - "SPOT_DISAPPEARED": 成功，亮斑出现后消失。
                - "NO_SPOT_FOUND": 失败，连续2次未找到亮斑或超时前从未找到。
                - "TIMEOUT_WHILE_PRESENT": 失败，亮斑一直存在直到超时。
                - "ERROR": 捕捉或处理时发生异常。
            - frame_or_none (np.ndarray | None): 成功时返回亮斑消失后的第一帧，否则为 None。
        """
        # --- 1. 初始沉睡 ---
        if wait_duration_s > 0:
            logger.info(f"开始初始等待 {wait_duration_s:.2f} 秒...")
            time.sleep(wait_duration_s)

        # --- 2. 准备捕捉循环 ---
        logger.info(f"等待结束，开始捕捉区域并监控亮斑。最长持续 {max_capture_duration_s:.2f} 秒...")
        start_capture_time = time.perf_counter()
        interval = 1.0 / fps

        spot_was_ever_detected = False
        consecutive_misses = 0

        while time.perf_counter() - start_capture_time < max_capture_duration_s:
            loop_start = time.perf_counter()

            # --- 捕捉与检测 ---
            try:
                frame_bgr = self.capture_region(region_coords)
                if frame_bgr is None or frame_bgr.size == 0:
                    time.sleep(0.02)
                    continue

                spot_found, pixel_count = self.has_bright_spot(frame_bgr, spot_threshold, brightness_threshold)

            except Exception as e:
                logger.error(f"捕捉或检测时发生异常: {e}", exc_info=True)
                return "ERROR", None

            # --- 核心逻辑判断 ---
            if spot_found:
                if not spot_was_ever_detected:
                    logger.info(f"首次检测到亮斑 (像素数: {pixel_count})。现在开始监控其消失...")
                    spot_was_ever_detected = True
                consecutive_misses = 0 # 重置连续失败计数
            else: # 未检测到亮斑
                if spot_was_ever_detected:
                    logger.info("亮斑已消失，任务成功完成。")
                    return "SPOT_DISAPPEARED", frame_bgr # 成功条件达成
                else:
                    consecutive_misses += 1
                    logger.info(f"未检测到亮斑 (连续第 {consecutive_misses} 次)。")
                    if consecutive_misses >= 2:
                        logger.warning("连续 2 次未检测到亮斑，提前退出。")
                        return "NO_SPOT_FOUND", None # 提前失败条件
            # --- 控制帧率 ---
            elapsed = time.perf_counter() - loop_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        # --- 3. 超时处理 ---
        logger.warning(f"监控超时 ({max_capture_duration_s:.2f} 秒)。")
        if spot_was_ever_detected:
            # 超时时，亮斑还存在
            logger.error("超时失败：亮斑在规定时间内未消失。")
            return "TIMEOUT_WHILE_PRESENT", None
        else:
            # 超时时，亮斑从未出现
            logger.error("超时失败：在规定时间内未检测到亮斑。")
            return "NO_SPOT_FOUND", None

class TemplateRecognizer:
    """
    基于模板匹配 + NMS 的高速价格识别器。
    右上角余额/右下角购买数量/配装购买价格 可以精确识别
    """
    def __init__(self, template_dir:str=None,
                 detection_threshold:float= 0.8,
                 overlap_thresh:float= 0.25,
                 use_color: bool = False,
                 test:bool=False):
        """
        初始化识别器，加载模板。

        Args:
            template_dir: 存放 0-9 模板图片的文件夹路径（可选）。
            detection_threshold: 匹配相似度阈值,任何低于这个分数的匹配都会被直接忽略
            overlap_thresh: 重叠抑制阈值,如果某个框与最高分框的重叠率超过了 overlap_thresh，就把它删掉
            use_color: 是否开启彩色匹配。True 则使用 BGR 三通道，False 则转为灰度。
            test: 是否启动测试模式
        """
        # ----- 读取输入参数 -----
        self.test = test
        if self.test:
            self.debug_dir = "debug/template_matching"
            os.makedirs(self.debug_dir, exist_ok=True)
            logger.info(f"测试模式已启用，调试图像将保存至: {self.debug_dir}")

        self.detection_threshold = detection_threshold  # 匹配相似度阈值
        self.overlap_thresh = overlap_thresh    # 重叠抑制阈值
        self.use_color:bool = use_color         # 色彩模式

        # ----- 初始化其他配件 -----
        self.image_processor = ImageProcessor()
        self._custom_tpl_cache:dict[tuple[str, bool],np.ndarray] = {}     # 缓存图片的字典

        # 预处理字典
        self.preprocess_params = {
            'gaussian_ksize': (3, 3),   # 高斯模糊核大小
            'adaptive_block_size': 11,  # 自适应阈值块大小
            'adaptive_c': 5,            # 从均值或高斯加权均值中减去的常数
            'scale_factor': 3.0,        # 图片放大倍数，不建议超过5
        }

        # ----- 加载数字模板（可选） -----
        if template_dir:
            self.templates = self._load_templates(template_dir)

            if not self.templates:
                logger.error(f"模板文件夹 '{template_dir}' 为空或无法加载任何模板，识别器无法工作。")
                raise ValueError(f"模板文件夹 '{template_dir}' 为空或无法加载。")

            logger.info(f"初始化完成，加载了 {len(self.templates)} 个模板。")

    def _load_templates(self, template_dir: str) -> dict:
        """
        加载 0-9 的数字模板，并应用统一的预处理。

        Args:
            template_dir: 模板图片存放得文件夹路径
        """
        templates = {}  # 存放 照片名称:照片

        h_max ,w_max = 0,0  # 模板的最大高宽

        for digit in range(10):
            filepath = os.path.join(template_dir, f"{digit}.png")
            if not os.path.exists(filepath):continue

            # 以彩色模式读取，以防原始模板是灰度的
            template_img = cv2.imread(filepath, cv2.IMREAD_COLOR)
            if template_img is None:continue

            # 应用与运行时完全相同的预处理流程
            preprocessed_template = self._preprocess_for_matching(template_img, self.preprocess_params)

            templates[str(digit)] = {
                'img':preprocessed_template,
                'h':preprocessed_template.shape[0],
                'w':preprocessed_template.shape[1],
            }

            h_max = max(h_max, preprocessed_template.shape[0])
            w_max = max(w_max, preprocessed_template.shape[1])

            if self.test:
                save_path = os.path.join(self.debug_dir, f"template_{digit}_processed.png")
                cv2.imwrite(save_path, preprocessed_template)
                logger.info(f"已保存预处理后的模板: {save_path}")

        self.tpl_h = h_max  # 记录模板高
        self.tpl_w = w_max  # 记录模板宽

        return templates

    @staticmethod
    def _preprocess_for_matching(image: np.ndarray, params: dict) -> np.ndarray:
        """
        为模板匹配执行统一的图像预处理。
        流程: 灰度化 -> 高斯模糊 -> 自适应阈值化 -> 放大图片。
            实际使用时发现除了 灰度和放大之外 的操作都会导致匹配不上，因此取消了
        Args:
            image: 要进行预处理得图片（BGR），可以是彩图或灰度图
            params: 预处理参数

        Returns:
            object: 预处理后得图片
        """
        # 1. 将图片转为灰度图
        if len(image.shape) == 3:
            preprocessed_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            preprocessed_image = image

        # 2. 高质量放大
        scale_factor = params['scale_factor']  # 放大倍数，2倍或3倍通常效果很好

        if scale_factor != 1.0:
            width = int(preprocessed_image.shape[1] * scale_factor)
            height = int(preprocessed_image.shape[0] * scale_factor)
            # 使用高质量的插值算法，INTER_CUBIC 或 INTER_LANCZOS4 是很好的选择
            preprocessed_image = cv2.resize(preprocessed_image, (width, height), interpolation=cv2.INTER_CUBIC)

        return preprocessed_image

    # 识别速度已经到 几ms了，不需要再优化
    @timing_decorator("模板匹配耗时: {duration:.3f} s", logger.info)
    def recognize_number(self, image: np.ndarray) -> tuple[str, float]:
        """
        识别图像中的价格数字。

        Args:
            image: 输入图像 (可以是 BGR 彩色图或灰度图)。

        Returns:
            tuple[str, float]:
                - str: 识别到的数字字符串。
                - float: 所有识别出的数字的平均匹配得分 (作为置信度)。
        """
        if image is None or image.size == 0:
            logger.warning("模板匹配识别器收到空图像。")
            return "", 0.0

        if self.test:
            # 使用时间戳确保文件名唯一，方便多次调试
            timestamp = int(time.time() * 1000)
            save_path = os.path.join(self.debug_dir, f"live_image_{timestamp}.png")
            cv2.imwrite(save_path, image)

        # 1. 预处理
        processed_image = self._preprocess_for_matching(image, self.preprocess_params)
        img_h, img_w = processed_image.shape

        if self.tpl_h > img_h or self.tpl_w > img_w:
            logger.error("输入图像尺寸小于模板尺寸！")
            return "", 0.0

        # 准备数据容器 (为了喂给 cv2.dnn.NMSBoxes)
        boxes_list = []      # [x, y, w, h]
        scores_list = []     # float
        class_ids_list = []  # str ('0', '1'...)

        # 2. 全局搜索所有模板
        for digit_char, tpl_data in self.templates.items():
            template_img = tpl_data['img']

            res = cv2.matchTemplate(processed_image, template_img, cv2.TM_CCOEFF_NORMED)    # 模板匹配，找出得分
            ys, xs = np.where(res >= self.detection_threshold)

            count = len(xs)
            if count == 0:continue

            # 直接提取分数
            scores = res[ys, xs]
            w, h = tpl_data['w'], tpl_data['h']
            current_boxes = np.column_stack((xs, ys, np.full(count, w), np.full(count, h)))
            # current_boxes 格式是：[ [x, y, w, h], [x, y, w, h], ... ]
            # array([
            #     [100, 50, 10, 20],  # 第1个匹配点 (x=100, y=50, 宽10, 高20)
            #     [101, 50, 10, 20],  # 第2个匹配点 (就在第1个旁边，可能是重复识别)
            #     [200, 80, 10, 20]   # 第3个匹配点 (在比较远的地方)
            # ])

            # 加入总表
            boxes_list.extend(current_boxes.tolist())
            scores_list.extend(scores.tolist())
            class_ids_list.extend([digit_char] * count)

        if not boxes_list:  # 如果一个框都没找到，直接返回
            logger.info("模板匹配：未找到任何候选匹配项。")
            return "", 0.0

        # 3. 应用非极大值抑制(NMS)
        # indices 返回所有 有效的索引
        indices = cv2.dnn.NMSBoxes(boxes_list, scores_list, self.detection_threshold, self.overlap_thresh)

        if len(indices) == 0:
            logger.info("模板匹配：NMS后无有效数字。")
            return "", 0.0

        # 4. 整理最终结果
        indices = indices.flatten()

        final_results = []
        for i in indices:
            final_results.append({
                'x': boxes_list[i][0],
                'digit': class_ids_list[i],
                'score': scores_list[i]
            })

        # 按 x 坐标从左到右排序
        final_results.sort(key=lambda x: x['x'])
        # print(final_results)
        # 拼接结果
        price_str = "".join([item['digit'] for item in final_results])
        # 计算平均置信度
        mean_conf = sum(item['score'] for item in final_results) / len(final_results)

        logger.info(f"======== 模板匹配识别为: {price_str} (平均置信度: {mean_conf:.3f}) ========")

        return price_str, mean_conf

    @timing_decorator("模板匹配识别总耗时: {duration:.3f} s", logger.info)
    def recognize_price(self, region_coords: tuple) -> tuple[int,float]:
        """
        识别价格

        Args:
            region_coords: 识别区域的 (x,y,w,h)

        Returns:
            (价格数字,置信度)
        """
        screen = self.image_processor.capture_region(region_coords)
        # 识别图像中的数字，不需要预处理
        price, confidence = self.recognize_number(screen)

        if price and confidence:
            return int(price), confidence
        else:
            return 0, 0.0

    @timing_decorator("等待价格识别耗时: {duration:.3f} s", logger.info)
    def recognize_price_wait(self,
                             region_coords: tuple,
                             timeout_s: float = 5.0,
                             fps: int = 20,) -> tuple[str, float]:
        """
        在指定时间内持续尝试识别区域内的价格数字，直到成功识别或超时。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            timeout_s: 最大等待超时时间（秒）。
            fps: 每秒识别频率。

        Returns:
            tuple[str, float]:
                - str: 识别出的价格字符串，超时未识别到则返回空字符串 ""。
                - float: 平均匹配得分（置信度）。
        """
        # 0. 参数校验
        if len(region_coords) != 4:
            raise ValueError("输入坐标必须包含 4 个整数 (x, y, w, h)")

        start_time = time.perf_counter()
        interval = 1.0 / fps

        logger.info(f"开始监控区域价格文字出现，最长等待 {timeout_s} 秒 (FPS: {fps})...")

        while time.perf_counter() - start_time < timeout_s:
            loop_start = time.perf_counter()

            # 1. 截图目标区域
            target_img = self.image_processor.capture_region(region_coords)
            if target_img is None or target_img.size == 0:
                time.sleep(0.003)
                continue

            # 2. 调用核心识别方法
            # 注意：recognize_number 内部已经包含了预处理和 NMS 逻辑
            price_str, confidence = self.recognize_number(target_img)

            # 3. 检查结果：如果识别到字符且置信度达标，则立即返回
            if price_str and confidence >= self.detection_threshold:
                logger.info(f"价格识别成功: '{price_str}' (置信度: {confidence:.3f})")
                return price_str, confidence

            # 4. 控制频率
            elapsed_loop = time.perf_counter() - loop_start
            sleep_time = interval - elapsed_loop
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.warning(f"等待价格识别超时 ({timeout_s} 秒未识别到有效内容)。")
        return "", 0.0

    def _get_or_load_template(self, template_path: str, use_color: bool=False) -> np.ndarray | None:
        """
        内部辅助方法：获取模板。
        如果缓存中没有，则从磁盘读取并存入缓存（仅存 1 倍率的 灰色/彩色 图片）。

        Args:
            template_path: 模板路径
            use_color: 是否存储彩色图

        Returns:
            根据选择的模式，返回 彩色/灰色图
        """
        cache_key = (template_path, use_color)  # 记录模板路径和彩色模式，当作字典的 key

        # 1. 如果命中缓存，直接返回
        if cache_key in self._custom_tpl_cache:
            return self._custom_tpl_cache[cache_key]

        # 2. 未命中缓存，从磁盘读取
        if not os.path.exists(template_path):
            logger.error(f"模板图片不存在: {template_path}")
            return None

        # 3. 根据需求处理并存入缓存
        if use_color:
            final_tpl = self.image_processor.load_image(template_path, mode='bgr')
        else:
            final_tpl = self.image_processor.load_image(template_path, mode='gray')

        if final_tpl is None:
            logger.error(f"无法读取模板图片: {template_path}")
            return None

        self._custom_tpl_cache[cache_key] = final_tpl

        logger.debug(f"已载入模板缓存 [模式:{'彩色' if use_color else '灰度'}]: {template_path}")
        return final_tpl

    @staticmethod
    def _prepare_scaled_templates(tpl_img: np.ndarray,
                                  max_rw: int,
                                  max_rh: int,
                                  multi_scale: bool) -> list[tuple[np.ndarray,int,int,float]]:
        """
        内部辅助方法：预先生成所有合法的缩放模板。

        Args:
            tpl_img: 模板图。
            max_rw: 搜索区域的宽度。
            max_rh: 搜索区域的高度。
            multi_scale: 是否开启多尺度。

        Returns:
            list: 包含元组的列表 [(resized_tpl, w, h, scale), ...]
        """
        scales = [1.0]
        if multi_scale:
            # 生成 5 个缩放级别：0.8, 0.9, 1.0, 1.1, 1.2
            scales = np.linspace(0.8, 1.2, 5)

        scaled_results = []
        for scale in scales:
            # 1. 计算缩放后的理论尺寸
            resized_w:int = int(tpl_img.shape[1] * scale)
            resized_h:int = int(tpl_img.shape[0] * scale)

            # 2. 越界防御：如果尺寸非法，或者比目标截图区域还大，直接跳过
            if (resized_w <= 0 or resized_h <= 0 or
                    resized_w > max_rw or resized_h > max_rh):
                continue

            # 3. 执行缩放或直接引用
            if scale == 1.0:
                scaled_results.append((tpl_img, resized_w, resized_h, 1.0))
            else:
                interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                resized_tpl = cv2.resize(tpl_img, (resized_w, resized_h), interpolation=interpolation)
                scaled_results.append((resized_tpl, resized_w, resized_h, scale))

        return scaled_results

    @staticmethod
    def _do_multi_match(target_img: np.ndarray,
                        scaled_templates: list,
                        threshold: float) -> tuple[tuple[int, int], int, int, float] | None:
        """
        在 target_gray 中匹配列表里的所有模板，返回最高分的匹配结果。

        Args:
            target_img: 要进行匹配的图片
            scaled_templates: 预先生成的列表，元素为 (tpl_img, w, h, scale)
            threshold: 匹配的阈值
        Returns:
            (max_loc, w, h, max_val) 或 None
            返回值格式：( (左上角x, 左上角y(相对截图区域)), 匹配模板宽, 匹配模板高, 相似度得分 )
        """
        best_val = -1.0
        best_res = None

        for current_tpl, current_w, current_h, current_scale in scaled_templates:
            # 不需要越界检查，在 _prepare_scaled_templates 已经检查过了

            res = cv2.matchTemplate(target_img, current_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_val:
                best_val = max_val
                best_res = (max_loc, current_w, current_h, max_val)

        if best_val >= threshold:
            return best_res
        return None

    # @timing_decorator("查找模板中心点耗时: {duration:.3f} s", logger.info)
    def find_center(self,
                    region_coords: tuple,
                    template_path: str,
                    threshold: float = 0.8,
                    multi_scale: bool = False,
                    use_color: bool = False,) -> Optional[tuple[int, int]]:
        """
        在屏幕指定区域内查找特定模板图片，如果存在则返回其在屏幕上的绝对中心坐标。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            template_path: 待查找的模板图片绝对或相对路径。
            threshold: 匹配相似度阈值 (0.0 - 1.0)。
            multi_scale: 可选开关。如果为 True，将在 0.8 倍到 1.2 倍之间缩放模板进行多次匹配，以应对大小差异。
            use_color: 是否使用彩色匹配。对于形状相同但颜色不同的图标，应设为 True。

        Returns:
            tuple[int, int]: 匹配成功返回目标在全屏下的绝对中心坐标 (x, y)；失败返回 None。
        """

        # 1. 统一通过缓存方法获取模板灰度图
        tpl_img = self._get_or_load_template(template_path, use_color=use_color)
        if tpl_img is None:return None

        # 2. 解析坐标并截取目标区域
        if len(region_coords) != 4:
            raise ValueError("输入坐标必须包含 4 个整数 (x, y, w, h)")

        rx, ry, rw, rh = region_coords
        target_img = self.image_processor.capture_region(region_coords)     # 截图目标区域
        if target_img is None or target_img.size == 0:return None

        # 3. 处理截图区域：如果模式是灰度，则转灰度；如果是彩色，保持 BGR
        if not use_color:
            target_to_match = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
        else:
            target_to_match = target_img

        # 3. 生成要比较的模板
        scaled_templates = self._prepare_scaled_templates(tpl_img, rw, rh, multi_scale)

        # 4. 进行多模板匹配
        match_res = self._do_multi_match(target_to_match, scaled_templates, threshold)

        # 5. 返回结果与后处理
        if match_res:
            max_loc, w, h, score = match_res  # 解包返回值

            if self.test:   # 画出结果
                mode_str = "color" if use_color else "gray"
                tpl_name = os.path.basename(template_path).split('.')[0]
                filename = f"{mode_str}_{tpl_name}_{score:.2f}.png"
                save_path = os.path.join(self.debug_dir, filename)
                self.image_processor.draw_and_save_debug(target_img, max_loc, w, h, save_path)

            return (rx + max_loc[0] + w // 2, ry + max_loc[1] + h // 2)
        else:
            return None

    # @timing_decorator("查找模板中心点耗时: {duration:.3f} s", logger.info)
    def find_center_on_image(self,
                             target_img: np.ndarray,
                             template_path: str,
                             threshold: float = 0.8,
                             multi_scale: bool = False,
                             use_color: bool = False,) -> Optional[tuple[int, int, float]]:
        """
        在已有的图像数组中查找特定模板。
        Args:
            target_img: 要寻找得图片内容（灰度图）。
            template_path: 待查找的模板图片绝对或相对路径。
            threshold: 匹配相似度阈值 (0.0 - 1.0)。
            multi_scale: 可选开关。如果为 True，将在 0.8 倍到 1.2 倍之间缩放模板进行多次匹配，以应对大小差异。
            use_color: 是否使用彩色匹配。对于形状相同但颜色不同的图标，应设为 True。

        Returns:
            tuple[int, int]: 匹配成功返回目标在全屏下的绝对中心坐标 (x, y)；失败返回 None。
        """
        if target_img is None or target_img.size == 0:    # 检查图片
            return None

        # 1. 获取模板灰度图
        tpl_img = self._get_or_load_template(template_path, use_color=use_color)
        if tpl_img is None: return None

        # 2. 处理目标图色彩维度
        if use_color:
            target_to_match = target_img  # 保持 BGR
        else:
            target_to_match = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY) # 转灰度

        th, tw = target_to_match.shape[:2]

        # 3. 准备多尺度模板
        scaled_templates = self._prepare_scaled_templates(tpl_img, tw, th, multi_scale)

        # 4. 执行匹配
        match_res = self._do_multi_match(target_to_match, scaled_templates, threshold)

        if match_res:
            max_loc, w, h, score = match_res

            if self.test:   # 画结果图
                mode_str = "color" if use_color else "gray"
                tpl_name = os.path.basename(template_path).split('.')[0]
                filename = f"{mode_str}_{tpl_name}_{score:.2f}.png"
                save_path = os.path.join(self.debug_dir, filename)
                self.image_processor.draw_and_save_debug(target_img, max_loc, w, h, save_path)

            # 返回相对于这张图左上角的中心点坐标
            return (max_loc[0] + w // 2, max_loc[1] + h // 2, score)
        return None

    def exists_template(self,
                        region_coords: tuple,
                        template_path: str,
                        threshold: float = 0.8,
                        multi_scale: bool = False,
                        use_color: bool = False,) -> bool:
        """
        判断屏幕指定区域内是否存在特定模板图片。
        当区域大小为 500x500 时，大概耗时 10ms
        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            template_path: 待查找的模板图片绝对或相对路径。
            threshold: 匹配相似度阈值 (0.0 - 1.0)。
            multi_scale: 可选开关。如果为 True，将缩放模板进行多次匹配。
            use_color: 是否使用彩色匹配。对于形状相同但颜色不同的图标，应设为 True。

        Returns:
            bool: 存在返回 True，否则返回 False。
        """
        # 直接调用找坐标的方法，如果返回值不是 None 说明找到了
        return self.find_center(region_coords, template_path, threshold, multi_scale, use_color) is not None

    @timing_decorator("等待模板出现耗时: {duration:.3f} s", logger.info)
    def wait_for_template(self,
                          region_coords: tuple,
                          template_path: str,
                          timeout_s: float = 5.0,
                          threshold: float = 0.8,
                          fps: int = 8,
                          multi_scale: bool = False,
                          use_color: bool = False,) -> tuple[int, int] | None:
        """
        持续检测指定区域，直到目标模板出现或超时。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            template_path: 待查找的模板图片绝对或相对路径。
            timeout_s: 最大等待超时时间（秒）。
            threshold: 匹配相似度阈值 (0.0 - 1.0)。
            fps: 检测频率（每秒检测次数）。
            multi_scale: 是否开启多尺度匹配。
            use_color: 是否使用彩色匹配。对于形状相同但颜色不同的图标，应设为 True。

        Returns:
            tuple[int, int] | None: 在超时时间内出现返回绝对中心坐标 (x, y)，超时未出现返回 None。
        """
        # 0. 输入检验 与 解析坐标
        if len(region_coords) != 4:
            raise ValueError("输入坐标必须包含 4 个整数 (x, y, w, h)")
        rx, ry, rw, rh = region_coords

        # 1. 统一通过缓存方法获取模板灰度图
        tpl_img = self._get_or_load_template(template_path, use_color=use_color)
        if tpl_img is None:return None

        # 2. 生成要比较的模板
        scaled_templates = self._prepare_scaled_templates(tpl_img, rw, rh, multi_scale)

        # 3. 开始等待循环
        start_time = time.perf_counter()
        interval = 1.0 / fps
        tpl_name = os.path.basename(template_path)

        logger.info(f"开始等待模板 [{tpl_name}] 出现，最长等待 {timeout_s} 秒 (FPS: {fps})...")

        while time.perf_counter() - start_time < timeout_s:
            loop_start = time.perf_counter()

            # 截屏并处理
            target_img = self.image_processor.capture_region(region_coords)
            # 如果没抓到图则休息一会
            if target_img is None or target_img.size == 0:
                time.sleep(0.02)
                continue

            # 处理色彩维度
            target_to_match = target_img if use_color else cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)

            # 遍历预计算的模板进行匹配
            match_res = self._do_multi_match(target_to_match, scaled_templates, threshold)

            if match_res:
                max_loc, w, h, score = match_res  # 解包返回值

                if self.test:  # 画出结果
                    mode_str = "color" if use_color else "gray"
                    tpl_name = os.path.basename(template_path).split('.')[0]
                    filename = f"wait_{mode_str}_{tpl_name}_{score:.2f}.png"
                    save_path = os.path.join(self.debug_dir, filename)
                    self.image_processor.draw_and_save_debug(target_img, max_loc, w, h, save_path)

                return (rx + max_loc[0] + w // 2, ry + max_loc[1] + h // 2)
            else:
                # 帧率控制
                elapsed_loop = time.perf_counter() - loop_start
                sleep_time = interval - elapsed_loop
                if sleep_time > 0:
                    time.sleep(sleep_time)

        logger.warning(f"等待模板 [{tpl_name}] 超时 ({timeout_s} 秒未出现)。")
        return None