# ocr_recognizer

# ----- 导入官方库 -----
import os
import logging
import time
import re
from typing import Optional

# ----- 导入三方库 -----
import cv2
import numpy as np
from paddleocr import PaddleOCR     # V2.10.0

# ----- 导入自用库 -----
from template_recognizer import ImageProcessor
from basic_tools import timing_decorator
from nhc import PHashRecognizer

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

__version__ = "1.0.4"
__update__ = "2026.07.28"

class OcrRecognizer:
    """
    用 ocr 方法来识别数字+文本 （这里用的 paddleocr）
    注：paddleocr 的版本为 2.10.0。3.X 版本不支持

    待解决：
    paddleocr没法跨线程使用，因此每次启动任务都要重新初始化ocr组件，
    会卡1-3s，原因在这里
    """
    def __init__(self, test = False) -> None:
        """
        初始化识别器，加载中文和英文识别引擎。
        Args:
            test: 是否启动测试模式
        """
        self.test = test
        if self.test:
            self.debug_dir = "./debug"
            os.makedirs(self.debug_dir, exist_ok=True)
            logger.info(f"测试模式已启用，调试图像将保存至: {self.debug_dir}")

        self.image_processor = ImageProcessor()
        # --- 加载中文OCR引擎 ---
        self.ocr_engine_ch = PaddleOCR(
            det_model_dir='./inference/det/ch',  # 检测模型所在文件夹
            rec_model_dir='./inference/rec/ch',  # 识别模型所在文件夹。
            cls_model_dir='./inference/cls/ch',  # 分类模型所在文件夹。
            use_angle_cls=False,
            lang='ch',
            show_log=False
        )

        # --- 加载英文OCR引擎 ---
        self.ocr_engine_en = PaddleOCR(
            det_model_dir='./inference/det/en',  # 检测模型所在文件夹
            # rec_model_dir='./inference/rec/en',# 识别模型所在文件夹。
            rec_model_dir='./inference/en_PP-OCRv3_rec_slim_infer',  # 识别模型所在文件夹。
            cls_model_dir='./inference/cls/en',  # 分类模型所在文件夹。
            use_angle_cls=False,
            det=False,
            lang='en',
            show_log=False,
            det_db_thresh=0.25,         # 尝试降低概率图阈值
            det_db_box_thresh=0.40,     # 尝试降低边界框阈值
            det_db_unclip_ratio=3.5,    # 尝试增大框的放大比例
        )

    @timing_decorator("价格 OCR 耗时: {duration:.3f} s",logger.info)
    def recognize_number(self, image_np: np.ndarray) -> tuple[str, float]:
        """
        使用 PaddleOCR 识别图像中的数字。

        Args:
            image_np: 输入图像 (二值化)。
        Returns:
            str: 识别到的数字字符串。
        """
        if self.ocr_engine_en is None:
            logger.error("OCR 引擎未初始化，无法识别数字。")
            return "", 0.0

        if image_np is None or image_np.size == 0:
            logger.warning("识别数字收到空图像。")
            return "", 0.0

        if image_np.ndim != 2: # 输入图像应为单通道二值图
            raise ValueError("recognize_number 需要单通道二值图")

        number_confidence_threshold:float = 0.7   # 置信度
        try:
            ocr_results = self.ocr_engine_en.ocr(image_np, cls=False)

            if not ocr_results or not ocr_results[0]:
                logger.info("PaddleOCR 未返回任何识别结果。")
                return "", 0.0

            # ----- 保存结果图 -----
            if self.test:
                save_path = f"{self.debug_dir}/price_box.png"
                self.draw_ocr_debug(image_np, ocr_results, save_path)

            # 遍历处理每个检测到的文本行/框
            text_all = ''
            confidence_list = []
            for line_info in ocr_results[0]:
                # line_info:  [框,(文本,置信度)]
                # 检查 line_info 结构是否符合预期
                if line_info is None or len(line_info) != 2 or len(line_info[1]) != 2:
                    logger.warning(f"跳过格式无效的 OCR 结果行: {line_info}")
                    continue
                text, confidence = line_info[1]
                if confidence < number_confidence_threshold:
                    continue
                else:
                    text_all += text
                    confidence_list.append(confidence)

            if len(text_all) > 0 and len(confidence_list) > 0:
                numbers = ''.join(re.findall(r'\d+',text_all))
                mean_confidence = sum(confidence_list) / len(confidence_list)
                logger.info(f"======== 价格识别为: {numbers} (置信度: {mean_confidence:.3f}) ========")
                return numbers, mean_confidence
            else:
                return "", 0.0

        except Exception as e:
            # 捕获并记录 OCR 或后续处理中可能发生的任何异常
            logger.error(f"识别数字过程中发生错误: {e}", exc_info=True)
            return "", 0.0

    def recognize_price(self,
                        region_coords: tuple,
                        enable_cropping: bool = True,
                        remove_icon: bool = False) -> tuple[int, float]:
        """
        识别指定截图区域的价格，返回数字和置信度

        Args:
            region_coords: 识别区域的 (x,y,w,h)
            enable_cropping: 在识别前是否需要裁剪
            remove_icon: 是否去除标签

        Returns:
            (价格数字,置信度)
        """
        # 1. 获取图像
        screen = self.image_processor.capture_region(region_coords)

        # 2. 复用底层图像识别逻辑
        return self.recognize_price_img(
            image_np=screen,
            remove_icon=remove_icon,
            enable_cropping=enable_cropping,
        )

    @timing_decorator("价格识别总耗时: {duration:.3f} s", logger.info)
    def recognize_price_img(self,
                        image_np: np.ndarray,
                        enable_cropping: bool = True,
                        remove_icon: bool = False) -> tuple[int, float]:
        """
        识别指定截图区域的价格，返回数字和置信度

        Args:
            image_np: 输入的图像 (建议为 BGR 彩色图或灰度图)。
            enable_cropping: 在识别前是否需要裁剪
            remove_icon: 是否去除标签

        Returns:
            (价格数字,置信度)
        """
        # 1.预处理图像，使其更容易被OCR识别
        processed = self.image_processor.preprocess_image(image_np,
                                                          enable_cropping=enable_cropping,
                                                          remove_icon=remove_icon)
        if self.test:
            cv2.imwrite(f'{self.debug_dir}/price_image.png', image_np)  # 保存原图

        # 2.识别图像中的数字
        price, confidence = self.recognize_number(processed)

        if price and confidence:
            return int(price), confidence
        else:
            return 0, 0.0

    @timing_decorator("购买 OCR 耗时: {duration:.3f} s", logger.info)
    def recognize_text(self, image_np: np.ndarray, need_preprocess: bool = False) -> tuple[str, float]:
        """
        使用 PaddleOCR 识别图像中的文本。
        在测试模式下，会绘制检测框并保存可视化图像。

        Args:
            image_np: 输入的图像 (建议为 BGR 彩色图或灰度图)。
            need_preprocess: 是否需要对图片进行预处理。

        Returns:
            tuple[str, float]: (识别出的文本, 平均置信度)。
        """
        if self.ocr_engine_ch is None:
            logger.error("OCR 引擎未初始化，无法识别文本。")
            return "", 0.0

        if image_np is None or image_np.size == 0:
            logger.warning("识别文本收到空图像。")
            return "", 0.0

        # 预处理步骤
        if need_preprocess:
            image_np = self.image_processor.preprocess_image(image_np)
            logger.info("图像预处理已启用。")

        if self.test and need_preprocess:
            cv2.imwrite(f'{self.debug_dir}/text_image_processed.png', image_np)  # 保存为 PNG 格式
        try:
            # 首先执行OCR，获取结果
            ocr_results = self.ocr_engine_ch.ocr(image_np, cls=False)

            # ----- 保存结果图 -----
            if self.test:
                save_path = f"{self.debug_dir}/text_boxes.png"
                self.draw_ocr_debug(image_np, ocr_results, save_path)

            # --- 可视化结束，继续执行原有的识别和排序逻辑 ---
            if not ocr_results or not ocr_results[0]:
                logger.info("PaddleOCR 未返回任何识别结果。")
                return "", 0.0

            # 1. 收集所有通过置信度阈值的文本块
            valid_lines = []
            confidence_threshold = 0.7  # 您可以根据需要调整此阈值
            for line_info in ocr_results[0]:
                if line_info and len(line_info) == 2 and len(line_info[1]) == 2:
                    box, (text, confidence) = line_info
                    if confidence >= confidence_threshold:
                        valid_lines.append([box, text, confidence])
                else:
                    logger.warning(f"跳过格式无效的 OCR 结果行: {line_info}")

            if not valid_lines:
                logger.info("没有识别结果超过置信度阈值。")
                return "", 0.0

            # 2. 根据文本框的左上角 x 坐标进行排序
            # item[0] 是框坐标列表, item[0][0] 是左上角点 [x, y], item[0][0][0] 是 x 坐标
            sorted_lines = sorted(valid_lines, key=lambda item: item[0][0][0])

            # 3. 拼接排序后的文本，并计算平均置信度
            text_parts = [line[1] for line in sorted_lines]
            confidence_list = [line[2] for line in sorted_lines]

            # 使用单个空格连接文本部分，更通用
            final_text = ' '.join(text_parts)
            mean_confidence = sum(confidence_list) / len(confidence_list)

            logger.info(f"======== 文本识别为: '{final_text}' (平均置信度: {mean_confidence:.3f}) ========")
            return final_text, mean_confidence

        except Exception as e:
            logger.error(f"OCR 识别过程中发生异常: {e}", exc_info=True)
            return "", 0.0

    @timing_decorator("多个价格识别总耗时: {duration:.3f} s", logger.info)
    def recognize_muti_price(self,image: np.ndarray,orientation:str = 'h') -> list:
        """从左到右或者从上到下，识别一个图片里的多个价格"""
        if self.ocr_engine_en is None:
            logger.error("OCR 引擎未初始化，无法识别数字。")
            return []
        if image is None or image.size == 0:
            logger.warning("识别数字收到空图像。")
            return []

        if image.ndim != 2: # 输入图像应为单通道二值图
            raise ValueError("recognize_muti_price 需要单通道二值图")

        number_confidence_threshold = 0.55   # 置信度
        try:
            ocr_results = self.ocr_engine_en.ocr(image, cls=False)

            if not ocr_results or not ocr_results[0]:
                logger.info("PaddleOCR 未返回任何识别结果。")
                return []

            # ocr_results = sorted(ocr_results, key=lambda item: item[0][0][0])   # 排序

            # ----- 保存结果图 -----
            if self.test:
                save_path = f"{self.debug_dir}/muti_price_box.png"
                self.draw_ocr_debug(image, ocr_results, save_path)

            # 遍历处理每个检测到的文本行/框
            price_list = []
            confidence_list = []
            if orientation == 'h':
                line_infos = sorted(ocr_results[0],key=lambda x:x[0][0][0]) # 排序
            else:
                line_infos = sorted(ocr_results[0],key=lambda x:x[0][0][1]) # 排序

            for line_info in line_infos:
                # line_info:  [框,(文本,置信度)]
                # 检查 line_info 结构是否符合预期
                if line_info is None or len(line_info) != 2 or len(line_info[1]) != 2:
                    logger.warning(f"跳过格式无效的 OCR 结果行: {line_info}")
                    continue
                text, confidence = line_info[1]
                if confidence < number_confidence_threshold:
                    continue
                else:
                    numbers = ''.join(re.findall(r'\d+', text))
                    price_list.append(int(numbers))
                    confidence_list.append(confidence)

        except Exception as e:
            # 捕获并记录 OCR 或后续处理中可能发生的任何异常
            logger.error(f"识别数字过程中发生错误: {e}", exc_info=True)
            return []

        if len(price_list) > 0:
            return price_list  # 返回置信度最高的结果
        else:
            return []

    @timing_decorator("查找文本位置耗时: {duration:.3f} s", logger.info)
    def find_text_center(self,
                         region_coords: tuple,
                         target_text: str,
                         threshold_confidence: float = 0.7) -> tuple[int, int] | None:
        """
        在指定区域查找是否存在特定文字。如果存在，返回该区域的中心坐标。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            target_text: 想要查找的文字（支持模糊匹配，只要识别结果包含该文字即可）。
            threshold_confidence: 置信度阈值，只有识别置信度高于此值才返回结果。

        Returns:
            tuple[int, int] | None: 找到则返回区域中心绝对坐标 (x, y)，否则返回 None。
        """
        # 1. 解析坐标并截取区域图
        if len(region_coords) != 4:
            raise ValueError("识别区域必须包含 4 个整数 (x, y, w, h)")
        rx, ry, rw, rh = region_coords

        target_img = self.image_processor.capture_region(region_coords)
        if target_img is None or target_img.size == 0:
            return None

        # 2. 执行 OCR 识别 (使用中文引擎)
        # 注意：这里直接使用原图识别，以获得最原始的坐标对应关系
        results = self.ocr_engine_ch.ocr(target_img, cls=False)

        # 3. 结果解析与目标查找
        if results and results[0]:
            for line in results[0]:
                box = line[0]  # 边框坐标: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = line[1][0]  # 识别出的文本内容
                confidence = line[1][1]  # 置信度

                # 4. 逻辑判断：包含目标文字且置信度达标
                if target_text in text and confidence >= threshold_confidence:

                    # 5. 计算文本块在截图内的局部中心点
                    # 通过计算 bounding box 四个顶点的平均值来获取几何中心
                    x_coords = [p[0] for p in box]
                    y_coords = [p[1] for p in box]
                    local_center_x = int(sum(x_coords) / 4)
                    local_center_y = int(sum(y_coords) / 4)

                    # 6. 转换为屏幕绝对坐标
                    abs_center_x = rx + local_center_x
                    abs_center_y = ry + local_center_y

                    # --- 测试模式：在图中画出精准位置 ---
                    if self.test:
                        debug_img = target_img.copy()
                        # 将 box 坐标转为 int 型的 pts 数组用于绘图
                        pts = np.array(box, np.int32).reshape((-1, 1, 2))
                        cv2.polylines(debug_img, [pts], True, (0, 255, 0), 2)  # 画绿框
                        cv2.circle(debug_img, (local_center_x, local_center_y), 5, (0, 0, 255), -1)  # 画红点

                        save_path = f"{self.debug_dir}/ocr_found_text.png"
                        cv2.imwrite(save_path, debug_img)
                        logger.info(
                            f"找到文本 '{target_text}', 置信度 {confidence:.3f}, 坐标 ({abs_center_x}, {abs_center_y})")

                    return (abs_center_x, abs_center_y)

        # logger.debug(f"未在指定区域内匹配到文字: '{target_text}'")
        return None

    @timing_decorator("循环等待文本耗时: {duration:.3f} s", logger.info)
    def wait_for_text(self,
                      region_coords: tuple,
                      target_text: str,
                      timeout_s: float = 5.0,
                      fps: int = 5,
                      threshold_confidence: float = 0.7,
                      change_threshold: float = 0.5) -> tuple[int, int] | None:
        """
        持续检测指定区域，直到目标文字出现或超时。

        Args:
            region_coords: 截图区域坐标 (x, y, w, h)。
            target_text: 想要查找的文字。
            timeout_s: 最大等待超时时间（秒）。
            fps: 检测频率。由于 OCR 比较耗 CPU，建议设置较低的 FPS（如 1 或 2）。
            threshold_confidence: 识别置信度阈值。
            change_threshold: 画面变化阈值。平均像素变化小于此值则认为画面静止。

        Returns:
            tuple[int, int] | None: 超时时间内找到则返回绝对中心坐标，超时则返回 None。
        """
        start_time = time.perf_counter()
        interval = 1.0 / fps
        last_frame_gray = None  # 用于存储上一帧的灰度图

        logger.info(f"开始等待文字 '{target_text}' 出现，最长等待 {timeout_s} 秒 (FPS: {fps})...")

        while time.perf_counter() - start_time < timeout_s:
            loop_start = time.perf_counter()

            # 1. 抓取当前帧并转灰度
            current_frame_bgr = self.image_processor.capture_region(region_coords)
            if current_frame_bgr is None or current_frame_bgr.size == 0:
                time.sleep(0.02)
                continue
            current_frame_gray = cv2.cvtColor(current_frame_bgr, cv2.COLOR_BGR2GRAY)

            # 2. 检查画面是否发生了变化
            is_changed = True
            if last_frame_gray is not None:
                # 计算两帧之间的绝对差异
                diff = cv2.absdiff(last_frame_gray, current_frame_gray)
                mean_diff = np.mean(diff)  # 算出一个平均差异值

                if mean_diff < change_threshold:
                    is_changed = False
                    logger.info(f"画面静止 (diff: {mean_diff:.4f})，跳过 OCR")

            # 3. 只有画面变了或者是第一帧，才进行 OCR
            if is_changed:
                # 注意：为了性能，我们可以直接把已经抓到的 current_frame_bgr 传给识别函数
                # 这里假设你重写一个支持传入 image_np 的方法，或者直接调用 OCR
                result = self.find_text_center(region_coords, target_text, threshold_confidence)
                if result is not None:
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"等待成功：文字 '{target_text}' 已找到，耗时 {elapsed:.2f} 秒。")
                    return result

            # 更新上一帧
            last_frame_gray = current_frame_gray

            # 4. 控制频率
            elapsed_loop = time.perf_counter() - loop_start
            sleep_time = interval - elapsed_loop
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.warning(f"等待文字 '{target_text}' 超时 ({timeout_s} 秒未找到)。")
        return None

    def draw_ocr_debug(self,
                       image_np: np.ndarray,
                       ocr_results: list,
                       save_path: str, )->None:
        """
        可视化辅助方法，把 ocr 识别到的检测框画出来。
        支持多边形绘制、单通道转彩色、以及中文路径保存。

        Args:
            image_np (np.ndarray): 输入图像（二值图、灰度图或 BGR）。
            ocr_results (list): PaddleOCR 返回的结果列表。
            save_path (str): 保存图片的完整路径。
        """
        try:
            # 1. 图像空间转换：确保在彩色空间绘制以显示绿色框
            if image_np.ndim == 2:
                vis_image = cv2.cvtColor(image_np, cv2.COLOR_GRAY2BGR)
            else:
                vis_image = image_np.copy()

            # 2. 提取并绘制所有检测框
            if ocr_results and ocr_results[0]:
                # PaddleOCR 的数据结构通常是 [ [ [box], (text, score) ], ... ]
                boxes = [line[0] for line in ocr_results[0] if line]

                draw_color = (0, 255, 0)  # 鲜绿色 BGR
                thickness = 3

                for box in boxes:
                    # 转换坐标点格式以适配 cv2.polylines
                    pts = np.array(box, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(vis_image, [pts], isClosed=True, color=draw_color, thickness=thickness)

            # 3. 使用支持中文路径的 save_image 方法
            success = self.image_processor.save_image(image_np=vis_image, image_path=save_path)

            if success and logger:
                logger.info(f"OCR 可视化结果已保存至: {save_path}")

        except Exception as e:
            if logger:
                logger.error(f"绘制或保存 OCR 可视化图像时出错: {e}", exc_info=True)

class DynamicOcrRecognizer:
    """
    一个动态、自学习的 ocr 识别器。

    结合了 pHash 缓存的快速查询能力和 OCR 的通用识别能力。
    查缓存的开销仅为 OCR 的 1%，因此大部分场景可以直接代替 OCR （即使不匹配也仅有 1%额外开销）
    - 对于见过的图像，  通过 pHash实现近乎瞬时的识别。
    - 对于未见过的图像，调用 OCR进行识别，并将高置信度的结果自动添加到缓存中，
    """
    def __init__(self, phash_cache: PHashRecognizer,
                 ocr_recognizer: OcrRecognizer,
                 ocr_confidence_threshold: float = 0.95,
                 valid_price: tuple[int, ...]= (-1,)):
        """
        初始化动态识别器。

        Args:
            phash_cache (PHashRecognizer): 一个已初始化的 pHash 缓存实例。
            ocr_recognizer (OcrRecognizer): 一个已初始化的 OCR 识别器实例。
            ocr_confidence_threshold (float): OCR识别结果可被信任并加入缓存的最低置信度。
            valid_price:一个用户指定的，可信任的价格序列（可选）
        """
        self.phash_cache = phash_cache
        self.ocr_recognizer = ocr_recognizer
        self.ocr_confidence_threshold = ocr_confidence_threshold
        self.image_processor = ImageProcessor()
        self.valid_price = valid_price

    def recognize_price(self, region_coords: tuple,remove_icon:bool=False) -> tuple[int, float]:
        """
        识别给定图像中的数字。“先查缓存，后用OCR”

        Args:
            region_coords: 识别区域的 (x,y,w,h)
            remove_icon: 是否去除标签

        Returns:
            - int: 识别出的数字字符串。如果识别失败则为 0。
            - float: 结果的置信度。
                 - 如果来自pHash缓存，置信度为 1.0。
                 - 如果来自OCR，则是OCR返回的原始置信度。
                 - 如果失败，为 0.0。
        """
        # 1.截图
        screen = self.image_processor.capture_region(region_coords)

        # 2.直接调用
        return self.recognize_price_img(screen, remove_icon=remove_icon)

    @timing_decorator("优化价格识别总耗时: {duration:.3f} s", logger.info)
    def recognize_price_img(self, image_np:np.ndarray,remove_icon:bool=False) -> tuple[int, float]:
        """
        识别给定图像中的数字。“先查缓存，后用OCR”

        Args:
            image_np: 输入的图像 (建议为 BGR 彩色图或灰度图)。
            remove_icon: 是否去除标签

        Returns:
            - int: 识别出的数字字符串。如果识别失败则为 0。
            - float: 结果的置信度。
                 - 如果来自pHash缓存，置信度为 1.0。
                 - 如果来自OCR，则是OCR返回的原始置信度。
                 - 如果失败，为 0.0。
        """
        screen = image_np

        # 1. 快速路径：查询pHash缓存
        cached = self.phash_cache.find(screen)
        if cached is not None:
            # 缓存命中，直接返回结果，置信度视为100%
            return cached, 1.0

        # 2. 慢速路径：缓存未命中，调用OCR
        logger.info("缓存未命中，启动OCR识别...")
        result, confidence = self.ocr_recognizer.recognize_price_img(screen,
                                                                     remove_icon=remove_icon)
        if result in self.valid_price:  # 如果价格在指定的范围里，则置信度为1
            confidence = 1

        # 3. 学习与缓存：根据置信度决定是否更新缓存
        if result and confidence >= self.ocr_confidence_threshold:
            logger.info(f"高置信度OCR结果 ('{result}', {confidence:.3f})，添加到pHash缓存。")
            # 注意：pHash缓存需要原始的BGR图像来计算哈希
            self.phash_cache.add(screen, result)
        elif result:
            logger.warning(f"低置信度OCR结果 ('{result}', {confidence:.3f})，不添加到缓存。")
        else:
            logger.info("DN_OCR 未能识别出任何数字。")
            return 0, 0.0  # OCR完全失败

        # 4. 返回本次OCR的识别结果
        return result, confidence

    @timing_decorator("优化文本识别总耗时: {duration:.3f} s", logger.info)
    def recognize_text(self, image_np: np.ndarray, need_preprocess: bool = False) -> tuple[str, float]:
        """
        识别给定图像中的文字。“先查缓存，后用OCR”

        Args:
            image_np: 输入的图像 (建议为 BGR 彩色图或灰度图)。
            need_preprocess: 是否需要对图片进行预处理。

        Returns:
            tuple[str, float]: (识别出的文本, 平均置信度)。
        """
        if image_np is None or image_np.size == 0:
            logger.warning("识别文本收到空图像。")
            return "", 0.0

        screen = image_np
        # 1. 快速路径：查询pHash缓存
        cached = self.phash_cache.find(screen)
        if cached is not None:
            # 缓存命中，直接返回结果，置信度视为100%
            return cached, 1.0

        # 2. 慢速路径：缓存未命中，调用OCR
        logger.info("缓存未命中，启动OCR识别...")
        result, confidence = self.ocr_recognizer.recognize_text(screen, need_preprocess)

        # 3. 学习与缓存：根据置信度决定是否更新缓存
        if result and confidence >= self.ocr_confidence_threshold:
            logger.info(f"高置信度OCR结果 ('{result}', {confidence:.3f})，添加到pHash缓存。")
            # 注意：pHash缓存需要原始的BGR图像来计算哈希
            self.phash_cache.add(screen, result)
        elif result:
            logger.warning(f"低置信度OCR结果 ('{result}', {confidence:.3f})，不添加到缓存。")
        else:
            logger.info("DN_OCR 未返回任何识别结果。")
            return "", 0.0

        # 4. 返回本次OCR的识别结果
        return result, confidence