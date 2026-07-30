# ----- 导入官方库 -----
import os
import ctypes
import functools
import random
import sys
import time
from collections import Counter
import re
import gc
import logging

# ----- 导入三方库 -----
import cv2
import numpy as np
import pyautogui
import pyperclip
from numpy import ndarray
from PyQt5.QtCore import QThread, pyqtSignal

# ----- 导入自用库 -----
from basic_tools import get_timestamp_ms, get_datetime, timing_decorator
from template_recognizer import ImageProcessor, TemplateRecognizer
from ocr_recognizer import OcrRecognizer, DynamicOcrRecognizer
from window_operator import WindowOperator, InputSimulator
from nhc import PHashRecognizer

logger = logging.getLogger(__name__)

__version__ = "1.0.1"
__update__ = "2026.04.25"

# ----- 常数定义 -----
# 快速点击
FAST_CLICK = {
    "delay":0.03,
    "hold_duration":0.02,
}
# 稳定点击
STABLE_CLICK = {
    "delay":0.1,
    "hold_duration":0.1,
}
# 连续
CONTINUE_CLICK = {
    "delay":0.00,
    "hold_duration":0.01,
}

BULLETS_SET:int = 200   # 一组子弹

class Worker(QThread):
    """
    工作线程类，用于执行耗时的自动化任务，避免阻塞主线程。
    """
    log_signal = pyqtSignal(str)    # 日志信号，用于向主线程发送日志消息
    save_log_signal = pyqtSignal()  # 保存日志信号
    finished_signal = pyqtSignal()  # 完成信号，用于通知主线程任务已完成
    restart_game_signal = pyqtSignal(int)    # 重启游戏信号，传递新绑定的hwnd

    def __init__(self, task_params: dict):
        """
        初始化工作线程。

        Args:
            task_params (dict): 从主UI传入的参数字典
        """
        super().__init__()
        # --- 解析传入的参数 ---
        # ============= 通用参数 ================
        self.task_params = task_params
        self.task_type = task_params["task_type"]
        self.op_large = task_params['op_large']
        self.op_small = task_params['op_small']
        self.flag = task_params['flag']
        self.test = task_params['test']
        self.auto_plan = task_params['auto_plan']
        self.coords_large = task_params["coords"]['large']     # 存储了大号所有需要的坐标
        self.coords_small = task_params["coords"]['small']     # 存储了小号所有需要的坐标
        self.coords_large_hoarding = task_params["coords"]['large_hoarding']  # 屯仓的大号

        self.image_processor = ImageProcessor()
        self.monitor_price = self.coords_large['monitor_price'] # 刷配装时候的价格监测位置
        self.buy_button_coord = self.coords_large['buy']        # 刷配装时候的购买位置
        self.monitor_text = self.coords_large['monitor_text']   # 刷配装时候的是否购买成功检测位置
        self.TARGET_KEYWORDS = ["胸挂", "口袋", "背包", "安全", "门禁"]
        self.auto_block_shit = 0        # 自动挡屎价
        self.auto_block_shit_list = [0]*10
        self.auto_block_shit_index = 0
        self.parent = task_params['parent']

        if self.test:
            # 测试模式的 logger 全打开
            loggers = [logging.getLogger(__name__), logging.getLogger('recognizer')]
            for logger_ in loggers:
                logger_.setLevel(logging.DEBUG)

        self.ocr = OcrRecognizer(test=self.test)  # ocr 引擎
        self.docr = DynamicOcrRecognizer(
            PHashRecognizer(),
            self.ocr,
            ocr_confidence_threshold = 0.9,
        )

        if getattr(sys, 'frozen', False):
            # 在 PyInstaller 打包后的环境中
            template_path_green = r'.\_internal\template\price_green'
            template_path_white = r'.\_internal\template\price_white'
        else:
            # 在正常开发环境中
            template_path_green = r'.\template\price_green'
            template_path_white = r'.\template\price_white'
        self.template_engine = TemplateRecognizer(template_path_green, 0.8, 0.3)  # 看配装处的价格
        # 看小号得阈值不能超过 0.8，不然有的人识别不出来
        self.template_engine_small = TemplateRecognizer(template_path_white, 0.78, 0.25, self.test)  # 看小号的价格

    def run(self):
        """线程的主循环，执行自动化任务。"""
        self._log("[任务] Worker已启动",color="blue")
        pyautogui.PAUSE = 0
        pyautogui.MINIMUM_DURATION = 0.01
        ctypes.windll.winmm.timeBeginPeriod(1)  # 高精度计时器

        try:
            if self.task_type == "single_client_settings":     # 单端滚仓
                self.task_single_client()
            elif self.task_type == "hoarding_settings":        # 屯仓
                self.hoard_mode = self.task_params["hoarding_settings"]["hoard_mode"]
                if self.hoard_mode == "默认":
                    self.task_hoarding()
                elif self.hoard_mode == "无探测":
                    self.task_hoarding_no_detect()
                elif self.hoard_mode == "双端屯仓":
                    self.task_hoarding_dual()
            elif self.task_type == "double_client_settings":   # 双端滚仓
                self.task_double_client()
            elif self.task_type == "skin_settings":
                self.task_skin()
            elif self.task_type == "test_mode":
                self.task_test()
            else:
                self._log("当前功能还未开发！",color='blue')

        except Exception as e:
            # 记录详细的错误信息到日志
            self._log(f"[错误] 任务执行期间发生未知错误", color='red')
            import traceback
            traceback_str = traceback.format_exc()
            # 为了在QTextEdit中正确显示换行，我们需要将\n替换为<br>
            self._log(traceback_str.replace('\n', '<br>'),color='red')

        finally:
            ctypes.windll.winmm.timeEndPeriod(1)  # 恢复计时
            try:
                self.finished_signal.emit()
                self.save_log_signal.emit()
            except Exception as e:
                logger.warning(f"线程退出清理时异常: {e}")

    def _log(self, text:str,color:str='black'):
        self.log_signal.emit(f"<font color={color}>{text} - {get_timestamp_ms()}</font>")

    def next_loop(self,idx:int):
        """切换到下一个配装方案，形成循环"""
        # if self.task_type == "single_client_settings":
        #     单端需要等一会
        # self.safe_sleep(self.delay_small)
        if self.num_loadouts > 1:
            # 5. 切换到下一个配装方案，形成循环
            idx = (idx + 1) % self.num_loadouts
        else:
            confirm_loadout, _ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large["confirm_loadout"]),
                threshold=400)
            if not confirm_loadout:  # 保证在配装界面才会esc
                pyautogui.press('esc'), self.safe_sleep(0.05)
            pyautogui.press('L')

        # 加一个短暂的延时，防止CPU占用过高
        self.safe_sleep(0.05)
        return idx

    def stable_recognize_price(self,
            recognize_engine,
            recognize_area:tuple|list,
            min_valid_price: int = 0,
            required_stable_count: int = 1,
            max_duration_seconds: float = 1.0) -> tuple[int, float]:
        """
        稳定地识别一个价格，只有当连续 N 次识别到相同价格时才返回。

        这个函数用于处理价格数字跳动或识别不稳定的情况，通过要求连续多次
        识别结果一致来确保返回值的准确性。

        Args:
            recognize_engine: 传递识别引擎，要调用 recognize 方法
            recognize_area:   截图区域 (x,y,w,h)
            min_valid_price:  识别出的价格必须高于此值才被视为有效,默认为 0。
            required_stable_count: 需要连续识别到相同价格的次数,默认为 1。
            max_duration_seconds: 函数运行的最大时间（秒），超时后将失败,默认为 1.0。

        Returns:
            tuple[float, float]:
                - 如果成功，返回一个元组 (识别到的稳定价格, 最后一次的置信度)。
                - 如果超时或失败，返回 (0.0, 0.0)。
        """
        start_time = time.perf_counter()

        last_price = 0  # 初始化一个不可能的价格
        current_stable_count = 0

        while not self.flag.stop:
            if time.perf_counter() - start_time > max_duration_seconds:
                return 0,0
            price, confidence = recognize_engine.recognize_price(recognize_area)

            # 检查识别出的价格是否有效
            if price > min_valid_price and confidence>0.8:
                if price == last_price:
                    # 价格与上一次相同，增加稳定计数
                    current_stable_count += 1
                else:
                    # 价格不一样则重置计数器
                    last_price = price
                    current_stable_count = 1
                # 检查是否已达到稳定识别的要求
                if current_stable_count >= required_stable_count:
                    return last_price, confidence
            else:
                last_price = 0
                current_stable_count = 0

        return 0,0  # 说明被用户停止了

    def set_auto_shit(self,task_params):
        """
        自动挡屎设置
        Args:
            task_params: 从 ui 传来得大参数字典

        Returns:
        """
        self.auto_block_shit_option = task_params['auto_block_shit_option']
        self.price_range = task_params['price_range']
        self.price_diff = task_params['price_diff']
        match = re.search(r'\d+', self.price_range)
        price_range_number = int(match.group(0))
        self.price_diff_real = -self.price_diff * price_range_number
        self.last_shit = 0  # 上一次挡屎价
        self.auto_block_max = task_params['auto_block_max'] # 最高挡屎价

    def task_single_client(self):
        """单端滚仓金弹"""
        self._log(f"[任务] 执行单端滚仓", color='blue')
        # ============= 单端参数 ================
        task_params = self.task_params["single_client_settings"]
        self.delay_loadout = task_params['delay_loadout']      # 识别延迟
        # self.delay_small = task_params['delay_small']
        self.bullet_quantity = task_params['bullet_quantity']  # 子弹数量
        self.enabled_loadouts = task_params['loadouts']
        self.num_loadouts = len(self.enabled_loadouts)         # 总共有几个配装
        self.auto_sell = task_params['auto_sell']
        self.auto_sell_price:int = task_params['auto_sell_price']
        self.min_sell_price = task_params['min_sell_price']
        self.receive_email_frq = task_params['receive_mail']
        self.fast_eat = task_params['fast_eat']
        self.refresh_interval = task_params['refresh_interval'] * 60
        self.delay_eat_min = task_params['delay_eat_min']
        self.delay_eat_max = task_params['delay_eat_max']
        self.set_auto_shit(task_params)

        local_loadouts = self.enabled_loadouts
        # 如果用了自动挡屎，则要先把挡屎价改成 0
        if self.auto_block_shit_option:
            for loadout in local_loadouts:
                loadout['max_price'] = 0

        idx = 0 # 使用局部变量 idx 作为索引
        perform_clicks = self.perform_clicks
        need_receive_mail = 0
        max_price_err_n = 8    # 连续10次价格错误就会触发返回配装机制
        price_err_n = 0

        wait_duration_s = 0.1   # 监测白点的等待时间
        last_refresh_time = time.time()

        if self.auto_plan:
            # 如果是自动化的，防止被屯仓卡住
            self.perform_clicks(self.coords_large["begin_game"])
            need_return, _ = self.ocr.recognize_price(self.coords_large["min_price_area"])
            if need_return:
                self.return_to_loadout()

        while not self.flag.stop:

            if self.game_crash(stop=False):
                # 游戏崩溃后重启，重启完立即停止
                self.re_act_delta_force()
                break

            # 1. 获取当前要检查的配装方案
            if time.time() - last_refresh_time > self.refresh_interval:
                if not self.refresh_func(): break
                if not self.return_to_loadout():break
                # 重置计时器
                last_refresh_time = time.time()
            loadout = local_loadouts[idx]

            # 2. 点击切换到该配装方案
            self.perform_clicks(loadout['click_coord'], delay=0.03)
            self.safe_sleep(self.delay_loadout)

            # 3. 识别价格
            need_buy = False  # 是否应该执行购买

            if not self.fast_eat:
                price, _ = self.ocr.recognize_price(self.monitor_price)
            else:
                self.safe_sleep(0.05)
                # --- 1. 高性能初始化 ---
                max_attempts = 25
                min_price = loadout['min_price']
                last_valid_price = -1  # 使用一个特殊值-1表示尚未找到有效价格
                final_price = 0
                # log_buffer = []  # 使用内存列表作为日志缓冲区，避免频繁I/O

                # --- 2. 极致性能的监控循环 ---
                for i in range(max_attempts):
                    # a. 核心操作：识别价格
                    price, _ = self.template_engine.recognize_price(self.monitor_price)

                    # b. 内存日志记录
                    # log_buffer.append(f"A{i + 1}: {price}\n")

                    # c. 核心逻辑判断 (将所有条件合并)
                    if price >= min_price:
                        # 只要是有效价格，就进入此分支
                        if last_valid_price == -1:
                            # e. 首次找到有效价格，启动监控
                            last_valid_price = price
                        elif price != last_valid_price:
                            # f. 检测到价格变化，立即决策并终止循环
                            final_price = price
                            # log_buffer.append(f"--> LOCK: Change from {last_valid_price} to {price}\n")
                            break
                        # g. 如果价格未变，last_valid_price 无需更新，因为它和 price 相同

                    # h. 精确延时
                    self.safe_sleep(0.003)  # 严格控制延时

                # --- 3. 循环结束后的处理 ---
                if final_price == 0 and last_valid_price != -1:
                    # 如果循环正常结束（未break），且曾找到过有效价格
                    final_price = last_valid_price
                    # log_buffer.append(f"--> LOCK: Exhausted, using last valid: {final_price}\n")

                price = final_price

            if price != 0:
                # 只要能识别出来就重置计数器
                price_err_n = 0

                if self.auto_block_shit_option:
                    # 更新自动挡屎
                    if price >= loadout['min_price']:
                        self.update_block_shit_price(price)
                    else:
                        self._log(f"[抛弃] 价格 {price:,} 过低，判断为识别错误")

                    if not self.auto_block_shit:
                        self._log("[探测] 正在自动探测挡屎价")
                        idx = self.next_loop(idx)
                        continue
                    else:
                        loadout['max_price'] = max(0,self.auto_block_shit + self.price_diff_real*self.bullet_quantity)
                        loadout['max_price'] = min(loadout['max_price'],self.auto_block_max*self.bullet_quantity)

                        if self.last_shit != self.auto_block_shit:
                            self._log(f"[探测] 当前挡屎价为 {loadout['max_price'] // self.bullet_quantity}",color='blue')
                        self.last_shit = self.auto_block_shit

            # 4. 判断价格
            if price > loadout['max_price']:
                self._log(f"[跳过] 方案 {loadout['id']}: 价格 {price:,} 单价 {price // self.bullet_quantity}")
            elif price == 0:
                # 等于0肯定就是没识别到图像
                self._log(f"[警告] 方案 {loadout['id']}: 未识别到价格")
                price_err_n += 1
                if price_err_n >= 30:
                    self._log(f"[错误] 大量未识别到价格，脚本已停止运行",color='red')
                    break
                if price_err_n >= max_price_err_n:
                    # 连续10次判别失误就回配装界面
                    self.return_to_loadout()
                if price_err_n % 13 == 0:
                    # 有可能配装的L卡没了
                    pyautogui.press('esc')
                    self.safe_sleep(1)
            elif price < loadout['min_price']:
                self._log(f"[抛弃] 方案 {loadout['id']}: 价格 {price:,} 过低，判断为识别错误")
            else:
                # 第一次监测通过，下面进行重复监测
                # self._log(
                #     f"<font color='blue'>[低价] 第1次 方案 {loadout['id']}: 价格 {price:,} 单价 {price//self.bullet_quantity}"
                #     f" - {get_timestamp_ms()}")

                pyautogui.moveTo(self.buy_button_coord)     # 鼠标去那里等着

                if not self.fast_eat:
                    # 第二次检测
                    self.safe_sleep(0.4)  # 非秒吃模式下等一会
                    price, _ = self.ocr.recognize_price(self.monitor_price)
                    if loadout['min_price'] <= price <= loadout['max_price']:
                        # self._log(
                        #     f"<font color='blue'>[低价] 第2次 方案 {loadout['id']}: 价格 {price:,} 单价 {price // self.bullet_quantity}"
                        #     f" - {get_timestamp_ms()}")

                        # 非秒吃模式下进行第三次监测
                        self.safe_sleep(0.2)
                        status, _ = self.image_processor.wait_and_detect_spot_disappearance(
                            region_coords=self.coords_large['white_spot'],
                            wait_duration_s=wait_duration_s,
                            max_capture_duration_s=5,
                            fps=100,
                            spot_threshold=5,
                            brightness_threshold=35,
                        )
                        price, _ = self.ocr.recognize_price(self.monitor_price)  # 第3次检测
                        if loadout['min_price'] <= price <= loadout['max_price']:
                            # 再次确认价格对不对
                            # 价格合适！尝试购买
                            self._log(f"[低价] 方案 {loadout['id']}: 价格 {price:,} 单价 {price//self.bullet_quantity}",color='blue')
                            self._log(f"[低价] 确认是低价，执行购买!",color='blue')
                            need_buy = True
                        else:
                            self._log(f"[低价] 价格已发生变化，抛弃",color='orange')

                    else:
                        self._log(f"[低价] 价格已发生变化，抛弃",color='orange')
                else:
                    # 秒吃模式下直接吃
                    need_buy = True

            sleep_duration = 0.0    # 秒吃模式下为 0
            if need_buy and not self.fast_eat:
                # 在非秒吃模式下要等待
                sleep_duration = round(random.uniform(self.delay_eat_min, self.delay_eat_max), 3)
                self.safe_sleep(sleep_duration)
                # 最后再检测一下
                price, _ = self.ocr.recognize_price(self.monitor_price)  # 第4次检测
                need_buy = loadout['min_price'] <= price <= loadout['max_price']

            if need_buy:
                # 点击购买按钮
                perform_clicks(self.buy_button_coord, delay=0.00, hold_duration=0.02)
                # 判断购买是否成功
                # success_code, _ = self.tell_success_buy(self.monitor_text,
                #                                         capture_duration_s=3,
                #                                         fps=30,
                #                                         only_check_for_green=True,
                #                                         save_all_frames=self.test,
                #                                         )
                success_code = self.tell_success_buy_v2()
                if success_code >= 0:  # 购买成功
                    if self.flag.stop: break  # 断点
                    self._log(f"[成功] 成功购买方案 {loadout['id']}",color='green')

                    self.append_to_log_file("运行日志/成功.txt", f"[成功] {sleep_duration:>6.3f} - {get_datetime()}")

                    if not self.auto_sell:
                        self._log(f"[成功] 未抽选自动售卖，任务结束",color='green')
                        break

                    # if not self.safe_sleep(2.0):break  # 等买子弹过程结束
                    # # 有时候抢了一部分，需要判断一下是不是这种情况，需要再次判断有没有回到配装界面
                    # confirm_loadout, _ = self.image_processor.has_green(
                    #     self.image_processor.capture_region(self.coords_large["confirm_loadout"]),
                    #     threshold=200)
                    # if not confirm_loadout:  # 如果不在配装界面就按1下esc
                    #     self._log(f"[成功] 检测出：子弹没吃满",color='green')
                    #     pyautogui.press('esc'), self.safe_sleep(0.5)
                    if success_code == 1:
                        self._log(f"[成功] 检测出：子弹没吃满", color='green')
                        pyautogui.press('esc'), self.safe_sleep(0.5)

                    if need_receive_mail == 0:
                        # 每抢成功5次领一次邮件
                        self.receive_email(), self.safe_sleep(0.5)  # 领邮件
                    need_receive_mail += 1
                    need_receive_mail %= self.receive_email_frq
                    # # ===== 去仓库 =====
                    # if self.flag.stop: break  # 断点
                    # self.move_bullets_to_warehouse()
                    # ===== 卖子弹 =====
                    if self.flag.stop: break  # 断点
                    if not self.sell_bullets_v2(): break  # 卖失败直接停
                    self.safe_sleep(0.5)
                    # ===== 回配装进入下一次循环 =====
                    if self.flag.stop: break  # 断点
                    self.perform_clicks(self.coords_large['begin_game'], delay=0.3, hold_duration=0.1,times=2)
                    self.safe_sleep(1)
                    pyautogui.press('L'), self.safe_sleep(0.2)
                    pyautogui.press('L'), self.safe_sleep(0.8)
                else:  # 没抢到
                    if self.flag.stop: break  # 断点
                    self._log(f"[失败] 方案 {loadout['id']}: 单价 {price//self.bullet_quantity} 没抢到...",color='blue')

                    self.append_to_log_file("运行日志/失败.txt",f"[失败] {sleep_duration:>6.3f} - {get_datetime()}")

                    self.safe_sleep(0.3)
                    pyautogui.press('esc'), self.safe_sleep(0.5)
                    pyautogui.press('L'), self.safe_sleep(0.1)

            idx = self.next_loop(idx)

    def tell_success_buy_v2(self) -> int:
        """
        专用于滚仓配装购买的成功检测
        正常情况下，有3种情况，全部购买，部分购买和购买失败
        全部购买为仅有绿色文本，部分购买为绿色文本+价格变化，购买失败仅有价格变化
        """
        # 首先记录是不是点上购买了，成功点击会变成灰色
        start_time = time.perf_counter()  # 开始的时刻
        capture_duration_s = 2
        end_time = start_time + capture_duration_s
        success_click = False   # 是否点击成功
        while time.perf_counter() < end_time:
            image0 = self.image_processor.capture_region(self.monitor_price)  # 检测是不是真的点上了
            success_click = not self.image_processor.has_green(image0, threshold=100)[0]
            if success_click:break
            self.safe_sleep(0.05)

        if not success_click:
            self._log(f"[错误] 点击购买无效",color='red')
            return -2

        fps = 30
        interval = 1.0 / fps
        start_time = time.perf_counter()    # 开始的时刻
        capture_duration_s = 10
        end_time = start_time + capture_duration_s
        tell1 = False   # 是否有购买成功的绿色文本
        tell2 = False   # 是否价格变化的文本
        while time.perf_counter() < end_time:
            t1 = time.perf_counter()

            if not tell1:   # 在没有记录的情况下判断
                image1 = self.image_processor.capture_region(self.monitor_text)  # 是否有购买成功的绿色文本
                tell1 = self.image_processor.has_green(image1, threshold=150)[0]
                if tell1 and not tell2:
                    end_time = time.perf_counter() + 1.0   # 只保留1s的时间

            if not tell2:
                image2 = self.image_processor.capture_region(self.coords_large['price_change'])  # 是否价格变化的文本
                tell2 = self.image_processor.has_gray(image2, threshold=1800)[0]
                if tell2 and not tell1:
                    end_time = time.perf_counter() + 1.0   # 只保留1s的时间
            if tell1 and tell2:break
            if not self.safe_sleep(interval - (time.perf_counter()-t1)):return -1
        # print(tell1,tell2)
        if (not tell1) and tell2:
            return -1   # 确定购买失败了
        elif tell1 and (not tell2):
            return 0    # 确定购买成功了,且全额购买
        elif tell1 and tell2:
            return 1    # 确定购买成功，但是只买了一部分
        else:
            return -2   # 未知情况

    @timing_decorator("识别有没有兑换耗时：{duration:.3f} s", logger.info)
    def set_has_exchange(self):
        """
        识别有没有兑换，设置兑换的档位。
        确定小号购买子弹应该点哪里
        """
        has_exchange, _ = self.image_processor.has_green(
            self.image_processor.capture_region(
                self.coords_small["buy_with_exchange_box"]), threshold=40)

        if has_exchange:
            self.has_exchange = 0
        else:
            # 没有兑换的情况
            self.has_exchange = 1

        # 小号的点击位置
        self.small_click_buy = self.coords_small['buy'][self.has_exchange]  # 购买按钮点击坐标
        self.small_buy1 = self.coords_small["buy1"][self.has_exchange]      # 拉到1 发点击坐标
        self.small_buy32 = self.coords_small["buy32"][self.has_exchange]    # 拉到32发点击坐标
        self.small_buy200_near = self.coords_small['buy200_near'][self.has_exchange] # 拉满
        self.small_buy_amount_minus = self.coords_small["buy_amount_minus"][self.has_exchange]  # 数量减一
        self.small_buy_amount = self.coords_small['buy_amount'][self.has_exchange]    # 实际的购买数量

        if self.task_type == "hoarding_settings":   # 如果是屯仓，需要下面的内容
            # 大号的点击位置（屯仓用）
            self.large_click_buy = self.coords_large_hoarding['buy'][self.has_exchange]     # 购买按钮点击坐标
            self.large_buy1 = self.coords_large_hoarding["buy1"][self.has_exchange]         # 拉到1 发点击坐标
            self.large_buy200_near = self.coords_large_hoarding['buy200_near'][self.has_exchange] # 拉满
            self.large_buy_amount_minus = self.coords_large_hoarding["buy_amount_minus"][self.has_exchange]  # 数量减一
            self.large_buy_amount = self.coords_large_hoarding['buy_amount'][self.has_exchange]    # 实际的购买数量

            BUY_CLICK :tuple= self.large_click_buy
            BUY_QTY :int= BULLETS_SET  # 买入时，一次购买的子弹数量（200发）
            BUY_SHIFT_CLICK :tuple= self.coords_large_hoarding["buy" + str(BUY_QTY)][self.has_exchange]
            BUY_SHIFT_CHECK :tuple= self.large_buy_amount
            DETECT_CLICK :tuple= self.small_click_buy
            DETECT_QTY :int= self.detect_quantity   # 探测时，一次购买的子弹数量（32/11 发）
            DETECT_SHIFT_CLICK :tuple= self.coords_small["buy" + str(self.detect_quantity)][self.has_exchange]
            DETECT_SHIFT_CHECK :tuple= self.small_buy_amount

            # ================== 定义常量 ================
            self.BUY_MODE = {
                "large":{
                    "buy_click":BUY_CLICK,      # 购买按钮点击坐标
                    "buy_quantity":BUY_QTY,     # 购买数量
                    "buy_shift_click":BUY_SHIFT_CLICK,  # 修改数量点击坐标
                    "buy_shift_check":BUY_SHIFT_CHECK,  # 检查修改数量区域
                    "loop_period":self.buy_circle # 购买周期
                },
                "small":{
                    "buy_click": DETECT_CLICK,  # 购买按钮点击坐标
                    "buy_quantity":DETECT_QTY,
                    "buy_shift_click":DETECT_SHIFT_CLICK,
                    "buy_shift_check":DETECT_SHIFT_CHECK,
                    "loop_period":self.detect_circle  # 探测周期
                },
            }

        else:
            # ================== 定义常量 ================
            self.BUY_MODE = {
                "large":{
                    # "buy_click":BUY_CLICK,      # 购买按钮点击坐标
                    "buy_quantity":31,     # 购买数量
                    # "buy_shift_click":BUY_SHIFT_CLICK,  # 修改数量点击坐标
                    # "buy_shift_check":BUY_SHIFT_CHECK,  # 检查修改数量区域
                    "loop_period":self.small_buy_circle # 购买周期
                },
                "small":{
                    # "buy_click": DETECT_CLICK,  # 购买按钮点击坐标
                    "buy_quantity":31,
                    # "buy_shift_click":DETECT_SHIFT_CLICK,
                    # "buy_shift_check":DETECT_SHIFT_CHECK,
                    "loop_period":self.small_buy_circle  # 探测周期
                },
            }

    def _hoarding_init(self):
        """
        屯仓任务初始化
        """
        # ================ 屯仓配置 =====================
        task_params = self.task_params["hoarding_settings"]
        self.hoard_target_quantity = task_params['hoard_target_quantity']
        self.hoard_min_price = task_params['hoard_min_price']
        self.hoard_max_price = task_params['hoard_max_price']
        self.buy_circle:float = task_params['buy_circle'] + 0.1   # 内置 0.1s
        self.detect_quantity = task_params['detect_quantity']
        self.detect_circle:float = task_params['detect_circle'] + 0.1   # 内置 0.1s
        self.refresh_rate:float = task_params['refresh_rate'] + 0.03     # 内置 0.03s
        self.bullet_name_input = task_params['bullet_name_input']
        self.purchase_location_selector = task_params['purchase_location_selector']
        self.hoard_mode = task_params["hoard_mode"]
        self.dynamic_sleep :bool = task_params["dynamic_sleep"]
        self.continuous_buy :int = task_params["continuous_buy"]
        self.continuous_detect :int = task_params["continuous_detect"]

    def _hoard_check_system_errors(self, tracker: "HoardTracker") -> bool:
        """检查错误：仓库满或长时间未变动"""
        if tracker.err_count % 4 == 0 and tracker.err_count > 0:
            # 大概率是堆积了，这个是特殊情况，长时间休眠保护
            self._log(f"[警告] 价格多次没变化，进入休眠保护", color='red')
            if not self.safe_sleep(10): return False

        if tracker.err_count >= 13:
            self._log(f"[错误] 仓库已满或交易行异常，停止运行", color='red')
            self.flag.stop = True
            return False

        if tracker.err_cost_n > 4:
            self._log(f"[错误] 多次识别错误，停止运行", color='red')
            self.flag.stop = True
            return False

        return True

    def _hoard_ensure_quantity(self, current_qty: int, target_qty: int,
                               click_coord: tuple[int,int], check_coord: tuple):
        """确保购买数量正确，不正确则拉动"""
        if current_qty != target_qty:
            self.pull_amount(click_coord, target_qty, check_coord)

    def _search_item_click(self)->bool:
        """
        处理屯仓前的搜索和定位逻辑
        1.点击搜索框
        2.搜出来后，点击选择的位置

        如果没有指定搜索，则把 self.purchase_location_selector 改成2，并点击
        """
        # 只有输入了 "搜索名称" 和 "点击位置" 才会执行
        if self.bullet_name_input and self.purchase_location_selector and self.hoard_mode in ("默认", "无探测"):
            if not self.navigate_to_sell_page(page=0):return False
            # 点击输入框，复制进去
            res = InputSimulator.smart_cover(
                pos=self.coords_large["buy_search"],
                content=self.bullet_name_input,
            )
            if not res:return False

            # ----- 验证是否进入购买界面，看不见 "交易行"的绿色说明进去了 -----
            for _ in range(30):
                green, _ = self.image_processor.has_green(self.coords_large["trade_green"])
                if green:
                    self.perform_clicks(self.coords_large["select_bullets"][self.purchase_location_selector-1],**STABLE_CLICK)
                    self.safe_sleep(0.3)
                else:
                    self.safe_sleep(0.3)
                    return True

            # 点不进去，不知道为啥失败了
            return False
        else:
            self.purchase_location_selector = max(1,self.purchase_location_selector)    # 默认点击第一个

        return True

    def _switch_client_window(self, target_client: str, current_client: str):
        """双端模式下的窗口切换逻辑"""
        if target_client != current_client:
            if not self.op_large.unlock_cursor():
                pyautogui.keyDown('alt'), self.safe_sleep(0.03)
                pyautogui.press('tab'), self.safe_sleep(0.03)
                pyautogui.keyUp('alt'), self.safe_sleep(0.04)
            self._log(f"[切换] 窗口切换至: {target_client}")
            return target_client
        return current_client

    def task_hoarding(self)->bool:
        """
        单端屯仓的函数
        """
        self._log(f"[任务] 执行单端屯仓", color='blue')
        # =========== 初始化 ===========
        self._hoarding_init()
        # 搜索物品并点进去
        if not self._search_item_click():
            self._log("[错误] 无法点进商品页面，停止运行。", color='red')
            return False
        self.set_has_exchange()

        tracker = HoardTracker(
            is_dual=False,
            target_qty=self.hoard_target_quantity,
            min_price=self.hoard_min_price,
            max_price=self.hoard_max_price,
            buy_configs=self.BUY_MODE,
            dynamic_slow=self.dynamic_sleep,
            slow_circle=self.detect_circle,
            confirm_n=self.continuous_detect,
            max_buy_n=self.continuous_buy,
        )
        # =============================

        # ================= 主循环变量 ==================
        account_type = "large"
        # ------------ 确定初始余额 ----------------
        initial_balance = self.record_init_balance(account_type)        # 初始余额
        if initial_balance<=0:return False
        tracker.init_balance(account_type, initial_balance)

        self.pull_amount(tracker.shift_click, tracker.once_qty) # 直接拉数量，进入探测阶段
        skip_once = False    # 跳过一次数量检测
        # ==============================================

        while not self.flag.stop and not self.game_crash():
            if self.flag.stop: break
            tracker.record_action(tracker.activated)    # 记录本轮开始的时刻
            if tracker.is_finished:
                self._log(f"[完成] 已经购买到设定数量的物品，任务结束", color='green')
                break
            if not self._hoard_check_system_errors(tracker): break

            self.perform_clicks(tracker.buy_click, **FAST_CLICK)    # 买一发子弹
            # 去上面看一下余额，并把鼠标移动回来
            # buy_amount_check 是购买结束后当前显示的数量，由于购买后数量可能会变化，并且是买到多少发就减少多少数量
            # 好像如果部分购买，实际上买了多少，数量就会减多少
            new_balance, buy_amount_check = self.see_balance(
                account_type = tracker.activated,
                need_buy_amount = not skip_once
            )

            if skip_once:   # 跳过一次数量检查
                buy_amount_check, skip_once = tracker.once_qty, False

            if not (0<buy_amount_check<=BULLETS_SET):
                self._log(f"[警告] 购买数量错误，请检查是否遮挡购买数量",color='red')

            # 3. 购买数量校准，如果购买后数量变了，需要拉回去
            self._hoard_ensure_quantity(buy_amount_check, tracker.once_qty, tracker.shift_click, tracker.shift_check)

            if not new_balance:
                # 识别成0，说明价格识别错了
                self._log(f"[警告] 探测没有识别到价格",color='red')
            else:
                # 计算子弹单价
                cost = tracker.calc_cost(new_balance, buy_amount_check)

                # ----- 正常情况 -----
                if cost > 0:
                    tracker.record_success(cost, buy_amount_check)
                    tracker.update_balance(new_balance)         # 更新余额

                    # 更新模式：tracker 内部会自动处理配置切换
                    tracker.update_mode(cost)
                    # self._log(f"当前探测时间：{tracker.loop_period}")
                    if tracker.activated == "large":
                        # 记录现在是【买入】模式
                        self._log(f"[买入] 单价为 {cost}", color='blue')
                    else:
                        # 记录现在是【探测】模式
                        self._log(f"[探测] 单价为 {cost}")

                # ----- 交易行卡价格了 -----
                elif cost == 0:
                    tracker.record_frozen_price()
                    if tracker.once_qty == self.detect_quantity:
                        # 如果在探测阶段没有识别到cost，则把周期改为购买周期，快速探测
                        tracker.set_loop_period(self.buy_circle)

                # ----- 消耗小于0，肯定识别错了 -----
                elif cost < 0:
                    tracker.record_error_cost()
                    self._log(f"[警告] 价格识别有误，当前余额为 {new_balance},先前为 {tracker.current_balance}",color='red')
                    new_balance_ocr = self.see_balance_ocr(tracker.activated)   # 用 ocr 重新识别，相信 ocr
                    if new_balance_ocr == new_balance:
                        tracker.update_balance(new_balance)

            if tracker.need_realign_quantity():
                # 在这里把购买数量拉对，跳过下次循环开始的检验
                skip_once = True
                self.pull_amount(tracker.shift_click, tracker.once_qty, tracker.shift_check)  # 拉数量，并检验对不对

            self.safe_sleep(tracker.get_wait_time())    # 用于保证周期一致

    def task_hoarding_no_detect(self):
        """
        无探测屯仓的函数
        """
        self._log(f"[任务] 执行无探测屯仓", color='blue')
        # =========== 初始化 ===========
        self._hoarding_init()

        # 搜索物品并点进去
        if not self._search_item_click():
            self._log("[错误] 无法点进商品页面，停止运行。", color='red')
            return False

        # ================= 主循环变量 ==================
        refresh_limit = 200         # 默认 刷200次就去一次大战场
        refresh_n = 0               # 记录当前刷了多少次
        accum_buy_quantity = 0      # 当前购买的子弹数量
        now_loop_period = self.buy_circle  # 购买周期，不会变
        click_duration :float = 0.8   # 持续点击，直到进入交易行购买界面
        click_pos :tuple = self.coords_large["select_bullets"][self.purchase_location_selector - 1]     # 固定的子弹点击位置
        # =============================================

        # 先检测一下是不是在购买界面
        if not self.is_buy_in_trade():
            self.navigate_to_sell_page(page=0)  # 回交易行
            self.perform_clicks(click_pos) # 点击子弹
            self.safe_sleep(1)

        self.set_has_exchange()

        auto_block_enabled, rank, auto_block_max, price_diff = (
            self.task_params["hoarding_settings"]["auto_block_shit_settings"])

        # 设置自动挡屎
        if auto_block_enabled:
            self.auto_block = DynamicPriceManager(
                price_diff, rank,
                max_limit=auto_block_max,
                min_limit=self.hoard_max_price,)    # 在无探测模式下这个就是 最低值
        else:
            self.auto_block = DynamicPriceManager(enabled=False,price_base=self.hoard_max_price)
        # =============================

        while not self.flag.stop and not self.game_crash():
            if self.flag.stop: break
            if accum_buy_quantity >= self.hoard_target_quantity:
                self._log(f"[完成] 已经购买到设定数量的物品，任务结束",color='green')
                break

            # 每刷够一定数量，去大战场一次
            refresh_n += 1
            if refresh_n >= refresh_limit:
                refresh_n = 0
                if not self.refresh_func():break

                if not self.navigate_to_sell_page(page=0):
                    self._log(f"[错误] 无法到交易行，任务结束", color='red')
                    return

                # 搜索物品并点进去
                if not self._search_item_click():
                    self._log("[错误] 无法点进商品页面，停止运行。", color='red')
                    return False

            # 如果不小心多按了一次esc，回到开始页面，则返回去
            if self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['begin_game_green']),
                threshold=60
            )[0]:
                self.navigate_to_sell_page(page=0)  # 回交易行
                self.perform_clicks(click_pos)  # 点击子弹
                self.safe_sleep(1)
                self.set_has_exchange()  # 重新识别有没有兑换

            # 点击进商品，直到检测出右上角灰色框
            click_init = time.perf_counter()
            while time.perf_counter()-click_init < click_duration:
                self.perform_clicks(click_pos)
                if self.is_buy_in_trade():break

            self.pull_full_amount_large()  # 拉到200
            # 识别右下角价格
            price_full, confidence = self.stable_recognize_price(
                self.template_engine,
                recognize_area = self.coords_large['monitor_price_in_trade'][self.has_exchange],
                required_stable_count = 0,
            )
            price_full //= BULLETS_SET
            self.hoard_max_price = self.auto_block.process(price_full)  # 更新挡屎价

            # 首次识别到低价就买入，如果低价没了会购买失败，所以不用担心买到屎
            # 每次购买完成后，价格都会更新，因此需要在购买前识别一下
            buy_s :int= 0   # 购买的次数
            if self.hoard_min_price<=price_full<=self.hoard_max_price and confidence>0.8:
                while not self.flag.stop:
                    t = time.perf_counter()     # 开始周期计时

                    # ===== 重新识别价格 =====
                    if buy_s != 0:
                        price_full, confidence = self.template_engine.recognize_price(
                            self.coords_large['monitor_price_in_trade'][self.has_exchange])
                        price_full //= BULLETS_SET
                        if not (self.hoard_min_price <= price_full <= self.hoard_max_price and confidence > 0.8):  # 再次检测到低价
                            self._log(f'[跳过] 单价为 {price_full}')
                            break
                    else:
                        buy_s += 1
                    # ===============================
                    # ===== 买入 =====
                    self.perform_clicks(self.small_click_buy, hold_duration=0.03)  # 买一次
                    accum_buy_quantity += BULLETS_SET  # 默认买成功
                    self._log(f'[买入] 单价为 {price_full}', color='blue')  # 记录日志
                    # ===============================
                    # ===== 重新拉数量 =====
                    self.pull_full_amount_large()  # 拉到200发
                    pyautogui.moveTo(self.small_click_buy)
                    # ===============================
                    self.safe_sleep(now_loop_period - (time.perf_counter() - t))
            else:
                self._log(f'[跳过] 单价为 {price_full}')

            # 提前移动鼠标过去
            pyautogui.moveTo(click_pos)
            # 如果在购买页面，则按下esc
            if self.is_buy_in_trade():
                pyautogui.press('esc'),self.safe_sleep(self.refresh_rate)
        # ====================================================

    def task_hoarding_dual(self):
        """双端屯仓函数"""
        self._log(f"[任务] 执行双端屯仓", color='blue')

        # =========== 初始化 ===========
        self._hoarding_init()
        self.set_has_exchange()

        tracker = HoardTracker(
            is_dual=True,
            target_qty=self.hoard_target_quantity,
            min_price=self.hoard_min_price,
            max_price=self.hoard_max_price,
            buy_configs=self.BUY_MODE,
            dynamic_slow=self.dynamic_sleep,
            slow_circle=self.detect_circle,
            confirm_n=self.continuous_detect,
            max_buy_n=self.continuous_buy,
        )
        # =============================

        # ================= 主循环变量 ==================

        # ------------ 根据 [探测]/[买入]模式 变化的量 ----------------
        activated = "small" # 用于记录当前是在探测还是买入，初始为探测
        # ------------ 确定初始余额 ----------------
        self._log(f"[屯仓] 正在识别初始余额")
        initial_large_balance = self.record_init_balance("large")
        if initial_large_balance <= 0: return False
        tracker.init_balance("large", initial_large_balance)

        self.pull_full_amount_large()     # 大号拉到200发

        # 切换到小号
        if not self.op_large.unlock_cursor():
            pyautogui.keyDown('alt'), self.safe_sleep(0.03)
            pyautogui.press('tab'), self.safe_sleep(0.03)
            pyautogui.keyUp('alt'), self.safe_sleep(0.04)

        initial_small_balance = self.record_init_balance("small")
        if initial_small_balance <= 0: return False
        tracker.init_balance("small", initial_small_balance)

        self.pull_amount(tracker.shift_click, tracker.once_qty) # 小号拉到探测数量
        skip_once = False    # 跳过一次数量检测
        # ===========================================

        while not self.flag.stop and not self.game_crash():
            if self.flag.stop: break
            tracker.record_action(tracker.activated)  # 记录本轮开始的时刻
            if tracker.is_finished:
                self._log(f"[完成] 已经购买到设定数量的物品，任务结束",color='green')
                break
            if not self._hoard_check_system_errors(tracker): break

            if tracker.transition_msg == "探测":
                self.safe_sleep(0.1)
                # 切换到小号
                if not self.op_large.unlock_cursor():
                    pyautogui.hotkey('alt', 'tab', interval=0.01)
                    # pyautogui.keyDown('alt'), self.safe_sleep(0.03)
                    # pyautogui.press('tab'), self.safe_sleep(0.03)
                    # pyautogui.keyUp('alt'), self.safe_sleep(0.04)

            self.perform_clicks(tracker.buy_click, **FAST_CLICK)    # 买一发子弹
            # 去上面看一下余额，并把鼠标移动回来
            # buy_amount_check 是购买结束后当前显示的数量，由于购买后数量可能会变化，并且是买到多少发就减少多少数量
            # 好像如果部分购买，实际上买了多少，数量就会减多少
            new_balance, buy_amount_check = self.see_balance(
                account_type = tracker.activated,
                need_buy_amount=not skip_once,
            )
            if skip_once:   # 跳过一次数量检查
                buy_amount_check, skip_once = tracker.once_qty, False

            if not (0<buy_amount_check<=BULLETS_SET):
                self._log(f"[警告] 购买数量错误，请检查是否遮挡购买数量",color='red')

            # 3. 购买数量校准，如果购买后数量变了，需要拉回去
            self._hoard_ensure_quantity(buy_amount_check, tracker.once_qty, tracker.shift_click, tracker.shift_check)

            if not new_balance:
                # 识别成0，说明价格识别错了
                self._log(f"[警告] 探测没有识别到价格",color='red')
            else:
                # 计算子弹单价
                cost = tracker.calc_cost(new_balance, buy_amount_check)

                # ----- 正常情况 -----
                if cost > 0:
                    tracker.record_success(cost, buy_amount_check)
                    tracker.update_balance(new_balance)         # 更新余额

                    # 更新模式：tracker 内部会自动处理配置切换
                    tracker.update_mode(cost)
                    # self._log(f"当前探测时间：{tracker.loop_period}")
                    if tracker.activated == "large":
                        # 记录现在是【买入】模式
                        self._log(f"[买入] 单价为 {cost}", color='blue')
                    else:
                        # 记录现在是【探测】模式
                        self._log(f"[探测] 单价为 {cost}")

                # ----- 交易行卡价格了 -----
                elif cost == 0:
                    tracker.record_frozen_price()
                    if tracker.once_qty == self.detect_quantity:
                        # 如果在探测阶段没有识别到cost，则把周期改为购买周期，快速探测
                        tracker.set_loop_period(self.buy_circle)

                # ----- 消耗小于0，肯定识别错了 -----
                elif cost < 0:
                    tracker.record_error_cost()
                    self._log(f"[警告] 价格识别有误，当前余额为 {new_balance},先前为 {tracker.current_balance}",color='red')
                    new_balance_ocr = self.see_balance_ocr(tracker.activated)   # 用 ocr 重新识别，相信 ocr
                    if new_balance_ocr == new_balance:
                        tracker.update_balance(new_balance) # 还是信任最新的余额，不然错一个就没法继续了

            if tracker.need_realign_quantity():
                # 在这里把购买数量拉对，跳过下次循环开始的检验
                skip_once = True
                self.pull_amount(tracker.shift_click, tracker.once_qty, tracker.shift_check)  # 拉数量，并检验对不对

            self.safe_sleep(tracker.get_wait_time())    # 用于保证周期一致

    def record_init_balance(self, account_type: str = "large") -> int:
        """
        记录 大号/小号 的初始余额

        Args:
            account_type (str): "large" 代表大号，"small" 代表小号。
        Returns:
            int: 识别到的初始余额，失败返回 0。（程序也会停止）
        """
        # 1. 动态配置映射
        if account_type == "large":
            buy1_pos = self.large_buy1
            buy_btn_pos = self.large_click_buy
            label = "大号"
        else:
            buy1_pos = self.small_buy1
            buy_btn_pos = self.small_click_buy
            label = "小号"

        target_loop_period = self.buy_circle  # 记录初始价格时得购买周期

        # 2. 初始化操作：先将购买数量设为 1
        self.perform_clicks(buy1_pos, times=2, delay=0.1)
        self.safe_sleep(0.1)

        # 3. 尝试识别初始余额
        for i in range(10):
            if self.flag.stop: break
            loop_start_time = time.perf_counter()

            # 点击购买（探测）
            self.perform_clicks(buy_btn_pos, delay=0.05)

            # 识别初始余额
            initial_balance, _ = self.see_balance(account_type=account_type, need_buy_amount=False)

            # 精确控制循环周期
            work_duration = time.perf_counter() - loop_start_time
            sleep_needed = target_loop_period - work_duration
            if sleep_needed > 0:
                if not self.safe_sleep(sleep_needed): return 0

            # 检查识别结果（必须在周期之后，不然会太快）
            if initial_balance > 0:
                self._log(f"[屯仓] {label}初始余额：{initial_balance}")
                return initial_balance

        # 4. 失败处理
        self._log(f"[错误] 识别不到{label}余额，停止运行", color='red')
        self.flag.stop = True
        return 0

    def pull_full_amount_large(self, timeout = 1.0) -> bool:
        """
        大号 拉满价格到 200发（先识别是不是拉到200发了，如果没有则去拉动）
        Args:
            timeout: 最长得持续时间

        Returns:
            如果成功拉到200发，返回True，否则返回False
        """
        t1 = time.time()
        click_pos = self.coords_large_hoarding['buy200'][self.has_exchange]     # 拉数量的位置
        while not self.flag.stop:
            right_amount = self.image_processor.has_white(
                self.image_processor.capture_region(self.large_buy200_near),
                threshold=100)[0]

            if time.time() - t1 > timeout:break

            if right_amount:
                return True
            else:
                self.perform_clicks(click_pos,**CONTINUE_CLICK)
        # 超时
        return False

    def check_buy_amount(self, detect_coords:tuple=None)->int:
        """
        检查当前购买数量
        Args:
            detect_coords: 要检查的坐标区域

        Returns:
            当前购买数量
        """
        buy_amount, _ = self.template_engine_small.recognize_price(detect_coords)
        if buy_amount>0:
            return buy_amount
        else:
            return 0

    def pull_amount(self, click_coords:tuple[int,int], amount:int=0, detect_coords:tuple=None) -> bool:
        """
        将购买数量拉到指定位置，并检验（可选）
        Args:
            click_coords: 拉动数量的点击坐标
            amount: 检查数量
            detect_coords:检查数量的识别框

        Returns:
            是否拉动成功（检验）
        """

        if not detect_coords:
            self.perform_clicks(click_coords, delay=0.05)  # 调整
            return True
        else:
            for _ in range(10):
                if self.flag.stop:return False

                buy_amount = self.check_buy_amount(detect_coords)
                if buy_amount == amount:
                    return True
                else:
                    self.perform_clicks(click_coords, delay=0.05)  # 调整

            return False

    def task_double_client(self):
        """双端滚仓任务"""
        self._log(f"[任务] 执行双端滚仓", color='blue')
        # ================ 双端配置 =====================
        task_params = self.task_params["double_client_settings"]
        self.delay_loadout = task_params['delay_loadout']
        self.loadout_index = task_params['loadout_index']
        self.target_price = task_params['target_price']        # 期望的子弹单价
        self.detect_quantity = task_params['detect_quantity']
        self.bullet_quantity = task_params['bullet_quantity']  # 配装的子弹数量
        self.delay_see_price = task_params['delay_see_price']
        # 生效的配装
        self.enabled_loadouts = task_params['loadouts']
        self.num_loadouts = len(self.enabled_loadouts)  # 总共有几个配装（应该是=1）
        self.auto_sell = task_params['auto_sell']
        self.min_sell_price = task_params['min_sell_price']
        self.receive_email_frq = task_params['receive_mail']
        self.refresh_interval = task_params['refresh_interval'] * 60
        self.small_buy_circle:float = task_params['small_buy_circle'] + 0.1     # 小号购买周期
        self.auto_sell_price = task_params['auto_sell_price']
        self.price_history_double = set()   # 记录小号购买历史
        idx = 0 # 使用局部变量 idx 作为索引
        perform_clicks = self.perform_clicks
        need_receive_mail = 0
        max_price_err_n = 8    # 连续10次价格错误就会触发返回配装机制
        price_err_n = 0
        last_refresh_time = time.time()

        self.set_auto_shit(task_params)

        local_loadouts = self.enabled_loadouts
        # # 如果用了自动挡屎，则要先把挡屎价改成 0
        # if self.auto_block_shit_option:
        #     for loadout in local_loadouts:
        #         loadout['max_price'] = 0

        if self.auto_sell:
            self.perform_clicks(self.coords_large["begin_game"])
            need_return, _ = self.ocr.recognize_price(self.coords_large["min_price_area"])
            if need_return:
                self.return_to_loadout()

        while not self.flag.stop and not self.game_crash():
            # 去大战场刷新
            if time.time() - last_refresh_time > self.refresh_interval:
                if not self.refresh_func(): break
                if not self.return_to_loadout():break
                # 重置计时器
                last_refresh_time = time.time()

            # 1. 获取当前要检查的配装方案
            loadout = local_loadouts[idx]

            # 2. 点击切换到该配装方案
            self.perform_clicks(loadout['click_coord'],delay=0.03,hold_duration = 0.02)
            self.safe_sleep(self.delay_loadout)

            # 3. 识别价格
            price, _ = self.ocr.recognize_price(self.monitor_price)

            if price != 0:
                # 只要能识别出来就重置计数器
                price_err_n = 0

                if self.auto_block_shit_option:
                    # 更新自动挡屎
                    if price >= loadout['min_price']:
                        self.update_block_shit_price(price)
                    else:
                        self._log(f"[抛弃] 价格 {price:,} 过低，判断为识别错误")

                    if not self.auto_block_shit:
                        self._log("[探测] 正在自动探测挡屎价")
                        idx = self.next_loop(idx)
                        continue
                    else:
                        loadout['max_price'] = max(0,self.auto_block_shit + self.price_diff_real*self.bullet_quantity)
                        loadout['max_price'] = min(loadout['max_price'],self.auto_block_max*self.bullet_quantity)
                        if self.last_shit != self.auto_block_shit:
                            self._log(f"[探测] 当前挡屎价为 {loadout['max_price'] // self.bullet_quantity}",color='blue')
                        self.last_shit = self.auto_block_shit

            # 4. 判断价格
            loadout['max_price'] = price + 1
            if price > loadout['max_price']:    # 挡屎失效了，不看价格直接吃
                self._log(f"[跳过] 方案 {loadout['id']}: 价格 {price:,} 单价 {price//self.bullet_quantity}")
            elif price == 0:
                # 等于0肯定就是没识别到图像
                self._log(f"[警告] 方案 {loadout['id']}: 未识别到价格")
                price_err_n += 1
                if price_err_n >= max_price_err_n:
                    # 连续 max_price_err_n 次判别失误就回配装界面
                    self.return_to_loadout()
                if price_err_n % 13 ==0:
                    # 有可能配装的L卡没了
                    pyautogui.press('esc')
                    self.safe_sleep(1)
            elif price < loadout['min_price']:
                self._log(f"[抛弃] 方案 {loadout['id']}: 价格 {price:,} 过低，判断为识别错误")
            else:
                # 再次检测
                self.safe_sleep(0.3)
                price, _ = self.ocr.recognize_price(self.monitor_price)
                if 0 < price <= loadout['max_price']:
                    # 再次确认价格对不对
                    # 价格合适！尝试购买
                    self._log(
                        f"[低价] 方案 {loadout['id']}: 价格 {price:,} 单价 {price//self.bullet_quantity} "
                             f"在范围内，尝试用小号探测",color='blue')
                    # ===== 小号进行探测 =====
                    if not self.handle_small_account_probe():continue
                    # ======================
                    # 点击购买按钮
                    perform_clicks(self.buy_button_coord,delay=0.01,hold_duration = 0.01)
                    # 判断购买是否成功
                    success_code = self.tell_success_buy_v2()
                    if success_code >= 0:  # 购买成功
                        if self.flag.stop: break  # 断点
                        self._log(f"[成功] 成功购买方案 {loadout['id']}",color='green')
                        if not self.auto_sell:
                            self._log(f"[成功] 未抽选自动售卖，任务结束",color='green')
                            break
                        # if not self.safe_sleep(2.0):break  # 等买子弹过程结束
                        # # 有时候抢了一部分，需要判断一下是不是这种情况，需要再次判断有没有回到配装界面
                        # confirm_loadout, _ = self.image_processor.has_green(
                        #     self.image_processor.capture_region(self.coords_large["confirm_loadout"]),
                        #     threshold=200)
                        # if not confirm_loadout:  # 如果不在配装界面就按1下esc
                        if success_code == 1:
                            self._log(f"[成功] 检测出：子弹没吃满",color='green')
                            pyautogui.press('esc'), self.safe_sleep(0.5)
                        if need_receive_mail == 0:
                            # 每抢成功 self.receive_email_frq 次,领1次邮件
                            self.receive_email(),self.safe_sleep(0.5)      # 领邮件
                        need_receive_mail += 1
                        need_receive_mail %= self.receive_email_frq
                        # ===== 去仓库 =====
                        # if self.flag.stop: break  # 断点
                        # self.move_bullets_to_warehouse()
                        # ===== 卖子弹 =====
                        if self.flag.stop: break  # 断点
                        if not self.sell_bullets_v2(): break  # 卖失败直接停
                        self.safe_sleep(0.5)
                        # ===== 回配装进入下一次循环 =====
                        if self.flag.stop: break  # 断点
                        self.perform_clicks(self.coords_large['begin_game'], delay=0.3,hold_duration=0.1,times=2)
                        self.safe_sleep(1)
                        pyautogui.press('L'), self.safe_sleep(0.2)
                        pyautogui.press('L'), self.safe_sleep(0.8)
                    else:     # 没抢到
                        if self.flag.stop: break  # 断点
                        self._log(f"[失败] 方案 {loadout['id']}: 没抢到，继续...",color='blue')
                        self.safe_sleep(0.3)
                        pyautogui.press('esc'),self.safe_sleep(0.5)
                        pyautogui.press('L'),self.safe_sleep(0.2)
                else:
                    self._log(f"[警告] 识别到其他配装价格，如果频发请调高配装延迟",color='red')

            idx = self.next_loop(idx)

    def task_skin(self):
        """
        买皮肤的函数
        """
        self._log(f"[任务] 执行买皮肤", color='blue')
        # ================ 买皮肤配置 =====================
        task_params = self.task_params["skin_settings"]
        self.buy_times = task_params['buy_times']
        hold_duration = 0.03  # 按下左键的持续时间

        for buy_try in range(1,1 + self.buy_times):
            if self.flag.stop or self.game_crash():break
            self._log(f"当前为第 {buy_try} 次购买",color='blue')
            pyautogui.moveTo(*self.coords_large["buy_skin_click"],duration=0.5)   # 先移动到购买按钮
            can_buy = False
            buy_success = False

            while True:
                # 一直检测是不是变绿了
                if self.flag.stop or self.game_crash():break

                sc = self.image_processor.capture_region(self.coords_large["buy_skin_green"])  # 截图

                if self.image_processor.has_green(sc,verbose=self.test)[0]:
                    # 只要变绿就进入购买环节
                    self._log("时间到，尝试购买",color='green')
                    t1 = time.time()
                    while time.time()-t1 <= 5.0:
                        # 最多点击5s
                        pyautogui.mouseDown()
                        self.safe_sleep(hold_duration)
                        pyautogui.mouseUp()
                        sc = self.image_processor.capture_region(self.coords_large["buy_confirm_green"])  # 截图
                        if self.image_processor.has_green(sc,verbose=self.test)[0]:
                            # 说明进入页面了，点击购买
                            can_buy = True
                            break
                        else:
                            self.safe_sleep(0.02)

                    if can_buy:
                        pyautogui.moveTo(*self.coords_large["buy_confirm_click"],duration=0.1)   # 移动到确认按钮
                        t2 = time.time()
                        while time.time()-t2 <= 3.0:
                            pyautogui.mouseDown()
                            self.safe_sleep(hold_duration)
                            pyautogui.mouseUp()
                            sc = self.image_processor.capture_region(self.coords_large["monitor_text"])
                            if self.image_processor.has_green(sc,verbose=self.test)[0]:
                                buy_success = True
                                break
                            else:
                                self.safe_sleep(0.02)

                    if buy_success:
                        self._log("购买成功", color='green')
                        # 买成功了，按两下esc，然后刷新一下
                        self.safe_sleep(2.5)
                        pyautogui.press('esc'),self.safe_sleep(2.5)
                        pyautogui.press('esc'),self.safe_sleep(2.5)
                        self.perform_clicks(self.coords_large['refresh_button'], times=3)
                    else:
                        self._log("购买失败", color='green')
                        self.safe_sleep(2.5)
                        self.perform_clicks(self.coords_large['refresh_button'],times=3)
                    # 不管有没有成功，都要停下来
                    self.safe_sleep(2)
                    break

    def task_test(self):
        """用于测试"""
        # task_params = self.task_params["skin_settings"]

        self._log(f"[任务] 测试", color='blue')
        while not self.flag.stop:
            # self.set_has_exchange()
            # final_price, buy_amount = self.see_balance_v2(need_buy_amount=False)
            # self._log(f"{final_price}")
            self.set_has_exchange()
            self.see_balance_ocr()
            self.op_large.click(((1160,324)))
            self.safe_sleep(0.2)
            self.op_large.unlock_cursor()
            self.op_small.click(((1160,324)))
            # self.receive_email()
            # self.set_has_exchange()
            # self._log(f"{self.has_exchange}")
            # self.sell_bullets_v2()

            self.safe_sleep(1)

    def game_crash(self,stop = True)->bool:
        """
        看看游戏是不是崩溃了
        Args:
            stop: 是否停止游戏运行
        Returns:
            bool: 如果游戏崩溃了，返回 True
        """
        if not self.op_large.is_valid():
            self._log("[错误] 游戏崩溃了，终止",color='red')
            self.flag.stop = stop
            return True
        else:
            return False

    def move_bullets_to_warehouse(self):
        """把买到的子弹放进仓库里"""
        i = 0
        while i < 5:
            i+=1
            self.perform_clicks(self.coords_large['warehouse'], delay=0.1,times=2),self.safe_sleep(0.5+0.5*i)  # 点进仓库
            warehouse_green, _ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['warehouse_green']))
            if warehouse_green:
                self._log(f"[转移] 成功到仓库")
                self.safe_sleep(1)
                break
            else:
                self.perform_clicks(self.coords_large['begin_game'], delay=0.1, times=2)

            # 到这里确定已经进入仓库了
            # 第一次用 ctrl f 监测
            pyautogui.keyDown('ctrl'), self.safe_sleep(0.1)
            pyautogui.press('f'), self.safe_sleep(0.1)
            pyautogui.keyUp('ctrl')
            move_success,_ = self.tell_success_buy(self.coords_large['move_bullets'],
                                                   capture_duration_s = 1,
                                                   fps=20,
                                                   only_check_for_green=False,
                                                   save_all_frames=self.test,
                                                   )
            if move_success == 0:
                self._log(f"[转移] 成功将子弹转移到仓库")
                self.safe_sleep(0.5)
                break

            # 第二次用鼠标转移
            self.perform_clicks(self.coords_large['warehouse_ctrl_f'], delay=0.1, times=2)
            need_sell,_ = self.image_processor.find_all_item_slots_by_grid(
                self.image_processor.capture_region(self.coords_large['warehouse_check_bullets']),
                debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标
            if need_sell:
                self._log(f"[转移] 成功将子弹转移到仓库")
                self.safe_sleep(0.5)
                break
            else:
                self.safe_sleep(0.5)

    @staticmethod
    def append_to_log_file(filename:str, message:str):
        """
        将一条消息追加写入到指定的日志文件中。
        会自动创建日志文件夹（如果不存在）。

        Args:
            filename: 日志文件的路径，例如 "运行日志/成功.txt"
            message: 要写入的消息内容
        """
        try:
            # 1. 获取日志文件所在的目录
            log_dir = os.path.dirname(filename)

            # 2. 如果目录不存在，就创建它
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # 3. 使用 'a' (append) 模式打开文件，这会追加内容到文件末尾
            #    encoding='utf-8' 确保能正确处理中文字符
            with open(filename, 'a', encoding='utf-8') as f:
                # 4. 写入消息，并加上一个换行符
                f.write(message + '\n')

        except Exception as e:
            # 在实际应用中，处理文件写入错误是很重要的
            # 这里我们简单地打印到控制台，避免因为日志写入失败而导致主程序崩溃
            print(f"!!! 写入日志文件 '{filename}' 时发生错误: {e}")

    @timing_decorator("分析胸挂等位置耗时：{duration:.3f} s", logger.info)
    def analyze_bullets_range(self, image_np: np.ndarray, test: bool = False, transfer: bool = True) \
            -> dict[str,tuple[int,int,int,int]]:
        """
        分析单张库存图片。

        Args:
            image_np (np.ndarray): 输入的BGR格式图像，由cv2.imread()或类似方法读入。
            test (bool, optional): 是否为测试模式。如果为True, 会保存调试图片并输出日志。
            transfer (bool, optional): 是否转换输出格式。此功能留待用户实现。

        Returns:
            dict:
                例如: 如果采用转换，则输出  {'胸挂': (x,y,w,h)}
        """

        if image_np is None or image_np.size == 0:
            return {}

        img_height, img_width, _ = image_np.shape

        # --- 1. OCR识别 ---
        ocr_result = self.ocr.ocr_engine_ch.ocr(image_np, cls=False)

        # --- 2. 筛选和排序标签 ---
        found_labels = []
        if ocr_result and ocr_result[0]:    # ocr_result[0]表示第一张图片
            for line in ocr_result[0]:      # line 表示每个文本块的信息
                text = line[1][0]           # line[1]，包括识别内容和置信度，('识别出的文本', 0.985)
                box = line[0]               # line[0]，识别边框的角点坐标，[[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                for keyword in self.TARGET_KEYWORDS:
                    if keyword in text:
                        y_coords = [p[1] for p in box]
                        y_min, y_max = int(min(y_coords)), int(max(y_coords))

                        has_item = bool(
                            re.search(r'(\d+)\s*/', text) and int(re.search(r'(\d+)\s*/', text).group(1)) > 0)

                        found_labels.append({
                            "keyword": keyword, "has_item": has_item,
                            "box_y_min": y_min, "box_y_max": y_max
                        })
                        break

        found_labels.sort(key=lambda x: x["box_y_min"])

        # --- 3. 计算结果 ---
        analysis_results = {}
        image_with_boxes = image_np.copy() if test else None

        for i, current_label in enumerate(found_labels):
            # 计算每个区域的起始和终止高度
            y_start = current_label["box_y_max"] + 5
            # 对于终止条件，最后一个直接到图片底部，其他的都到上一个标签顶部
            if i + 1 < len(found_labels):
                y_end = found_labels[i + 1]["box_y_min"] - 5
            else:
                y_end = img_height

            dy = max(0, y_end - y_start)    # 高差

            # 更新结果字典,只记录有内容的部分
            # 由于卡包没有数字，一定不会被记录
            if current_label["has_item"]:
                analysis_results[current_label["keyword"]] = (y_start, dy)

            if test:
                # 绘制所有识别出的标签的红框
                cv2.rectangle(image_with_boxes, (10, current_label['box_y_min']), (250, current_label['box_y_max']),
                              (0, 0, 255), 2)
                # 只为有物品的区域绘制绿色内容框
                if current_label["has_item"]:
                    cv2.rectangle(image_with_boxes, (10, y_start), (img_width - 10, y_end), (0, 255, 0), 2)
                    cv2.putText(image_with_boxes, f"H:{dy}", (20, y_start + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                (0, 255, 0), 2)

        # --- 4. （可选）格式转换 ---
        if transfer and analysis_results:
            # 转换为绝对坐标
            for key, value in analysis_results.items():
                y1, dy = value
                relative = list(self.coords_large[key]) # 相对坐标
                relative[-1] = dy
                relative[1] = y1 + self.coords_large["sell_bullets_detect"][1]
                analysis_results[key] = relative

        # --- 5. （可选）保存调试图片和日志 ---
        if test:
            debug_dir = 'debug'
            os.makedirs(debug_dir, exist_ok=True)
            save_path = os.path.join(debug_dir, f'analyze_bullets_range.png')
            cv2.imwrite(save_path, image_with_boxes)
            logger.info(f"调试图像已保存到: {save_path}")

        # --- 6. 输出最终处理 ---
        # 把背包放最后吧，实际顺序为 胸挂-安全箱-背包
        if "背包" in analysis_results.keys():
            value = analysis_results.pop("背包")
            analysis_results['背包'] = value

        return analysis_results

    def update_block_shit_price(self, price: int):
        """
        自动挡屎函数
        - 仅当 price > 0 时写入 auto_block_shit_list，并推进 auto_block_shit_index（环形缓冲）
        - 触发条件：
            1. 列表 10 项都 > 0
            2. 连续三次 price 相等（且 > 0）
        - 满足条件时，auto_block_shit = 列表中出现频率最高的值（平票时取最近的）
        注意：self.auto_block_shit只存储了原始的价格，没有转换成单价
        """
        # 用于连续相等检测
        if not hasattr(self, "_last_price"):
            self._last_price = None # 记录上次的价格
            self._streak = 0        # 记录重复的次数
        min_price = 0
        if price > min_price:
            # 写入环形缓冲区
            self.auto_block_shit_list[self.auto_block_shit_index] = price
            self.auto_block_shit_index = (self.auto_block_shit_index + 1) % len(self.auto_block_shit_list)

            # 连续相等计数
            if price == self._last_price:
                self._streak += 1
            else:
                self._streak = 1
            self._last_price = price

            # 触发条件
            cond_full_positive = (self.auto_block_shit_list[-1] > min_price)  # 最后一位大于min_price相当于全部大于了
            cond_three_equal = (self._streak >= 3)

            if cond_full_positive or cond_three_equal:
                if cond_full_positive:
                    positives = self.auto_block_shit_list
                else:
                    positives = self.auto_block_shit_list[:self.auto_block_shit_index]

                if positives:
                    freq = Counter(positives)       # 统计全部价格出现过的频率
                    max_count = max(freq.values())  # 出现最多的次数
                    candidates = {k for k, c in freq.items() if c == max_count} # 出现次数最多的价格
                    # 最近优先
                    for i in range(1, len(self.auto_block_shit_list) + 1):
                        pos = (self.auto_block_shit_index - i) % len(self.auto_block_shit_list)
                        v = self.auto_block_shit_list[pos]
                        if v in candidates:
                            self.auto_block_shit = v
                            break

    def handle_small_account_probe(self) -> bool:
        """
        在小号窗口执行探测性购买，并判断价格是否值得抢购。

        Returns:
            object: bool,如果价格低于期望值（值得抢）- True,否则返回 False
        """
        self.set_has_exchange()  # 重新识别有没有兑换
        if not self.op_large.unlock_cursor():
            pyautogui.keyDown('alt'), self.safe_sleep(0.03)
            pyautogui.press('tab'), self.safe_sleep(0.03)
            pyautogui.keyUp('alt'), self.safe_sleep(0.04)

        self._log(f"[探测] 成功切换到小号窗口")

        max_bullet_quantity = 100   # 最多的探测次数

        # 1. 初始化专门用于探测的 Tracker
        # 因为只在小号跑，所以 is_dual 设为 False，只关注价格判定
        tracker = HoardTracker(
            is_dual=False,
            target_qty=max_bullet_quantity,# 每次+1，就是最大探测次数
            min_price=1,
            max_price=self.target_price, # 目标好价
            buy_configs=self.BUY_MODE,
            confirm_n=1,                 # 滚仓探测通常只要出现一次好价就走
            idle_threshold=4,            # 对应原 err_count 休眠阈值
            slow_circle=13.0             # 对应原休眠时间
        )

        initial_balance = -1    # 初始余额
        # TODO 每次都要看余额，浪费

        # 2. 循环购买并检查价格

        accum_buy_quantity = 0     # 当前探测次数
        err_count = 0   # 连续 n 次价格不变话要先暂停处理
        err_cost = 0    # 连续 n 次消费为负数的话则终止运行
        target_loop_period = self.small_buy_circle

        for i in range(20):
            loop_start_time = time.perf_counter()  # 循环计时，用于保证周期一致
            # 记录初始价格
            if self.flag.stop: return False
            self.perform_clicks(self.small_click_buy)
            initial_balance,_ = self.see_balance(account_type = "small")  # 去上面看一下余额，并把鼠标移动回来

            work_duration = time.perf_counter() - loop_start_time  # 计算实际需要睡眠得时间
            sleep_needed = target_loop_period - work_duration

            if sleep_needed > 0:self.safe_sleep(sleep_needed)
            if initial_balance > 0:
                tracker.init_balance("small", initial_balance)  # 记录初始余额
                break
            else:
                # 识别成0，说明价格识别错了
                self._log(f"[警告] 探测没有识别到价格，若频发请增加看价时间",color='red')

        if initial_balance <= 0:
            self._log(f"[错误] 识别不到价格，停止运行",color='red')
            self.flag.stop = True

        while not self.flag.stop and not self.game_crash():
            if self.flag.stop:return False
            tracker.record_action("small")  # 记录本轮开始的时刻
            if tracker.is_finished:
                self._log(f"[警告] 已经 {max_bullet_quantity} 次探测不到低价。",color='green')
                break

            # 系统检查 (堆积休眠、仓库满等)
            if not self._hoard_check_system_errors(tracker):
                self.flag.stop = True
                return False

            # 确保小号购买数量正确
            for attempt in range(10):
                if self.flag.stop:return False
                buy_amount = self.check_buy_amount(self.small_buy_amount)
                if buy_amount == 31:
                    self.safe_sleep(0.3)
                    break
                else:
                    self.perform_clicks(self.small_buy32, hold_duration=0.03, delay=0.1, times=2)   # 拉到32
                    self.perform_clicks(self.small_buy_amount_minus, hold_duration=0.03, delay=0.1) # 减1
                    self.safe_sleep(0.6)

            self.perform_clicks(self.small_click_buy, **FAST_CLICK)    # 买一发子弹
            new_balance,_ = self.see_balance(account_type = "small")     # 去上面看一下余额，并把鼠标移动回来
            # pyautogui.moveTo(self.small_click_buy)  # 移动回购买按钮

            if not new_balance:
                # 识别成0，说明价格识别错了
                self._log(f"[警告] 探测没有识别到价格。",color='red')
            else:

                # 使用 tracker 统一计算单价
                cost = tracker.calc_cost(new_balance, 31) # 31 是探测数量
                # ----- 正常情况 -----
                if cost > 0:
                    tracker.record_success(cost, 1) # 滚仓计数以次数为准
                    tracker.update_balance(new_balance)     # 更新余额
                    # 不需要更新模式，限死为 small
                    if cost <= self.target_price:
                        self._log(f"[探测] 子弹单价: {cost}，价格合适，去大号买",color='blue')
                        return True # 这里不用睡，可以提前退出去大号买
                    else:
                        self._log(f"[探测] 子弹单价: {cost}")

                # ----- 交易行卡价格了 -----
                elif cost == 0:
                    tracker.record_frozen_price()

                # ----- 消耗小于0，肯定识别错了 -----
                elif cost < 0:
                    tracker.record_error_cost()
                    self._log(f"[警告] 价格识别有误，当前余额为 {new_balance},先前为 {tracker.current_balance}",color='red')
                    tracker.update_balance(new_balance)

            self.safe_sleep(tracker.get_wait_time())  # 用于保证周期一致

        self._log(f"[失败] 没有好价", color="red")
        return False

    @timing_decorator("看一次余额耗时：{duration:.3f} s", logger.info)
    def see_balance(self, account_type: str = "small", need_buy_amount: bool = True) -> tuple[int, int]:
        """
        统一的余额获取函数。
        通过监测价格变化实现高性能识别，并可选识别当前购买数量。
        识别后鼠标不会移走。

        Args:
            account_type (str): "small" 使用小号坐标, "large" 使用大号屯仓坐标。
            need_buy_amount (bool): 是否顺便识别当前的购买数量。

        Returns:
            tuple[int, int]: (识别到的余额, 购买数量)。
                             数量识别失败返回 0，不需要识别数量则返回 -1。
        """
        # 1. 环境准备：根据账户类型映射坐标和识别配置
        if account_type == "small":
            coords = self.coords_small
            hover_pos = coords['see_price1']        # 鼠标移动到余额显示区域
            price_area = coords["monitor_price"]    # 余额识别区域
            amount_area = self.small_buy_amount     # 检测当前购买数量
        else:
            # 大号（屯仓模式）坐标
            coords = self.coords_large_hoarding
            hover_pos = coords['see_price1']
            price_area = coords["monitor_price"]
            amount_area = self.large_buy_amount

        # 2. 鼠标预热：移动到触发价格显示的区域
        pyautogui.moveTo(hover_pos, duration=0)

        # 3. 高性能监控循环：检测价格数字的变化
        timeout_seconds = 0.40
        start_time = time.perf_counter()
        final_price = 0

        # 内部循环：不断截图并比对，直到价格发生变化或超时
        while time.perf_counter() - start_time < timeout_seconds:
            if self.flag.stop: return 0, -1

            # 使用识别数字的专用模式
            current_price, _ = self.template_engine_small.recognize_price(price_area)

            if current_price > 0:
                if final_price == 0:
                    # 记录第一次捕获到的有效价格
                    final_price = current_price
                elif current_price != final_price and (final_price - current_price < 1_500_000):
                    # 检测到价格跳变（说明服务器数据已同步到UI），锁定新价格
                    # 花费必须小于 150w。怀疑有时候会识别错位
                    # file = "./photo/tpl_test/"+get_timestamp_ms()+".png"
                    # file = file.replace(":","-").replace(",","-")
                    # self.image_processor.save_image(file,
                    #      self.image_processor.capture_region(price_area))
                    final_price = current_price
                    break

        # 4. 识别购买数量（可选）
        buy_amount = -1
        if need_buy_amount:
            # 子弹数量识别后的处理逻辑
            buy_amount = self.check_buy_amount(amount_area)

        return final_price, buy_amount

    @timing_decorator("看一次余额耗时：{duration:.3f} s", logger.info)
    def see_balance_ocr(self, account_type: str = "small") -> int:
        """
        统一的余额获取函数,OCR 识别。
        通过监测价格变化实现高性能识别，并可选识别当前购买数量。
        识别后鼠标不会移走。

        Args:
            account_type (str): "small" 使用小号坐标, "large" 使用大号屯仓坐标。

        Returns:
            int: 识别到的余额。
        """
        # 1. 环境准备：根据账户类型映射坐标和识别配置
        if account_type == "small":
            coords = self.coords_small
            hover_pos = coords['see_price1']        # 鼠标移动到余额显示区域
            price_area = coords["monitor_price"]    # 余额识别区域
            amount_area = self.small_buy_amount     # 检测当前购买数量
        else:
            # 大号（屯仓模式）坐标
            coords = self.coords_large_hoarding
            hover_pos = coords['see_price1']
            price_area = coords["monitor_price"]
            amount_area = self.large_buy_amount

        # 2. 鼠标预热：移动到触发价格显示的区域
        pyautogui.moveTo(hover_pos, duration=0)

        # 3. 高性能监控循环：检测价格数字的变化
        timeout_seconds = 0.40
        start_time = time.perf_counter()
        final_price = 0

        # 内部循环：不断截图并比对，直到价格发生变化或超时
        while time.perf_counter() - start_time < timeout_seconds:
            if self.flag.stop: return 0

            # 使用识别数字的专用模式
            current_price, _ = self.ocr.recognize_price(price_area)

            if current_price > 0:
                final_price = current_price
                break

        return final_price

    @timing_decorator("购买识别总耗时: {duration:.3f} s", logger.info)
    def tell_success_buy(self,
                         region_coords,
                         capture_duration_s: float = 3.0,
                         fps: int = 20,
                         initial_diff_thresh: float = 5.0,
                         stable_diff_thresh: float = 1.0,
                         min_stable_frames: int = 1,
                         save_all_frames: bool = False,
                         only_check_for_green = False,
                         save_folder: str = 'debug'
                         ) -> tuple[int, float]:
        """
        对于指定坐标位置，检测是不是有购买成功得弹窗出现

        Args:
            region_coords: 指定的截图区域，(x,y,w,h)
            capture_duration_s: 最长捕捉时间
            fps: 捕捉帧率
            initial_diff_thresh: 起始差别阈值
            stable_diff_thresh: 稳定差别阈值
            min_stable_frames: 最小得重复帧数
            save_all_frames: 是否保存每一帧
            only_check_for_green: 是否只检测绿色
            save_folder: 保存图片的文件夹路径

        Returns:
            object: (状态码,置信度)
        """
        logger.info("开始执行购买状态判断...")

        # 调用新的整合函数
        status, stable_frame_or_none = self.image_processor.capture_stable_frame(
            region_coords=region_coords,
            max_duration_s=capture_duration_s,
            fps=fps,
            initial_diff_thresh=initial_diff_thresh,
            stable_diff_thresh=stable_diff_thresh,
            min_stable_frames=min_stable_frames,
            check_for_green=True,  # 总是检查绿色
            green_threshold = 150,
            only_check_for_green = only_check_for_green,
            save_all_frames=save_all_frames,
            save_folder=save_folder,
        )

        logger.info(f"捕捉和等待结果: Status='{status}'")

        # --- 根据返回的状态处理 ---
        if status == "GREEN_FOUND":
            return 0,1.0  # 绿色直接成功
        elif status == "STABLE" or status == "TIMEOUT_STABLE":
            # 找到了稳定帧 (或超时但有候选稳定帧) -> 进行 OCR
            if stable_frame_or_none is None:
                logger.error("状态指示有帧但实际为 None，逻辑错误！")
                return -1,0.0

            logger.info("获取到稳定(或候选)帧，开始 OCR识别购买结果")
            try:
                processed = self.image_processor.preprocess_image(stable_frame_or_none,6)
                if self.test:
                    cv2.imwrite(r'debug\text_image.png', processed)  # 保存为 PNG 格式
                if processed is None or processed.size == 0:
                    logger.error("预处理后的图像为空")
                    return -1,0.0
                result, confidence = self.ocr.recognize_text(processed)

                # 解析 OCR 结果
                if not self.has_chinese(result):
                    logger.warning("OCR 购买结果不含中文")
                    return -1,confidence
                elif self.is_str1_in_str2("成功", result):
                    return 0,confidence
                elif self.is_str1_in_str2("哈夫币空间", result):
                    return 1,confidence
                elif self.is_str1_in_str2("失败", result):
                    return 2,confidence
                else:
                    logger.warning(f"OCR 结果 '{result}' 未匹配已知状态。")
                    return -1,confidence
            except Exception as e:
                logger.error(f"OCR 或结果解析时异常: {e}", exc_info=True)
                return -1,0.0
            finally:
                del stable_frame_or_none
                if 'processed' in locals(): del processed
                gc.collect()
        elif status in ["TIMEOUT_UNSTABLE", "NO_FRAMES", "ERROR"]:
            # 超时未变化、没捕捉到帧或出错，都视为未知状态
            logger.warning(f"因状态 '{status}'，无法判断购买结果。")
            return -1,0.0
        else:
            # 未知状态字符串，理论上不应发生
            logger.error(f"收到未知的状态码: '{status}'")
            return -1,0.0

    @staticmethod
    def is_str1_in_str2(str1: str, str2: str) -> bool:
        """
        检查字符串 str1 中是否有任何一个字符出现在字符串 str2 中。
        """
        return any(c in str2 for c in str1)

    def is_buy_in_trade(self)->bool:
        """
        检查是不是在交易行购买界面
        原理：检测右上角 "购买数" 左边的灰色矩形

        Returns:
            bool, 是否在交易行购买界面
        """

        # 检测右上角 "购买数" 左边的灰色矩形
        is_gray,_ = self.image_processor.has_gray(
            self.coords_small['buy_in_trade_gray'],
            threshold=60,
        )

        return is_gray

    @staticmethod
    def has_chinese(text: str) -> bool:
        """
        检查字符串中是否包含汉字。
        Args:
            text: 要检查的字符串。
        Returns:
            bool: 如果包含汉字，返回 True；否则返回 False。
        """
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True  # 找到汉字，立即返回 True
        return False  # 遍历完所有字符，没有找到汉字


    # @timing_decorator("点击耗时: {duration:.3f} s", logger.info)
    def perform_clicks(
            self,
            click_sequence: list[list] | list | tuple,
            times: int = 1,
            delay: float = 0.02,
            move_duration: float = 0,
            hold_duration: float = 0.02,
            interval: float = 0.1
    ) -> bool:
        """
        执行一系列完全可预测且坐标精确的点击操作。
        经测试，delay 和 hold_duration都为0.01容易买到，保守取0.02

        Args:
            click_sequence: 点击坐标, (x, y) 或 [(x1, y1), (x2, y2)]
            times: 在每个坐标点上重复点击的次数。
            delay: 移动到目标位置后，在开始点击前停留多久。
            move_duration: 鼠标移动到目标的精确耗时（秒）。
            hold_duration: 模拟按住鼠标的精确时长（秒）。
            interval: 多次点击之间的精确间隔时间（秒）。

        Returns:
            bool: 如果所有点击操作都成功执行，则返回True，否则返回False。
        """
        # 1. 标准化输入
        if isinstance(click_sequence[0], int):
            click_sequence = [click_sequence]

        try:
            # 2. 遍历每一个需要点击的坐标点
            for x, y in click_sequence:

                # 3. 精确时间的鼠标移动
                pyautogui.moveTo(x, y, duration=move_duration)

                # 4. 执行指定的`delay`参数
                if not self.safe_sleep(delay):return False

                # 5. 在该精确点上执行 `times` 次点击
                for i in range(times):
                    # a. 执行精确时长的按键
                    pyautogui.mouseDown()
                    self.safe_sleep(hold_duration)
                    pyautogui.mouseUp()

                    # b. 如果不是最后一次点击，执行精确的点击间隔
                    if i < times - 1:
                        if not self.safe_sleep(interval): return False

            return True

        except Exception as e:
            logger.error(f"点击操作失败: {str(e)}")
            return False

    def capture_near_mouse_pointer(self,position:tuple|list,dx:int=10,dy:int=10)-> ndarray:
        """
        返回以 position 为中心，左右扩大dx，上下扩大dy的截图
        """
        return self.image_processor.capture_region(position[0] - dx, position[1] - dy, 2 * dx, 2 * dy)

    def sell_bullets(self) -> bool:
        """
        负责调度，确保出售任务的完成。
        它会先尝试上架第一批物品，如果需要，再等待并尝试上架第二批。
        """
        self._log(f"[出售] 开始出售子弹",color='blue')

        # --- 1. 定义通用参数和进入交易行 ---
        delay, sleep, hold_duration = 0.4, 0.4, 0.15
        max_attempts1 = 10   # 最多卖5次子弹
        max_attempts2 = 30  # 为每次上架任务设定的最大重试次数
        if not self.navigate_to_sell_page():
            self._log("[错误] 多次尝试仍无法进入交易行出售页面，程序中止",color='red')
            return False

        # --- 2. 尝试执行上架任务，带重试逻辑 ---
        for batch_num in range(1,max_attempts1+1):
            if self.flag.stop: return False

            # 寻找下一个要售卖的物品
            pyautogui.moveTo(self.coords_large['trade']), self.safe_sleep(0.1)  # 移走鼠标，防止干扰截图
            need_sell, sell_coord = self.image_processor.find_all_item_slots_by_grid(
                self.image_processor.capture_region(self.coords_large['check_bullets']),
                debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标

            if not need_sell:
                # 再次监测是不是确实不用卖了
                pyautogui.moveTo(self.coords_large['trade']), self.safe_sleep(0.2)  # 移走鼠标，防止干扰截图
                need_sell, sell_coord = self.image_processor.find_all_item_slots_by_grid(
                    self.image_processor.capture_region(self.coords_large['check_bullets']),
                    debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标
                if not need_sell:
                    # 不用卖了，可以结束了
                    self._log("[出售] 仓库中已无待售物品，流程结束",color='blue')
                    return True

            # ===== 开始卖 =====
            # 计算物品的绝对坐标
            sell_coord = (self.coords_large['check_bullets'][0] + sell_coord[0],
                          self.coords_large['check_bullets'][1] + sell_coord[1])

            batch_sell_successful = False   # 先默认本次售卖失败
            for attempt in range(1,max_attempts2+1):
                if self.flag.stop: return False
                self._log(f"[出售] 批次{batch_num} 第 {attempt}/{max_attempts2} 次尝试执行")
                sell_successful, needs_a_second_run = self.sell_bullet_once(sell_coord,delay, sleep, hold_duration,method=1)
                pyautogui.moveTo(self.coords_large['trade']), self.safe_sleep(0.1)
                if self.flag.stop: return False
                if sell_successful:
                    # 这次卖成功了，进入下一次尝试
                    batch_sell_successful = True
                    self.safe_sleep(1.5)
                    if needs_a_second_run:self.safe_sleep(1)  # 暂停一会，卖下一波
                    break
                else:
                    # 回到交易页面
                    green, _ = self.image_processor.has_green(
                        self.image_processor.capture_region(self.coords_large["trade_green"]))
                    if not green:
                        pyautogui.press('esc'),self.safe_sleep(0.5)
                    # 这次失败了,先监测一下是不是识别错了,需要停止
                    pyautogui.moveTo(self.coords_large['trade']), self.safe_sleep(0.1)  # 把鼠标移走
                    need_sell,_ = self.image_processor.find_all_item_slots_by_grid(
                        self.image_processor.capture_region(self.coords_large['check_bullets']),
                        debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标
                    if not need_sell:
                        # 确定，不需要卖了
                        batch_sell_successful = True
                        break
                    else:
                        self._log(f"[警告] 批次 {batch_num} 第 {attempt} 次上架失败，稍后重试",color='orange')
                        self.safe_sleep(1.5)

            if not batch_sell_successful:
                # 卖10次都没卖出去
                self._log(f"[错误] 批次 {batch_num} 多次尝试仍无法上架，程序中止",color='red')
                return False

    def copy_text_to_input(self,
                           box_pos: tuple[int, int],
                           target_text: str,
                           click_delay: float = 0.1) -> bool:
        """
        智能输入文本（替代 OCR 检测的轻量级方案）。
        流程：点击 -> 全选 -> 复制 -> 校验 -> (一致则跳过 / 不一致则覆盖输入)
        作用：防止重复输入相同的文本，触发游戏内高延迟的联想搜索或网络刷新。

        Args:
            box_pos: 输入框在窗口中的相对坐标 (x, y)
            target_text: 想要输入的目标文本
            click_delay: 点击输入框后等待UI响应的时间

        Returns:
            bool: 操作是否成功
        """
        if not self.is_valid():
            logger.error("未绑定有效窗口，无法执行智能输入。")
            return False

        # 1. 点击输入框获取焦点
        self.click(box_pos)
        time.sleep(click_delay)

        # 2. 清空系统剪贴板，防止读到上一次复制的历史残留数据
        self.set_clipboard_content("")

        # 3. 模拟全选和复制
        InputSimulator.press_hotkey("ctrl a c")

        # 4. 获取刚刚复制的内容
        current_text = self.get_clipboard_content()

        # 5. 比对内容 (使用 strip() 去除可能带有的 \r\n 等隐形字符)
        if current_text and current_text.strip() == target_text.strip():
            logger.info(f"输入框已有目标内容 '{target_text}'，跳过输入以规避重新加载。")
            # 按右方向键取消全选的蓝色高亮状态，防止后续误触键盘删掉文本
            InputSimulator.press_hotkey("right")
            return True

        # 6. 如果内容为空，或者不一致，执行覆盖输入
        # 此时输入框还处于 Ctrl+A 的全选蓝底状态，直接打字会完美覆盖！
        current_display = current_text.strip() if current_text else "空"
        logger.info(f"输入框当前内容为 '{current_display}'，执行覆盖输入: '{target_text}'")

        if not self.typewrite(target_text):
            logger.error("注入目标文本失败。")
            return False

        return True

    # def copy_text_to_input(self,
    #                        position_coords: list|tuple,
    #                        input_text:str='hello',
    #                        is_num:bool=True,
    #                        detect_coord:list|tuple|None=None)->bool:
    #     """
    #     复制文本到输入框里面
    #     Args:
    #         position_coords: 鼠标点击输入框的坐标
    #         input_text: 要复制进去的文本
    #         is_num: 输入的是不是纯数字
    #         detect_coord: 可选，检测输入框文本是否一致
    #
    #     Returns:
    #         object: bool，是否执行成功
    #     """
    #     # 标准化处理
    #     input_text = input_text.replace('。', '.')
    #     input_text = ' '.join(input_text.split())
    #
    #     pyperclip.copy(input_text)
    #
    #     input_text_plain = input_text.lower().replace(' ', '').replace('.', '')
    #     result = False
    #     if detect_coord and len(detect_coord) == 4:
    #         # 需要重复检测的
    #         for i in range(10):
    #             if self.flag.stop: return False
    #             # 先进行识别，如果相同则不需要复制
    #             if is_num:
    #                 text, _ = self.ocr.recognize_price(detect_coord)
    #                 text = str(text)
    #             else:
    #                 image = self.image_processor.capture_region(detect_coord)
    #                 image = self.image_processor.preprocess_image(
    #                     image,
    #                     scale_factor = 5,
    #                 )
    #                 text, _ = self.ocr.recognize_text(image,need_preprocess=False)
    #                 if self.test:
    #                     self._log(f"输入文本为：{input_text}，识别为：{text}")
    #
    #                 text = text.lower().replace(' ','').replace('.', '').replace('0','o')
    #                 if self.test:
    #                     self._log(f"处理文本为：{input_text_plain}，处理识别为：{text}")
    #             if self.flag.stop: return False
    #             if text == input_text_plain:
    #                 # 说明输入跟预期相等了
    #                 result = True
    #                 break
    #             else:
    #                 # 一直输入直到相等
    #                 if self.flag.stop: break
    #                 self.perform_clicks(position_coords, delay=0.1, hold_duration=0.1)
    #                 pyautogui.keyDown('ctrl')   , self.safe_sleep(0.10+0.05*i)
    #                 pyautogui.press('a')        , self.safe_sleep(0.40+0.10*i)
    #                 pyautogui.press('v')        , self.safe_sleep(0.10+0.05*i)
    #                 pyautogui.keyUp('ctrl')     , self.safe_sleep(0.15+0.05*i)
    #                 pyautogui.press('enter')    , self.safe_sleep(0.15+0.05*i)
    #                 pyautogui.press('enter')    , self.safe_sleep(0.15+0.05*i)
    #
    #                 if is_num:
    #                     # 数字的情况可以额外输入一遍
    #                     text, _ = self.ocr.recognize_price(detect_coord)
    #                     text = str(text)
    #                     if text == input_text_plain:
    #                         # 说明输入跟预期相等了
    #                         result = True
    #                         break
    #                     else:
    #                         self.perform_clicks(position_coords, delay=0.1, hold_duration=0.1)
    #                         pyautogui.keyDown('ctrl'),  self.safe_sleep(0.10 + 0.05 * i)
    #                         pyautogui.press('a'),       self.safe_sleep(0.40 + 0.10 * i)
    #                         pyautogui.keyUp('ctrl'),    self.safe_sleep(0.15 + 0.05 * i)
    #                         pyautogui.typewrite(input_text_plain,interval=0.1+0.05*i)
    #                         pyautogui.press('enter'),   self.safe_sleep(0.15 + 0.05 * i)
    #                         pyautogui.press('enter'),   self.safe_sleep(0.15 + 0.05 * i)
    #     else:
    #         self.perform_clicks(position_coords, delay=0.1, hold_duration=0.1)
    #         pyautogui.keyDown('ctrl'), self.safe_sleep(0.1)
    #         pyautogui.press('a'), self.safe_sleep(0.4)
    #         pyautogui.press('v'), self.safe_sleep(0.1)
    #         pyautogui.keyUp('ctrl'), self.safe_sleep(0.15)
    #         pyautogui.press('enter'), self.safe_sleep(0.15)
    #         pyautogui.press('enter'), self.safe_sleep(0.10)
    #         result = True
    #
    #     if result:
    #         return True
    #     else:
    #         self._log(f"[错误] 无法正确输入文本，程序已终止",color='red')
    #         self.flag.stop = True
    #         return False


    def sell_bullets_v2(self) -> bool:
        """
        直接在仓库里卖，负责调度，确保出售任务的完成。
        它会先尝试上架第一批物品，如果需要，再等待并尝试上架第二批。
        """
        self._log(f"[出售] 开始出售子弹",color='blue')
        delay, sleep, hold_duration = 0.4, 0.4, 0.05
        max_attempts1 = 20   # 最多卖5次子弹
        max_attempts2 = 30   # 为每次上架任务设定的最大重试次数
        batch_num = 1        # 当前是第几次售卖

        # 去仓库页面
        if not self.navigate_to_warehouse():
            return False

        analyze_bullets = None
        for i in range(5):
            self.safe_sleep(0.4)
            # 分析当前所在的界面
            analyze_bullets = self.analyze_bullets_range(
                self.image_processor.capture_region(self.coords_large['sell_bullets_detect']),
                test=self.test,
            )
            if analyze_bullets:break

        # 如果为空直接退出，不进入循环
        if not analyze_bullets:
            self._log("[出售] 仓库中无待售物品", color='blue')
            return True

        needs_a_second_run = True   # 默认，只能确定不需要售卖了才能退出
        analyze_failed = 0      # 连续分析位置错误得次数
        while batch_num<=max_attempts1:
            skip_to_next = False # 用于跳过最后的检验
            if self.flag.stop: return False

            if not analyze_bullets:
                analyze_failed += 1
                if not needs_a_second_run:
                    # 确保确实不需要卖才退出
                    self._log("[出售] 仓库中已无待售物品，流程结束",color='blue')
                    return True
                else:
                    if analyze_failed > 0 and analyze_failed %3 ==0:
                        # 这个情况肯定是游戏下滚了
                        self.perform_clicks(self.coords_large['begin_game'], delay=0.1, times=2)  # 点开始游戏
                        self.safe_sleep(1.5)
                        self.perform_clicks(self.coords_large['warehouse'], delay=0.1, times=2)  # 点开始游戏
                        self.safe_sleep(1.5)
                        self._log('[出售] 重新识别')
                    # 如果上次循环说明了还需要卖，则识别一次重新运行
                    analyze_bullets = self.analyze_bullets_range(
                        self.image_processor.capture_region(self.coords_large['sell_bullets_detect']),
                        test=self.test,
                    )
                    continue
            else:
                # 进入这个分支说明有东西要卖的
                # 只要有子弹就一直卖
                analyze_failed = 0      # 重置连续失败计数器
                self.safe_sleep(0.3)
                keys = list(analyze_bullets.keys())
                # 寻找下一个要售卖的物品
                # 这里采用默认参数，因为识别错误的前提是格子上面有东西，因此在点击之前已经卖了
                need_sell, sell_coord = self.image_processor.find_all_item_slots_by_grid(
                    self.image_processor.capture_region(analyze_bullets[keys[0]]),
                    # detection_thresholds = (0.1,20),
                    debug=self.test,method=-1)  # 记录是否需要售卖以及售卖时相对坐标

                if not need_sell:
                    # 再次监测是不是确实不用卖了,这次宽松一些
                    need_sell, sell_coord = self.image_processor.find_all_item_slots_by_grid(
                        self.image_processor.capture_region(analyze_bullets[keys[0]]),
                        debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标

                    # 如果确实是没发现子弹，但是第一个是背包
                    if not need_sell and keys[0] == "背包":
                        # 处理背包太大的情况，如果背包有东西但是没识别到，说明需要下滚
                        pyautogui.moveTo(self.coords_large['sell_bullets_slip']), self.safe_sleep(0.2)
                        pyautogui.scroll(-600), self.safe_sleep(1.5)
                        analyze_bullets = self.analyze_bullets_range(
                            self.image_processor.capture_region(self.coords_large['sell_bullets_detect']),
                            test=self.test,
                        )
                        continue
                    elif not need_sell:
                        # 不用卖了，可以结束了
                        self._log("[出售] 仓库中已无待售物品，流程结束",color='blue')
                        return True

                # ===== 开始卖 =====
                # 计算物品的绝对坐标
                sell_coord = (analyze_bullets[keys[0]][0] + sell_coord[0],
                              analyze_bullets[keys[0]][1] + sell_coord[1])

                batch_sell_successful = False  # 先默认本次售卖失败
                sell_failed = 0     # 连续售卖失败的次数
                for attempt in range(1, max_attempts2 + 1):
                    if self.flag.stop: return False
                    self._log(f"[出售] 批次 {batch_num} 第 {attempt}/{max_attempts2} 次尝试执行")
                    sell_successful, needs_a_second_run,status = (
                        self.sell_bullet_once(sell_coord, delay, sleep,hold_duration,method=2))
                    # ！！！！！ 只把  needs_a_second_run = False 作为出售完得唯一判断标准 ！！！！！
                    if status == "未能进入上架页面":
                        sell_failed += 1
                    else:
                        sell_failed = 0
                    if sell_successful: # 出售成功
                        if needs_a_second_run: # 还需要继续卖
                            # 这次卖成功了，进入下一次尝试
                            batch_sell_successful = True
                            # 重新识别
                            t = time.perf_counter()
                            self.image_processor.capture_stable_frame(
                                self.coords_large['sell_success_green'],
                                max_duration_s=5.0,
                                fps=10,
                                green_threshold=200,
                                check_for_green=True,
                                only_check_for_green=True,
                            )
                            self.safe_sleep(1.3)
                            analyze_bullets = self.analyze_bullets_range(
                                self.image_processor.capture_region(self.coords_large['sell_bullets_detect']),
                                test=self.test,
                            )
                            self.safe_sleep(2.2 - (time.perf_counter() - t))    # 暂停一会，卖下一波
                            break
                        else:
                            self._log("[出售] 仓库中已无待售物品，流程结束",color='blue')
                            self.safe_sleep(1.0)
                            return True
                    else:   # 出售失败得情况，
                        if sell_failed >0 and sell_failed %2 ==0:
                            # 连续n次进不去交易行售卖,估计游戏出bug了，重进一下仓库，并重新识别
                            self.perform_clicks(self.coords_large['begin_game'], delay=0.1, times=2) # 点开始游戏
                            self.safe_sleep(1.5)
                            self.perform_clicks(self.coords_large['warehouse'], delay=0.1, times=2) # 点开始游戏
                            self.safe_sleep(1)
                            self._log('[出售] 重新识别，切换到下个批次')
                            analyze_bullets = self.analyze_bullets_range(
                                self.image_processor.capture_region(self.coords_large['sell_bullets_detect']),
                                test=self.test,
                            )
                            skip_to_next = True
                            break   # 打破内层循环，开始新的一轮尝试售卖
                        else:
                            self.safe_sleep(1.0)
                            need_sell, _ = self.image_processor.find_all_item_slots_by_grid(
                                self.image_processor.capture_region(analyze_bullets[keys[0]]),
                                detection_thresholds=(0.1, 20),
                                debug=self.test)  # 记录是否需要售卖以及售卖时相对坐标
                            if not need_sell:
                                # 实际上需要卖，但是识别不对了，要做特殊处理
                                self._log(f"[警告] 当前批次无法完成，启用下个批次",color='orange')
                                self.safe_sleep(2.0)
                                skip_to_next = True
                                break  # 打破内层循环，开始新的一轮尝试售卖
                            else:
                                self._log(f"[警告] 批次 {batch_num} 第 {attempt} 次上架失败，稍后重试",color='orange')
                                self.safe_sleep(2.0)

                if not batch_sell_successful and not skip_to_next:
                    # 卖10次都没卖出去
                    self._log(f"[错误] 批次 {batch_num} 多次尝试仍无法上架，程序中止",color='red')
                    return False

                batch_num += 1

    def sell_bullet_once(self, position_coords: tuple, delay: float = 0.1, sleep: float=0.1,
                         hold_duration: float=0.05, method :int= 1) -> tuple[bool, bool, str]:
        """
        执行一次上架尝试，并返回明确的结果。
        Args:
            position_coords: 购买物品的绝对坐标
            delay: 鼠标点击前得延迟
            sleep: 统一得睡眠时间
            hold_duration: 鼠标按下得持续时间
            method: 购买方法，1表示直接点击出售，2表示用 alt+d 出售
        Returns:
            tuple[bool, bool, str]:
                - 本次上架操作是否成功完成。
                - 是否需要再上架一次（仅在成功时有意义）。
                - 记录状态
        """
        sell_all = self.coords_large["sell_bullet2"]
        sell_price = self.coords_large["sell_price"]    # 三个柱子的坐标
        sell_bullet_amount = self.coords_large["sell_bullet_amount"]    # 卖的数量

        # 1. 尝试进入出售页面 (只试一次)
        if method == 1:
            self.perform_clicks(position_coords, delay=delay, hold_duration=hold_duration, times=1) # 点子弹，进入售卖页面
        else:
            # 直接在背包里卖
            pyautogui.moveTo(position_coords), self.safe_sleep(0.3)
            pyautogui.keyDown('alt'), self.safe_sleep(0.1)
            pyautogui.press('d'), self.safe_sleep(0.1)
            pyautogui.keyUp('alt')
            pyautogui.moveTo(self.coords_large["sell_page_click"])
            self.image_processor.capture_stable_frame(
                self.coords_large['sell_page_detect'],
                max_duration_s=3.0,
                fps=10,
                min_stable_frames=5,
                check_for_green=False,
                save_all_frames=self.test,
            ) # 等上架的页面出来并稳定
            # 检测游戏是不是卡了，没打开交易页面
            # 这里检测仓库的绿色，如果仓库没有绿色说明进入上架页面了
            is_in_stock_page = not self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['warehouse_green']))[0]

            if not is_in_stock_page:
                self._log("[失败] 未能进入上架页面", color='orange')
                # 失败不需要额外操作，直接返回失败状态
                return False, False, "未能进入上架页面"

            # ===== 到这里说明已经进入一级菜单了 ======
            self.perform_clicks(self.coords_large["sell_page_click"]),self.safe_sleep(0.5)

        # 检测是不是在出售页面
        t = time.perf_counter()
        is_in_sell_page = False
        while time.perf_counter() - t <= 3.0:
            # 监测是不是进入售卖界面了
            if self.flag.stop: return False, False, "被终止"  # 任务中断
            is_in_sell_page, _ = self.image_processor.has_yellow(
                self.image_processor.capture_region(self.coords_large['sell_yellow']))
            if is_in_sell_page:
                self.safe_sleep(0.5)
                break
            self.safe_sleep(0.2)
            self.perform_clicks(self.coords_large["sell_page_click"])   # 重新点

        if not is_in_sell_page:
            self._log("[失败] 未能进入出售页面",color='orange')
            # 失败不需要额外操作，直接返回失败状态
            pyautogui.press('esc')
            return False, False, "未能进入出售页面"

        # --- 从这里开始，我们确认已经成功进入了出售页面 ---
        try:
            attempt_can_sell = False     # 这次能不能卖出去
            needs_a_second_run = False   # 默认一次就能卖完
            price_list = [0] * 5

            for i,amount in enumerate(sell_bullet_amount):
                if i>0:needs_a_second_run = True
                # 三个数量都去试一下,判断是否卖出去
                self.perform_clicks(amount, times=2, delay=0.1)  # 拉满子弹
                price_list[i] = self.ocr.recognize_price(sell_price[i],remove_icon=True)[0]    # 拉数量的同时识别价格
                if self.flag.stop: return False, False, "被终止"
                attempt_can_sell, _ = self.image_processor.has_green(
                    self.image_processor.capture_region(self.coords_large['sell_green']))
                if attempt_can_sell:break   # 这次能卖出去了

            if attempt_can_sell:
                # 有时候会 0/0 但是按钮也是绿色的
                # 如果交易行卡 0/0 bug，直接返回
                trade_full = self.ocr.recognize_price(self.coords_large['sell_bullet_amount_check'])
                if trade_full[1]>0.8 and trade_full[0] == 0:
                    pyautogui.press('esc')
                    self._log('[失败] 交易行满了')
                    return False, False, "出 0/0 bug了"
            else:
                pyautogui.press('esc')
                self._log('[失败] 交易行满了')
                return False, False, "交易行满了"

            # 4. 计算价格
            for i in range(3):
                if price_list[i] == 0:
                    price_list[i] = self.ocr.recognize_price(sell_price[i], remove_icon=True)[0]

            # self._log(f"<font color='blue'>[价格] 前三个柱子价格为:{price_list[0]},{price_list[1]},{price_list[2]}</font>")

            if self.flag.stop: return False, False, "被终止"
            dp1 = price_list[1] - price_list[0]
            dp2 = price_list[2] - price_list[1]

            price_weight = {0:1,1:2,2:3}    # 分别表示市场价卖，低一档和低两档卖

            if dp1==dp2 and dp1>0:    # 正常情况
                price_sell = price_list[1]-price_weight[self.auto_sell_price]*dp2
            else:   # 第一个价格异常，应该抛弃
                if dp2>0 and price_list[1]>0:   # 说明价格2 和 价格3 识别正确了
                    price_sell = price_list[2]-price_weight[self.auto_sell_price]*dp2
                else:
                    # 如果识别不对，则任务失败
                    self._log(f"[警告] 价格识别有误，重试",color='orange')
                    pyautogui.press('esc')
                    return False, False, "价格识别有误"

            price_sell = max(price_sell, self.min_sell_price)   # 防止畜生
            # 5. 上架
            self.safe_sleep(0.5*sleep)

            # 点击输入框，复制进去
            res = InputSimulator.smart_cover(
                pos=sell_all[4],
                content=str(price_sell),
            )
            # res = self.copy_text_to_input(
            #     position_coords= sell_all[4],
            #     input_text = str(price_sell),
            #     is_num = True,
            #     detect_coord = self.coords_large["sell_price_input"]
            # )
            self.safe_sleep(0.5*sleep)
            if not res: return False, False, "价格输入有误"

            self.perform_clicks(sell_all[5], delay=delay,hold_duration = hold_duration)         # 出售

        except Exception as e:
            self._log(f"[错误] 在上架过程中出错: {e}",color='red')
            pyautogui.press('esc')  # 出错时尝试清理界面
            return False, False , "上架过程中出错"

        # 如果所有步骤都顺利完成
        self._log(f"[成功] 上架价格: {price_sell}",color='green')
        return True, needs_a_second_run,"成功"

    def receive_email(self) -> bool:
        """领邮件"""
        # 检测用不用领邮件
        # ----- 先识别右上角有没有感叹号 -----
        mail_region = self.image_processor.capture_region(self.coords_large['mail_region'])
        has_yellow,_ = self.image_processor.has_yellow(mail_region)
        if not has_yellow:
            # self._log(f"[邮件] 不需要领邮件",color='blue')
            return True

        self._log(f"[邮件] 检测到需要领邮件", color='blue')
        self.perform_clicks(self.coords_large['mail'][0],delay=0.15,times=2), self.safe_sleep(0.3)   # 点开邮件
        # ----- 狂点邮件 -----
        step1:bool = False
        need_wait:bool = False  # 是不是需要切换页面
        for i in range(20):
            if self.flag.stop:break
            # 确保点开领邮件了
            mail_green,_ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['mail_green']))

            if mail_green:
                if need_wait:
                    self.safe_sleep(0.3)
                else:
                    self.safe_sleep(0.1)
                step1 = True
                break
            else:
                need_wait = True
                self.perform_clicks(self.coords_large['mail'][1], times=1)  # 点开交易行邮件
                self.safe_sleep(0.1+i*0.03)
        if not step1:
            self._log(f"[邮件] 无法点开邮件", color='red')
            return self.navigate_to_main_page()

        # ----- 看看右下角有没有领取 -----
        mail_green_rb, _ = self.image_processor.has_green(
            self.image_processor.capture_region(self.coords_large['mail_green_rb']))
        if not mail_green_rb:   # 不需要领取
            return self.navigate_to_main_page()

        # ----- 点击领取全部 -----
        step2: bool = False
        for i in range(30):
            if self.flag.stop:break
            self.perform_clicks(self.coords_large['mail'][2], delay=0.1, times=2)  # 领邮件
            # 确保点开领取全部了
            mail_green,_ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['mail_green']))
            if mail_green:
                self.safe_sleep(0.2)
            else:
                step2=True
                break
        if not step2:
            self._log(f"[邮件] 无法领取全部邮件", color='red')
            return self.navigate_to_main_page()

        # ----- 跳过 -----
        for i in range(20):
            if self.flag.stop:break
            pyautogui.press("space")
            # 确保点开领邮件了
            mail_green,_ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['mail_green']))
            if mail_green:
                break
            else:
                self.safe_sleep(0.2)

        pyautogui.press('esc'),self.safe_sleep(0.1)
        self._log(f"[邮件] 邮件领取完毕",color='blue')
        return self.navigate_to_main_page()

    def navigate_to_main_page(self) -> bool:
        """监测是不是在大厅，如果不在则返回大厅"""
        in_main_page = False
        for i in range(10):
            # 最多监测 20 次
            main_page_green = self.image_processor.wait_for_color(
                self.coords_large['main_page_green'],
                color_name = "green",
                delay = 0,
                timeout_s = 0.5,
                threshold = 220,
                fps = 30,
            )

            if main_page_green:
                in_main_page = True
                break
            else:
                pyautogui.press('esc')
                if not self.safe_sleep(0.1+i*0.1):return False

            #
            # main_page_green,_ = self.image_processor.capture_stable_frame(
            #     self.coords_large['main_page_green'],
            #     max_duration_s = 0.5,
            #     fps = 30,
            #     only_check_for_green = True,
            #     green_threshold = 220,
            # )
            # if main_page_green == "GREEN_FOUND":
            #     in_main_page = True
            #     break
            # else:
            #     pyautogui.press('esc')
            #     if not self.safe_sleep(0.1+i*0.1):return False

        if not in_main_page:
            self._log(f"[错误] 无法返回大厅",color='red')
            return False
        else:
            # self._log(f"<font color='black'>[大厅] 已经返回大厅 - {get_timestamp_ms()}</font>")
            return True

    def navigate_to_sell_page(self,page = 1) -> bool:
        """
        保程序在交易行的出售页面。
        输入：
            page: 0表示 交易行/购买，1表示 交易行/出售
        """
        delay = 0.25
        for i in range(10):  # 最多重试5次
            self.perform_clicks(self.coords_large['trade'], times=2)
            if not self.safe_sleep(delay): return False

            # 验证是否成功进入交易行（检查标志性绿色按钮）
            green, _ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large["trade_green"]))
            if green:
                self.perform_clicks(self.coords_large['sell'][page], times=2)
                if not self.safe_sleep(delay): return False
                return True
            else:
                # 如果没成功，可能需要按ESC返回主菜单再重试
                pyautogui.press('esc')
                if not self.safe_sleep(delay): return False
        return False

    def navigate_to_warehouse(self) -> bool:
        """导航去仓库"""
        if not self.navigate_to_main_page():
            return False

        # 去仓库页面
        for i in range(5):
            self.perform_clicks(self.coords_large['warehouse'], delay=0.1,times=2),self.safe_sleep(0.5+0.3*i)  # 点进仓库
            warehouse_green, _ = self.image_processor.has_green(
                self.image_processor.capture_region(self.coords_large['warehouse_green']))
            if warehouse_green:
                self._log(f"[出售] 成功到仓库",color='black')
                return True
            else:
                self.perform_clicks(self.coords_large['begin_game'], delay=0.1, times=2)
        # 说明回不到仓库
        self._log("[错误] 回不到仓库",color='red')
        return False

    def refresh_func(self)->bool:
        """
        刷新一次大战场
        Args:

        Returns:
            object:
                - True  能回去
                - False 不能回去
        """
        self._log('[刷新] 去大战场刷新一下', color='magenta')
        self.perform_clicks(self.coords_large["begin_game"],times=2),self.safe_sleep(0.5)   # 让大号重新获取焦点
        # 每一步是否成功
        step_s1 = False     # 进入到模式切换的菜单
        step_s2 = False     # 成功点击切换菜单的大战场
        step_s3 = False     # 成功切换回烽火
        # ============ 确保进入模式切换 ==============
        for i in range(20):
            if self.flag.stop: return False
            pyautogui.press('esc')
            self.safe_sleep(0.5+0.2*i)
            quit_game,_ = self.ocr.recognize_text(
                self.image_processor.capture_region(self.coords_large['enter_ss']),need_preprocess=True)

            if self.is_str1_in_str2(quit_game,"进入特勤处"):
                step_s1 = True
                break

        if not step_s1:
            self._log(f"[错误] 无法切换模式，任务已停止",color='red')
            return False

        # ============ 确保点击大战场 ==============
        for i in range(20):
            if self.flag.stop: return False
            # 一直点，确保真的到大战场了
            self.perform_clicks(self.coords_large['return_to_dazhanchang'],
                                delay=0.1,times=2,hold_duration=0.05+0.01*i) # 进入大战场
            quit_game,_ = self.ocr.recognize_text(
                self.image_processor.capture_region(self.coords_large['enter_ss']),need_preprocess=True)
            if not self.is_str1_in_str2(quit_game,"进入特勤处"):
                step_s2 = True
                break
        if not step_s2:
            self._log(f"[错误] 无法点进大战场，任务已停止",color='red')
            return False

        # ============ 确保进入大战场 ==============
        battlefield = False
        t = time.time()
        while time.time() - t <= 15:
            if self.flag.stop: return False
            pyautogui.press('space'), self.safe_sleep(0.1)  # 按个空格防止广告
            pyautogui.press('space'), self.safe_sleep(0.2)  # 按个空格防止广告
            text,_ = self.ocr.recognize_text(
                self.image_processor.capture_region(self.coords_large["home_text"]))
            if self.is_str1_in_str2(text,"开始"):
                # 在大战场，要回去
                self.safe_sleep(1)
                battlefield = True
                break

        if not battlefield:
            self._log(f"[错误] 回不到大战场，任务已停止",color='red')
            return False

        # ====== 到这里确定绝对到大战场了 ======
        for i in range(20):
            pyautogui.press('esc')
            if not self.safe_sleep(0.5+0.1*i): return False
            self.perform_clicks(self.coords_large["return_to_fenghuo"],delay=0.1,times=2,hold_duration=0.05+0.01*i)
            self.safe_sleep(0.5+0.1*i)    # 每次时间变长
            text, _ = self.ocr.recognize_text(
                self.image_processor.capture_region(self.coords_large["home_text"]),)
            if self.is_str1_in_str2(text,"备战"):
                # 确保已经回到烽火了
                step_s3 = True
                break

        if not step_s3:
            self._log(f"[错误] 回不到烽火，任务已停止",color='red')
            return False

        self._log('[刷新] 刷新完成', color='magenta')
        return True

    def re_act_delta_force(self):
        """通过官方启动器重启三角洲"""
        self._log("[重启] 正在重启三角洲")
        if not self.safe_sleep(10):return False
        start_lnk,status =  WindowOperator.start_item("三角洲行动.lnk")
        if not start_lnk:
            self._log(f"[错误] {status}", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            return False    # 先把启动器取消后台
        else:
            self._log(f"[重启] {status}")
        if not self.safe_sleep(10):return False
        windows = WindowOperator.find_windows_with_details("三角洲行动")
        old_hwnd = []
        delta_force_launcher = None
        for window in windows:
            old_hwnd.append(window['hwnd'])
            if window.get('window_size') != (1462, 1136) and window.get('client_size') != (1440,1080):
                delta_force_launcher = window

        if not delta_force_launcher:
            self._log("[错误] 无法找到启动器", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            return False

        df_w = WindowOperator(delta_force_launcher['hwnd'])
        df_w.focus()
        df_w.show()     # 显示出来
        df_w.set_topmost(True)
        # ===== 获取截图区域，为窗口的右下1/4 =========
        client_x, client_y = delta_force_launcher['window_position']
        client_w, client_h = delta_force_launcher['window_size']

        # 1. 计算1/4区域的宽高 (使用整数除法 //)
        quarter_w = client_w // 2
        quarter_h = client_h // 2

        # 2. 计算1/4区域的起始X, Y坐标
        #    起始X = 客户区X + 客户区宽度的一半
        #    起始Y = 客户区Y + 客户区高度的一半
        quarter_x = client_x + (client_w // 2)
        quarter_y = client_y + (client_h // 2)

        act_game_region = (quarter_x, quarter_y, quarter_w, quarter_h)
        act_game_click:tuple[int,int] = None
        # 一直检测，直到出现“开始游戏”
        for i in range(600):
            act_game_click = self.ocr.find_text_center(act_game_region,'开始')
            self.safe_sleep(1)
            if act_game_click:break

        if not act_game_click:
            self._log("[错误] 无法识别启动按钮", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            return False

        # 一直点击开始游戏，直到游戏出现“正在启动”
        act_game = False
        for i in range(600):
            self.perform_clicks(act_game_click,hold_duration=0.1,times=1)
            self.safe_sleep(0.5)
            text, _ = self.ocr.recognize_text(
                self.image_processor.capture_region(act_game_region), )
            if self.is_str1_in_str2("启动", text):
                act_game = True
                break
            self.safe_sleep(0.5)

        if not act_game:
            self._log("[错误] 无法点击按钮启动游戏", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            return False

        df_w.set_topmost(False)
        if not self.safe_sleep(60):return False    # 等待游戏启动
        new_hwnd = None
        for i in range(600):
            if new_hwnd: break
            windows = WindowOperator.find_windows_with_details("三角洲行动")
            # ===== 绑定新的窗口 =====
            for window in windows:
                if window['hwnd'] not in old_hwnd:
                    new_hwnd = window['hwnd']
                    break
            if not self.safe_sleep(1):break

        if not new_hwnd:
            self._log("[错误] 无法找到游戏窗口", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            return False
        # self.op_large.set_topmost(False)
        op_large_temp = WindowOperator(new_hwnd)   # 临时的窗口绑定
        self._log('[重启] 已重新绑定')
        from resolution_m import resolution_position
        if not op_large_temp.focus(attempts = 5,interval = 1):
            self._log("[错误] 无法聚焦游戏窗口", color='red')
            self.image_processor.capture_full_screen('error.png')
            self._log("[错误] 全屏截图已保存到 error.png")
            # return False
        self.safe_sleep(1)
        op_large_temp.set_topmost(True),self.safe_sleep(2)
        # self.parent.update_selected_window(new_hwnd,'三角洲行动',"大号")

        self.coords_large = op_large_temp.client_to_screens(resolution_position.get('large', {}))
        # 一直点击，知直到点击到主界面
        in_main_page = False
        for i in range(60):
            text, _ = self.ocr.recognize_text(
                self.image_processor.capture_region(self.coords_large["home_text"]), )
            if self.is_str1_in_str2("备战", text):
                in_main_page = True
                break

            self.perform_clicks(self.coords_large['start_game_click'],hold_duration=0.1,times=2)
            if not self.safe_sleep(1):break
            pyautogui.press('space'),self.safe_sleep(0.1)
            pyautogui.press('space'),self.safe_sleep(0.5)
            pyautogui.press('tab'),self.safe_sleep(0.5)

        if in_main_page:
            self._log("[重启] 已回到烽火",color='blue')
            self.safe_sleep(2)
        else:
            self._log("[错误] 无法回到烽火",color='red')
            return False
        self.return_to_loadout()
        self._log("[重启] 重新启动 Worker！！！", color='blue')
        self.restart_game_signal.emit(new_hwnd)
        self.flag.stop = True
        return True

    def safe_sleep(self, duration_s: float= 0.01) -> bool:
        """
        可中断的休眠函数。
        Args:
            duration_s: 希望休眠的总秒数。
        Returns:
            bool: 如果休眠被中断，返回 False；如果正常完成休眠，返回 True。
        """
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < duration_s:
            if self.flag.stop:break
            self.msleep(1)  # 休眠一个很短的时间片，然后再次检查
        if self.flag.stop:
            return False
        else:
            return True  # 正常完成

    def return_to_loadout(self):
        """
        检测到不再配装页面就自动回去
        """
        params = {"delay": 1.3, "hold_duration": 0.05, "move_duration": 0.1}
        self.navigate_to_main_page()    # 先回到大厅
        # green0, _ = self.image_processor.has_green(self.image_processor.capture_region(
        #     *self.coords_large["begin_game_green"]),
        #     threshold=100, )
        # if not green0:
        #     self.perform_clicks(self.coords_large['begin_game'], delay=0.05)  # 点一下左上角开始游戏
        #     self.safe_sleep(1)

        # 要监测一下是不是在大战场，如果是的话需要回去
        text,_ = self.ocr.recognize_text(
            self.image_processor.capture_region(self.coords_large["home_text"]),)

        if self.is_str1_in_str2("备战",text):
            # 主页没有配装,先点击一下配装
            self.perform_clicks(self.coords_large["return_to_loadout"][0],hold_duration=0.05),self.safe_sleep(1.2)
            # 如果green1，说明可以直接点开始行动
            # 如果green2，说明需要点一下大坝
            # 如果都没有，则说明可能在红薯窝
            green1,_=self.image_processor.has_green(self.image_processor.capture_region(
                *self.coords_large["return_to_loadout_half"]),
                threshold= 100,)
            green2, _ = self.image_processor.has_green(self.image_processor.capture_region(
                *self.coords_large["return_eagle"]),
                threshold=200,)
            if green1:
                # 如果有则不需要点第二下
                self.perform_clicks(self.coords_large["return_to_loadout"][3:],**params)
            elif green2:
                self.perform_clicks(self.coords_large["return_to_loadout"][2:],**params)
            else:
                self.perform_clicks(self.coords_large["return_to_loadout"][1:],**params)
            self.safe_sleep(1)

        # elif self.is_str1_in_str2("开始",text):
        #     # 在大战场，要回去
        #     pyautogui.press('esc'),self.safe_sleep(1)
        #     self.perform_clicks(self.coords_large["return_to_fenghuo"]),self.safe_sleep(1)
        #     return False

        # 检测一下主页有没有配装，没有的话点一下
        self.perform_clicks(self.coords_large['home_loadout'], delay=0.05)  # 点一下配装
        self.safe_sleep(1)
        if self.num_loadouts > 1:   # 如果是来回刷，则直接进去配装界面
            pyautogui.press('L')
            self.safe_sleep(1)

        return True

class DynamicPriceManager:
    """
    动态价格管理类。
    通过采集历史价格，计算当前交易行的 “第一个柱子价格”，并给出合理的购买上限。
    """

    def __init__(self,price_diff: int=0,price_diff_n: int=1 , bullet_qty: int=1, max_limit: int=999999999,
                 min_limit: int = 1,
                 buffer_size=10, streak_threshold=3,*,enabled:bool=True, price_base:int=0):
        """
        Args:
            price_diff: 价格挡位差
            price_diff_n: 差几个挡位
            bullet_qty: 购买的子弹数量
            max_limit:最高价
            min_limit:最低价
            buffer_size: 价格缓冲区大小
            streak_threshold:连续相等次数，连续相等好几次就更新价格
            enabled:是否启用自动挡屎，不启用则需要传入price_base(固定价格)
            price_base:固定价格。
        """

        # --- 配置参数 ---
        self.buffer_size = buffer_size
        self.streak_threshold = streak_threshold
        self.price_diff = price_diff        # 档位差价
        self.price_diff_n = price_diff_n    # 差几个档位
        self.bullet_quantity = bullet_qty   # 单次购买数量（如 200）
        self.price_max = max_limit    # 允许的价格上限
        self.price_min = min_limit    # 允许的价格下限
        self.enabled = enabled  # 是否启用自动挡屎
        self.price_base = price_base    # 固定价格

        # --- 运行状态 ---
        self.buffer :list[int]= [0] * buffer_size  # 环形缓冲区
        self.index :int= 0      # 当前写入位置，0-self.buffer 循环
        self.streak :int= 0     # 连续相等计数
        self.last_sample_price :int= -1  # 上一个采集到的价格
        self.block_price :int= 0  # 识别出的当前价格基准
        self.calculated_price :int= 0   # 在当前价格基础上减去 挡位

    def add_sample(self, price: int):
        """
        添加一个新的价格样本到缓冲区，并尝试更新“当前价格”基准
        """
        if price <= 0:
            return

        # 1. 写入环形缓冲区
        self.buffer[self.index] = price
        self.index = (self.index + 1) % self.buffer_size

        # 2. 连续相等检测
        if price == self.last_sample_price:
            self.streak += 1
        else:
            self.streak = 1
        self.last_sample_price = price

        # 3. 更新基准价格的核心逻辑
        # 情况 A: 触发连续性阈值 —— 立即强制更新（优先级最高）
        cond_streak = (self.streak >= self.streak_threshold)
        if cond_streak:
            self.block_price = price
            return

        # 情况 B: 缓冲区满了 —— 根据频率更新（平票时最近优先）
        cond_full = (self.buffer[-1] > 0)
        if cond_full:
            # 统计频率
            freq = Counter(self.buffer)
            max_count = max(freq.values())

            # 找出出现频率最高的价格（可能是多个）
            candidates = {k for k, c in freq.items() if c == max_count}

            # 最近优先：从当前索引往回找，第一个在候选集里的就是最新的价格
            for i in range(1, self.buffer_size + 1):
                pos = (self.index - i) % self.buffer_size
                val = self.buffer[pos]
                if val in candidates:
                    self.block_price = val
                    break

    def process(self,price: int)->int:
        """
        输入新价格，返回 计算后的价位
        Returns:
            计算后的价位
        """
        if not self.enabled:
            return self.price_base

        # 1. 更新内部数据
        self.add_sample(price)

        # 2. 如果还在探测期（没识别出"价格基准"），返回 0
        if self.block_price == 0:
            self.calculated_price = 0
            return 0

        # 3. 计算实际应设定的 购买价格
        # 公式：价格基准 - (单价档位差 * 档位个数 * 购买数量)
        raw_limit = self.block_price - self.price_diff * self.price_diff_n * self.bullet_quantity
        # 4. 应用保险栓（不能超出范围）
        self.calculated_price = max(self.price_min, min(raw_limit, self.price_max))

        print(f"最终挡位价：{self.calculated_price}")
        return self.calculated_price

    def reset(self):
        """重置所有采集数据"""
        self.buffer = [0] * self.buffer_size
        self.index = 0
        self.streak = 0
        self.last_sample_price = -1
        self.block_price = 0

    def __repr__(self):
        if self.enabled:
            return f"<PriceMgr(On) Blocked:{self.block_price:,} Limit:{self.calculated_price:,} Buf:{self.buffer}>"
        else:
            return f"<PriceMgr(Off) Blocked:{self.price_base:,}>"


class HoardTracker:
    """屯仓数据统计与状态管理类"""

    def __init__(self, is_dual: bool,target_qty: int,min_price :int, max_price: int, buy_configs:dict,
                 confirm_n: int = 1,idle_threshold: int = 6,dynamic_slow:bool = False, slow_circle: float = 5.0,
                 max_buy_n: int = -1,):
        """

        Args:
            is_dual: 是不是双端
            target_qty: 目标购买数量
            min_price: 最低价格
            max_price: 最大价格
            buy_configs: 坐标配置
            confirm_n: 连续n次识别到低价
            idle_threshold：连续多少次没出低价就进入动态休眠
            dynamic_slow: 是否启用动态休眠
            slow_circle: 动态休眠的周期长
            max_buy_n: 大号单次触发最大连买次数

        """
        self.is_dual = is_dual
        self.target_qty = target_qty
        self.min_price = min_price  # 买入最低价
        self.max_price = max_price  # 买入最高价
        self.configs = buy_configs  # 存储 BUY_MODE 字典
        self.buy_circle_n = buy_configs.get("large", {}).get("loop_period", 0.5)    # 默认的购买周期
        self.detect_circle_n = buy_configs.get("small", {}).get("loop_period", 5)    # 默认的探测
        self.loop_period = self.detect_circle_n   # 初始的探测周期

        # === 统计区 ===
        self.activated = "small" # 默认当前模式为 探测
        self.old_activated = self.activated # 初始模式
        self.accum_qty = 0      # 已购买的子弹数量
        self.err_count = 0      # 连续 n 次价格不变话要先暂停处理
        self.err_cost_n = 0     # 连续 n 次消费为负数的话则终止运行
        self.price_history = set()  # 探测到的历史价格

        self.transition_msg = ""    # 【新增】用字符串记录切换状态，空字符串表示未切换
        # self.buy_history = [0, 0]   # 购买记录，[上一次状态, 这一次状态] (0:探测, 1:买入)

        # === 余额封装区 ===
        self._shared_balance = -1                   # 单端共享余额
        self._dual_balances = {"small": -1, "large": -1} # 双端独立余额

        # --- 智能探测参数 ---
        self.confirm_n = confirm_n           # 连续探测到低价 N 次才买入
        self.idle_threshold = idle_threshold # 连续多长时间没出低价就进入动态休眠
        self.slow_circle = slow_circle       # 动态休眠的周期长
        self.slow_step = 1.0                           # 超过阈值后，每次增加 1.0 秒
        if dynamic_slow:
            self.max_slow_circle = self.slow_circle * 2.0  # 最大限制为基础慢速的 2 倍（翻倍）
        else:
            self.max_slow_circle = self.slow_circle

        self.max_buy_n = max_buy_n       # 【新增】Burst 限制次数
        self.current_buy_n = 0           # 【新增】当前大号连买计数器

        # --- 时间管理区 ---
        # 记录双端上次购买/探测的独立时间戳
        self.last_act_time:dict[str, float] = {
            "small": time.perf_counter() - 10.0,
            "large": time.perf_counter() - 10.0}

        # --- 连击计数器 ---
        self.low_price_streak = 0   # 低价连击
        self.high_price_streak = 0  # 高价连击

    # ================= 动作记录 =================
    def record_action(self, account: str):
        """
        记录指定账号执行点击购买的时刻。
        在 Worker 执行 perform_clicks 购买后立刻调用。
        """
        now = time.perf_counter()
        if self.is_dual:
            # 双端模式：各自记录
            self.last_act_time[account] = now
        else:
            # 【关键】单端模式：只有一个物理窗口，点击任何一个模式都要同步更新两个时间戳
            # 这样能确保：小号刚点完，切大号时，大号会严格遵守冷却。
            self.last_act_time["small"] = now
            self.last_act_time["large"] = now

    def update_mode(self, current_cost: int):
        """根据价格更新当前模式，并记录历史"""
        # 1. 判定当前价格是否在【有效低价区间】
        is_valid_low = (self.min_price <= current_cost <= self.max_price)   # 是不是 有效低价区间
        self.old_activated = self.activated  # 记录旧模式（当前模式）
        self.transition_msg = ""  # 重置切换消息

        # ----- 探测到低价 -----
        if is_valid_low:
            self.high_price_streak = 0
            self.low_price_streak += 1

            # 探测到低价，立刻加速
            self.loop_period = self.buy_circle_n

            # ----- 只有连续 n 次探测到低价，切换为买入 -----
            if self.low_price_streak >= self.confirm_n:
                # 如果当前是小号，则切换为大号买入
                if self.activated == "small":
                    self.activated = "large"
                    self.current_buy_n = 0
                # 如果当前是大号买入，则记录连续购买次数
                else:
                    self.current_buy_n += 1 # 已经在large模式，连买计数增加

                # 检查是否达到连买上限，超限后改回探测模式
                if 0 < self.max_buy_n <= self.current_buy_n:
                    self.activated = "small"
                    self.current_buy_n = 0      # 重置大号购买次数
                    self.low_price_streak = 0   # 重置低价连击，强制重新探测
        # ----- 探测到高价 -----
        else:
            # 价格过高，或者低于 min_price 破发价
            self.low_price_streak = 0
            self.high_price_streak += 1
            self.current_buy_n = 0  # 价格变高，连买计数清零
            self.activated = "small"    # 立刻切换为探测模式

            # 需求3：连续N次没出低价，进入缓慢探测模式
            if self.high_price_streak >= self.idle_threshold:
                # 计算超出的次数
                extra_times = self.high_price_streak - self.idle_threshold
                # 计算动态时间：初始慢速 + (超出次数 * 递增步长)
                dynamic_period = self.slow_circle + (extra_times * self.slow_step)

                # 【核心】使用 min() 限制最大值，不超过翻倍上限
                self.loop_period = min(dynamic_period, self.max_slow_circle)
            else:
                # 【显式赋值】正常小号探测
                self.loop_period = self.detect_circle_n

        # 记录模式切换字符串
        if self.old_activated != self.activated:
            if self.activated == "large":
                self.transition_msg = "买入"
            else:
                self.transition_msg = "探测"
        else:
            self.transition_msg = ""  # 未发生切换

    # ================= 智能等待计算 =================
    def get_wait_time(self) -> float:
        """
        获取本次循环应睡眠的时间。
        逻辑：
        1. 只要模式切换，返回 购买周期减去已流逝时间。
        2. 模式未变：返回 当前模式周期减去已流逝时间。
        """
        now = time.perf_counter()
        # 获取当前(或切换后)账号上一次操作的时间
        last_time = self.last_act_time[self.activated]
        elapsed = now - last_time   # 时间差

        # 1. 发生了模式切换 (不论是 S->L 还是 L->S)
        if self.transition_msg:
            # 统一要求：休息够 大号的购买间隔 (buy_circle_n)
            return max(0.0, self.buy_circle_n - elapsed)

        # 2. 模式未改变
        # 休息够 当前模式对应的 loop_period (detect/buy/slow)
        return max(0.0, self.loop_period - elapsed)

    # ================= 余额管理 =================
    def init_balance(self, account: str, val: int):
        """记录初始余额"""
        if self.is_dual:
            self._dual_balances[account] = val
        else:
            self._shared_balance = val

    def calc_cost(self, new_bal: int, buy_amount: int) -> int:
        """
        计算单价并处理连买 Bug
        Args:
            new_bal: 新余额
            buy_amount: 购买后识别的数量

        Returns:
            这次购买的单价
        """
        # 计算分母：如果部分购买，则用 (设定数量 - 剩余数量)
        if buy_amount == self.once_qty:
            denom = self.once_qty
        else:
            denom = self.once_qty - buy_amount

        if denom <= 0: return 0

        cost = (self.current_balance - new_bal) // denom
        # 兼容处理：有时买两次价格才跳变
        if (cost // 2) in self.price_history:
            cost //= 2
        return cost

    @property
    def current_balance(self) -> int:
        """获取当前激活状态应该对比的旧余额"""
        if self.is_dual:
            return self._dual_balances[self.activated]
        else:
            return self._shared_balance

    def update_balance(self, new_val: int):
        """更新当前激活状态的余额"""
        if self.is_dual:
            self._dual_balances[self.activated] = new_val
        else:
            self._shared_balance = new_val

    def record_success(self, cost: int, amount: int):
        """
        记录一次成功的购买

        Args:
            cost: 购买价格
            amount: 购买数量
        """
        # 重置错误计数器
        self.err_count = 0
        self.err_cost_n = 0
        # 记录购买的数量和历史
        self.accum_qty += amount
        self.price_history.add(cost)

    def record_frozen_price(self):
        """记录交易行价格未变动（可能卡了或仓库满）"""
        self.err_count += 1
        self.err_cost_n = 0

    def record_error_cost(self):
        """记录一次错误消费"""
        self.err_cost_n += 1

    def need_realign_quantity(self) -> bool:
        """判定是否因为切换了模式而需要重新拉数量"""
        return bool(self.transition_msg)

    def set_loop_period(self, new_period:float) -> None:
        """
        设置新的周期时间
        Args:
            new_period: 新的周期时间
        """
        self.loop_period = new_period

    def get_status_summary(self, price):
        """新增方法：输出当前关键信息"""
        mode_str = f"[{self.old_activated.upper()}]"
        streak_info = f"L-Streak: {self.low_price_streak} | H-Streak: {self.high_price_streak}"
        burst_info = f"Burst: {self.current_buy_n}/{self.max_buy_n}"
        period_info = f"Next Wait: {self.loop_period:.1f}s"
        change_info = f" >> CHANGE: {self.transition_msg}" if self.transition_msg else ""
        return f"Price: {price:4d} | {mode_str:7s} | {streak_info} | {burst_info} | {period_info}{change_info}"

    # ------------ 根据 [探测]/[买入]模式 变化的量 ----------------
    @property
    def cfg(self) -> dict:
        """获取当前模式对应的配置字典"""
        return self.configs[self.activated]

    @property
    def buy_click(self)->tuple[int,int]:
        """购买的点击坐标"""
        return self.cfg["buy_click"]

    @property
    def once_qty(self)->int:
        """现在应每次买入的数量（用于在买入与探测之间切换）"""
        return self.cfg["buy_quantity"]

    @property
    def shift_click(self)->tuple[int,int]:
        """现在应该,买入数量的坐标"""
        return self.cfg["buy_shift_click"]

    @property
    def shift_check(self)->tuple[int,int,int,int]:
        """检测 买入数量 是否正确的坐标"""
        return self.cfg["buy_shift_check"]

    # ------------------------------------------

    @property
    def is_finished(self) -> bool:
        """购买数量足够"""
        return self.accum_qty >= self.target_qty