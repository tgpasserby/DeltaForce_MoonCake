# ----- 导入官方库 -----
import functools
import time
import os
from PIL import Image
import pickle
from typing import Dict, Optional
import logging

# ----- 导入三方库 -----
import cv2
import numpy as np
import imagehash

# ----- 导入自用库 -----
from basic_tools import timing_decorator

logger = logging.getLogger(__name__)

__version__ = "1.0.1"
__update__ = "2026.07.28"

class PHashRecognizer:
    """
    一个基于感知哈希（pHash）的高速图形识别系统。

    功能：
    - 记录：存储图像的 pHash 值及其对应的数字字符串。
    - 查找：根据输入图像的 pHash，快速在缓存中查找相似图像对应的数字。
    - 持久化：支持将缓存保存到文件及从文件加载。
    """
    def __init__(self, hamming_threshold: int = 5, need_save_cache:bool = False):
        """
        初始化pHash缓存。

        Args:
            hamming_threshold (int): 汉明距离阈值。当两张图片的 pHash 汉明距离小于等于此值时，
                                     认为是同一张图片。默认值为5。
            need_save_cache: 在退出程序时是否保存缓存。
        """
        self._cache: Dict[imagehash.ImageHash, str|int] = {}    # 数字存为 int
        self.need_save_cache:bool = need_save_cache
        self.hamming_threshold:int = hamming_threshold
        self.load_cache()
        logger.info(f"pHash缓存已初始化，汉明距离阈值为: {self.hamming_threshold}")

    @staticmethod
    # @timing_decorator("计算 phash耗时: {duration:.3f} s")
    def _calculate_phash(image_np: np.ndarray) -> Optional[imagehash.ImageHash]:
        """
        计算 BGR NumPy数组图像的 pHash值。

        Args:
            image_np: OpenCV格式的BGR图像。

        Returns:
            Optional: 计算出的 pHash对象，如果输入无效则返回 None。
        """
        if not isinstance(image_np, np.ndarray) or image_np.size == 0:
            logger.warning("尝试为无效图像计算pHash。")
            return None
        # imagehash库需要PIL格式的RGB图像，因此需要进行转换
        image_rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image_rgb)
        return imagehash.phash(pil_image)

    @staticmethod
    def preprocess_for_phash(image_np: np.ndarray) -> np.ndarray | None:
        """
        图像预处理方法。
        目标是标准化图像，去除主要干扰，但保留宏观灰度结构。
        (目前没有发现好的方法，经常会导致识别的不一样)
        """
        pass

    def add(self, image_np: np.ndarray, label: str|int) -> None:
        """
        计算 一张图片的 pHash，并添加到缓存中。
        如果哈希非常相似，但是对应的数字不同，则会更新其对应的数字。

        Args:
            image_np: OpenCV格式的BGR图像。
            label: 与图像对应的数字或文本（推荐使用字符串以支持'1,000'等格式）。
        """
        new_phash = self._calculate_phash(image_np)     # 计算 phash
        if new_phash is None:return # 无效图形

        # 检查是否已有非常相似的哈希存在，避免轻微变动导致重复存储
        found_key = self._find_closest_hash(new_phash)

        # 如果存在则更新，不存在则添加
        if found_key:
            if self._cache[found_key] != label:
                logger.warning(
                    f"更新缓存：哈希 {found_key} 对应的数字：'{self._cache[found_key]}' -> '{label}'。")
                self._cache[found_key] = label
        else:
            self._cache[new_phash] = label
            logger.info(f"新条目已添加：pHash={new_phash}, Number='{label}'")

    def _find_closest_hash(self, target_hash: imagehash.ImageHash) -> Optional[imagehash.ImageHash]:
        """
        在缓存中寻找与目标哈希最接近的哈希键。
        """
        if not self._cache:return None  # 没有找到

        # 如果能直接找到，则返回本身
        if target_hash in self._cache:return target_hash

        # 寻找最接近的哈希键
        min_dist = float('inf')
        closest_hash = None

        # 计算全部的哈希键，找到最接近的
        for stored_hash in self._cache.keys():
            dist = target_hash - stored_hash
            if dist < min_dist:
                min_dist = dist
                closest_hash = stored_hash

        if min_dist <= self.hamming_threshold:
            return closest_hash
        else:
            return None

    def find(self, image_np: np.ndarray) -> str|int|None:
        """
        通过 pHash查找输入图片对应的数字。

        Args:
            image_np: OpenCV格式的 BGR图像。

        Returns:
            Optional[str]: 如果在缓存中找到匹配的数字，则返回该数字字符串。
                           如果不存在，则返回 None。
        """
        # image_np = self.preprocess_for_phash(image_np)
        target_phash = self._calculate_phash(image_np)
        if target_phash is None:
            return None  # 输入无效

        closest_hash_key = self._find_closest_hash(target_phash)

        if closest_hash_key:
            found_number = self._cache[closest_hash_key]
            dist = target_phash - closest_hash_key
            logger.info(f"找到相似图片 (距离: {dist})，对应数字: '{found_number}'")
            return found_number
        else:
            logger.info("未找到相似图片。")
            return None

    def save_cache(self, file_path: str='config//cache.pkl') -> bool:
        """
        将当前的缓存数据保存到文件。
        """
        try:
            with open(file_path, 'wb') as f:
                pickle.dump(self._cache, f)
            logger.info(f"缓存已成功保存到: {file_path}")
            return True
        except IOError as e:
            logger.error(f"保存缓存失败：无法写入文件 {file_path}。原因: {e}")
            return False
        except Exception as e:
            logger.error(f"保存缓存时发生未知错误: {e}")
            return False

    def load_cache(self, file_path: str='config//cache.pkl') -> bool:
        """
        从文件加载缓存数据。
        """
        if not os.path.exists(file_path):
            logger.warning(f"缓存文件不存在: {file_path}。将使用空缓存启动。")
            return False
        try:
            with open(file_path, 'rb') as f:
                self._cache = pickle.load(f)
            logger.info(f"缓存已成功从 {file_path} 加载，包含 {len(self._cache)} 个条目。")
            return True
        except (pickle.UnpicklingError, EOFError) as e:
            logger.error(f"加载缓存失败：文件 {file_path} 已损坏或为空。原因: {e}。将使用空缓存。")
            self._cache = {}
            return False
        except Exception as e:
            logger.error(f"加载缓存时发生未知错误: {e}。将使用空缓存。")
            self._cache = {}
            return False

    def __len__(self):
        return len(self._cache)

    def __str__(self):
        return f"NumberPHashCache(items={len(self._cache)}, threshold={self.hamming_threshold})"

    def __del__(self):
        """
        如果设置了缓存文件路径，则自动保存缓存。
        """
        # 检查是否有需要保存的数据以及保存路径
        if self.need_save_cache and self._cache:
            try:
                self.save_cache()
            except Exception as e:
                # 在__del__中最好不要让异常抛出，只记录即可
                # 使用print而不是logger，因为在程序退出时logging可能已关闭
                print(f"CRITICAL: 在__del__中自动保存缓存失败: {e}")