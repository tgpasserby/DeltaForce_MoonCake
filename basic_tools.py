# basic_tools

"""
存放大多数模块使用的基础构件
"""

import functools
import time
import json
import os
from typing import Dict,List,Tuple,Optional

__version__ = "1.0.0"
__update__ = "2026.07.28"

def timing_decorator(format_string="函数 '{func_name}' 执行时间: {duration:.6f} 秒", printer=print):
    """
    一个可定制打印格式的计时装饰器工厂。

    Args:
        format_string: 格式化字符串
        printer: 用于输出信息的函数，默认为内置的 print。

    Returns:
        function: 实际的装饰器函数。
    """

    def decorator(func):
        @functools.wraps(func)  # 保留原函数的元信息 (如名称, docstring)
        def wrapper(*args, **kwargs):
            # --- 计时开始 ---
            start_time = time.perf_counter()
            # --- 执行原函数 ---
            result = func(*args, **kwargs)
            # --- 计时结束 ---
            end_time = time.perf_counter()
            duration = end_time - start_time

            # --- 使用传入的 format_string 格式化并打印 ---
            try:
                output_message = format_string.format(func_name=func.__name__, duration=duration)   # 要打印的日志
                if hasattr(printer, '__name__') and printer.__name__ in ['debug', 'info', 'warning', 'error', 'critical']:
                    printer(output_message, stacklevel=2)
                else:
                    printer(output_message)
            except (KeyError, ValueError) as e:
                # 如果格式字符串有问题（比如缺少占位符或格式错误），打印错误信息
                printer(f"格式化错误: {e} | {func.__name__} 耗时: {duration:.6f}s")

            # --- 返回原函数的执行结果 ---
            return result
        return wrapper
    return decorator

def get_timestamp_ms()->str:
    """
    使用 time 模块生成一个精确到毫秒的时间戳字符串。
    格式: HH:MM:SS,ms
    """
    # 1. 获取当前时间戳（一个带小数的浮点数，例如 1678886400.12345）
    now = time.time()

    # 2. 使用 strftime 格式化日期和时间部分（不含毫秒）
    # time.localtime() 会处理浮点数，直接使用其整数部分
    time_str = time.strftime('%H:%M:%S', time.localtime(now))

    # 3. 从原始时间戳中计算毫秒数
    # (now - int(now)) 得到小数部分，乘以1000得到毫秒
    milliseconds = int((now - int(now)) * 1000)

    # 4. 使用 f-string 将它们组合起来，并确保毫秒总是3位数（例如 7ms -> "007"）
    return f"{time_str},{milliseconds:03d}"

def get_timestamp_s()->str:
    """
    使用 time 模块生成一个精确到秒的时间戳字符串。
    格式: HH:MM:SS
    """
    # 1. 获取当前时间戳（一个带小数的浮点数，例如 1678886400.12345）
    now = time.time()

    # 2. 使用 strftime 格式化日期和时间部分（不含毫秒）
    # time.localtime() 会处理浮点数，直接使用其整数部分
    time_str = time.strftime('%H:%M:%S', time.localtime(now))

    # 4. 使用 f-string 将它们组合起来，并确保毫秒总是3位数（例如 7ms -> "007"）
    return f"{time_str}"

def get_datetime()->str:
    """
    使用 time 模块生成一个精确到秒的时间戳字符串。
    格式: YYYY-MM-DD HH:MM:SS
    """
    # 1. 获取当前时间戳（一个带小数的浮点数，例如 1678886400.12345）
    now = time.time()

    # 2. 使用 strftime 格式化日期和时间部分（不含毫秒）
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

    return f"{time_str}"

def write_json(data:Dict, file_path:str, indent:int=2)->bool:
    """
    将 Python 对象（字典、列表等）写入 JSON 文件。

    Args:
        data: 要序列化的数据对象
        file_path: 目标文件路径
        indent: 缩进空格数，默认为 4，设为 None 则不换行

    Returns:
        bool - 是否写入成功
    """
    try:
        # 确保目标目录存在，不存在则创建
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        # ensure_ascii=False 允许写入非 ASCII 字符（如中文），避免乱码
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

        return True
    except Exception as e:
        print(f"写入文件时出错: {e}")
        return False

def read_json(file_path:str)->Optional[Dict]:
    """
    从 JSON 文件中读取数据。

    Args:
        file_path: 文件路径

    Returns:
        成功返回解析后的对象，失败或文件不存在返回 None
    """
    # 文件不存在
    if not os.path.exists(file_path):
        print(f"错误: 文件 '{file_path}' 不存在。")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"JSON 格式错误: {e}")
        return None
    except Exception as e:
        print(f"读取文件时发生未知错误: {e}")
        return None