# advanced_tools.py

"""
存放高级类
"""
# ----- 导入官方库 -----
import logging
import time
from typing import Optional, Tuple, Literal, Union, List

# ----- 导入三方库 -----
import cv2
import numpy as np

# ----- 导入自用库 -----
from window_operator import InputSimulator
from template_recognizer import TemplateRecognizer

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

__version__ = "1.0.2"
__update__ = "2026.07.28"

class VisualFeedbackController:
    """
    一个通过滑动鼠标滚轮，在屏幕上找指定内容得类
    """
    def __init__(self):

        self.rc:TemplateRecognizer = TemplateRecognizer()   # 模板匹配器

    def scroll_search(self,
                      search_region: Tuple[int,int,int,int],
                      template_path: Union[str, List[str]],
                      scroll_step: int = 3,
                      max_attempts: int = 100,
                      direction: Literal['up', 'down'] = 'down',
                      similarity_threshold: float = 0.95,
                      threshold:float = 0.8,
                      freq:int = 10,
                      use_color:bool = False)->Optional[Tuple[Tuple[int,int],int]]:
        """
        全自动滚动搜索：一直滚动直到找到目标或到达底部。

        Args:
            search_region: 截图和识别区域 (x, y, w, h)
            template_path: 目标图片（组）路径
            scroll_step: 每次截图前滚动的齿数 (1齿 = 120delta)，建议不超过 5
            max_attempts: 最大尝试次数，防止死循环
            direction: 'down' (向下滚) 或 'up'
            similarity_threshold: 判断画面是否一致的阈值 (0-1)，越高越严格
            threshold: 判断图片相同得阈值
            freq: 滑动得频率，建议不超过20。
            use_color: 是否使用彩色模式。

        Returns:
            (发现的坐标, total_notched_scrolled) 或 None
        """
        rx, ry, rw, rh = search_region  # 解析坐标
        total_notches:int = 0           # 记录转动了多少齿
        last_frame_gray:np.ndarray = None   # 最后一次截图得图片（灰度）
        consecutive_same_frames:int = 0     # 连续相同帧
        step_freq = 100      # 每次滑动后的休息时间
        delay:float = 1/freq - 1/step_freq  # 每次完成一轮后休息得时间
        if delay<=0:delay=0.01

        # 将输入统一转为列表处理
        if isinstance(template_path, str):
            templates = [template_path]
        else:
            templates = template_path

        logger.info(f"开始滚动搜索目标: {templates[0]}, 模板数： {len(templates)}")

        for i in range(max_attempts):
            # 1. 截图并获取当前画面
            current_frame = self.rc.image_processor.capture_region(search_region)

            # 2. 遍历所有模板进行匹配 (择优录取)
            best_match = None   # 分数最高的模板信息
            max_score = -1.0

            for tpl in templates:
                res = self.rc.find_center_on_image(current_frame, tpl,
                                                   threshold=threshold, use_color=use_color)
                if res:
                    local_x, local_y, score = res   # 相对坐标和相似度评分
                    # 记录得分最高的那个模板结果
                    if score > max_score:
                        max_score = score
                        best_match = (local_x, local_y, score, tpl)

            # 如果在当前帧找到了任意一个模板
            if best_match:
                lx, ly, score, hit_tpl = best_match
                abs_pos = (rx + lx, ry + ly)    # 目标中心在屏幕上的绝对坐标
                logger.info(f"命中目标！模板:{hit_tpl}, 位置:{abs_pos}, 得分:{score:.2f}, 滚动齿数:{total_notches}")
                return abs_pos, total_notches

            # 3. 画面一致性检查（判断是否到底）
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)  # 转化为灰度图
            if last_frame_gray is not None:
                # 计算两帧之间的差异
                # 使用模板匹配的相似度算法比对两张图
                res = cv2.matchTemplate(current_gray, last_frame_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)

                if max_val >= similarity_threshold:
                    consecutive_same_frames += 1
                    logger.info(f"检测到画面未发生变化 (相似度: {max_val:.4f}, 连续 {consecutive_same_frames} 次)")
                else:
                    consecutive_same_frames = 0  # 画面动了，重置计数

                # 如果连续 2 次画面几乎一样，判定到底
                if consecutive_same_frames >= 2:
                    logger.warning("滚动受阻或已到达尽头，停止搜索。")
                    return None

            # 4. 执行滚动
            # 更新上一帧
            last_frame_gray = current_gray

            # 调用鼠标滚动方法
            InputSimulator.mouse_scroll(clicks=scroll_step, direction=direction, freq=step_freq)
            total_notches += scroll_step

            # 【关键】等待 UI 渲染。给游戏引擎 0.3-0.5 秒时间完成滚动动画
            # 时间太短会导致截图时画面还在模糊晃动，影响识别。
            time.sleep(delay)

        logger.error(f"达到最大尝试次数 {max_attempts}，未找到目标。")
        return None

    # def drag_by_pixels_verified(self,
    #                             anchor_template: str,
    #                             search_region: tuple,
    #                             target_px: int,
    #                             direction: str = 'down'):
    #     """
    #     【视觉反馈闭环】精确控制滑动距离。
    #     :param anchor_template: 参考锚点的图片路径
    #     :param search_region: 锚点可能出现的区域 (x, y, w, h)
    #     :param target_px: 你想要画面移动的精确像素值
    #     :param direction: 'down' (向下拉，内容向上走) 或 'up'
    #     """
    #     logger.info(f"开始闭环滑动任务：目标距离 {target_px} 像素")
    #
    #     # 1. 寻找初始位置 (锚点)
    #     pos_start = self.rc.find_center(search_region, anchor_template, threshold=0.8)
    #     if not pos_start:
    #         logger.error("未找到初始锚点，闭环失败")
    #         return False
    #
    #     y_start = pos_start[1]
    #     logger.info(f"初始锚点位置: Y={y_start}")
    #
    #     # 2. 计算滑动的物理起点和终点 (初步尝试)
    #     # 注意：向下滑动 'down'，鼠标是从下往上拖，或者从上往下拖，取决于你的逻辑定义
    #     # 这里假设：'down' 是指把内容往下拽（鼠标从上往下移）
    #     drag_start = (search_region[0] + search_region[2] // 2, search_region[1] + search_region[3] // 2)
    #     offset = target_px if direction == 'down' else -target_px
    #     drag_end = (drag_start[0], drag_start[1] + offset)
    #
    #     # 3. 执行第一次物理滑动
    #     # 假设 InputSimulator 已经集成
    #
    #     InputSimulator.mouse_drag(drag_start[0], drag_start[1], drag_end[0], drag_end[1], duration=0.5)
    #
    #     # 给 UI 一点点惯性停止的时间
    #     time.sleep(0.3)
    #
    #     # 4. 滑动后再次寻找锚点
    #     pos_end = self.rc.find_center(search_region, anchor_template, threshold=0.7)
    #     if not pos_end:
    #         logger.warning("滑动后锚点丢失，尝试扩大范围寻找或返回结果")
    #         return False
    #
    #     y_end = pos_end[1]
    #     actual_move = y_end - y_start
    #     error = target_px - abs(actual_move)
    #
    #     logger.info(f"滑动结束。实际移动: {actual_move} px, 预期: {target_px} px, 误差: {error} px")
    #
    #     # 5. 【闭环补偿】如果误差超过 5 像素，进行微调
    #     if abs(error) > 5:
    #         logger.info(f"误差较大 ({error}px)，执行精准微调...")
    #         # 计算微调的起止点
    #         adjust_start = drag_start
    #         adjust_end = (drag_start[0], drag_start[1] + (target_px - actual_move))
    #         InputSimulator.mouse_drag(adjust_start[0], adjust_start[1], adjust_end[0], adjust_end[1], duration=0.3)
    #         return True
    #
    #     return True