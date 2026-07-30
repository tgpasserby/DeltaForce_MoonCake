from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# ============================================================
# 配置区
# ============================================================

# 打包后的 EXE
EXE_PATH = Path(
    r"E:\python_proj\测试开源\dist\月饼的三角洲通用脚本v1.2.24-开源版\月饼的三角洲通用脚本v1.2.24-开源版.exe"
)

# 用于打包的虚拟环境 Python
VENV_PYTHON = Path(
    r"D:\anaconda\envs\yuebing-open\python.exe"
)

# PyInstaller onedir 模式支持文件目录
INTERNAL_DIR = EXE_PATH.parent / "_internal"

# 每轮观察 EXE 启动的秒数
STARTUP_OBSERVE_SECONDS = 10

# 最大自动修复轮数
MAX_REPAIR_ROUNDS = 30

# 修复完成后是否重新正常启动 EXE
LAUNCH_AFTER_SUCCESS = False

# 日志文件
LOG_PATH = EXE_PATH.parent / "auto_repair.log"

# 修复清单
MANIFEST_PATH = EXE_PATH.parent / "auto_repair_manifest.json"


# ============================================================
# 异常识别规则
# ============================================================

MODULE_PATTERNS = [
    re.compile(
        r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]"
    ),
    re.compile(
        r"ImportError:\s*No module named ['\"]([^'\"]+)['\"]"
    ),
]

METADATA_PATTERNS = [
    re.compile(
        r"PackageNotFoundError:\s*"
        r"No package metadata was found for\s+([^\r\n]+)"
    ),
    re.compile(
        r"No package metadata was found for\s+([^\r\n]+)"
    ),
]

ZONEINFO_PATTERN = re.compile(
    r"ZoneInfoNotFoundError:.*?"
    r"No time zone found with key",
    flags=re.DOTALL,
)

DLL_ERROR_PATTERNS = [
    re.compile(r"DLL load failed", flags=re.IGNORECASE),
    re.compile(r"找不到指定的模块", flags=re.IGNORECASE),
]

RUNTIME_ERROR_MARKERS = [
    "Traceback (most recent call last):",
    "ModuleNotFoundError:",
    "PackageNotFoundError:",
    "FileNotFoundError:",
    "ImportError:",
    "DLL load failed",
    "ZoneInfoNotFoundError:",
]


@dataclass(frozen=True)
class MissingItem:
    """表示从异常信息中识别出的缺失项目。"""

    kind: str
    name: str


@dataclass
class RepairRecord:
    """表示一次自动修复记录。"""

    round_number: int
    kind: str
    name: str
    copied_paths: list[str]
    timestamp: str


def decode_output(data: bytes | None) -> str:
    """解码子进程输出。

    Args:
        data: 子进程输出的原始字节。

    Returns:
        解码后的字符串。
    """
    if not data:
        return ""

    for encoding in ("utf-8", "gb18030", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    return data.decode("utf-8", errors="replace")


def write_log(message: str) -> None:
    """同时输出到控制台和日志文件。

    Args:
        message: 需要记录的文本。
    """
    print(message)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(message)
        if not message.endswith("\n"):
            file.write("\n")


def contains_runtime_error(output: str) -> bool:
    """判断输出中是否存在明确运行异常。

    Args:
        output: EXE 的标准输出和标准错误。

    Returns:
        检测到异常时返回 True。
    """
    return any(marker in output for marker in RUNTIME_ERROR_MARKERS)


def run_environment_query(
    operation: str,
    name: str,
) -> dict[str, Any]:
    """通过指定虚拟环境查询模块或发行包信息。

    Args:
        operation: 查询类型，可选 module、metadata、distributions。
        name: 模块名或发行包名。

    Returns:
        查询结果。

    Raises:
        RuntimeError: 虚拟环境查询失败。
    """
    helper_code = r"""
import importlib.metadata
import importlib.util
import json
import pathlib
import sys

operation = sys.argv[1]
name = sys.argv[2]

result = {
    "success": False,
    "operation": operation,
    "name": name,
}

try:
    if operation == "module":
        top_level_name = name.split(".", 1)[0]
        spec = importlib.util.find_spec(top_level_name)

        if spec is None:
            raise ModuleNotFoundError(
                f"Cannot find module: {top_level_name}"
            )

        locations = []
        if spec.submodule_search_locations:
            locations = [
                str(pathlib.Path(path).resolve())
                for path in spec.submodule_search_locations
            ]

        result.update({
            "success": True,
            "top_level_name": top_level_name,
            "origin": spec.origin,
            "locations": locations,
            "is_package": bool(locations),
        })

    elif operation == "metadata":
        distribution = importlib.metadata.distribution(name)
        metadata_path = getattr(distribution, "_path", None)

        if metadata_path is None:
            raise RuntimeError(
                f"Cannot determine metadata directory for {name}"
            )

        result.update({
            "success": True,
            "metadata_path": str(
                pathlib.Path(metadata_path).resolve()
            ),
            "distribution_name": (
                distribution.metadata.get("Name") or name
            ),
            "version": distribution.version,
        })

    elif operation == "distributions":
        top_level_name = name.split(".", 1)[0]
        mapping = importlib.metadata.packages_distributions()

        result.update({
            "success": True,
            "distributions": mapping.get(top_level_name, []),
        })

    else:
        raise ValueError(f"Unknown operation: {operation}")

except Exception as exc:
    result.update({
        "success": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
    })

print(json.dumps(result, ensure_ascii=False))
"""

    process = subprocess.run(
        [
            str(VENV_PYTHON),
            "-c",
            helper_code,
            operation,
            name,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    stdout = decode_output(process.stdout)
    stderr = decode_output(process.stderr)

    result: dict[str, Any] | None = None

    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue

        try:
            result = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    if result is None:
        raise RuntimeError(
            "无法解析虚拟环境查询结果。\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    if not result.get("success"):
        raise RuntimeError(
            f"查询失败：{operation} {name}\n"
            f"{result.get('error_type')}: "
            f"{result.get('error')}\n"
            f"stderr:\n{stderr}"
        )

    return result


def get_environment_search_roots() -> list[Path]:
    """获取虚拟环境中的标准库和 site-packages 路径。

    Returns:
        可用于查找缺失文件的根目录。
    """
    helper_code = r"""
import json
import site
import sysconfig

roots = []

for path in site.getsitepackages():
    roots.append(path)

paths = sysconfig.get_paths()

for key in ("stdlib", "platstdlib", "purelib", "platlib"):
    path = paths.get(key)
    if path:
        roots.append(path)

print(json.dumps(list(dict.fromkeys(roots)), ensure_ascii=False))
"""

    process = subprocess.run(
        [
            str(VENV_PYTHON),
            "-c",
            helper_code,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    stdout = decode_output(process.stdout)
    stderr = decode_output(process.stderr)

    if process.returncode != 0:
        raise RuntimeError(
            "无法获取虚拟环境路径。\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    for line in reversed(stdout.splitlines()):
        try:
            values = json.loads(line)
            return [Path(value) for value in values]
        except json.JSONDecodeError:
            continue

    raise RuntimeError(
        "无法解析虚拟环境搜索路径。\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def copy_path(
    source: Path,
    destination: Path,
) -> list[str]:
    """复制文件或目录。

    Args:
        source: 源文件或源目录。
        destination: 目标路径。

    Returns:
        已复制的目标路径。

    Raises:
        FileNotFoundError: 源路径不存在。
    """
    if not source.exists():
        raise FileNotFoundError(f"源路径不存在：{source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
        )
    else:
        shutil.copy2(source, destination)

    return [str(destination)]


def copy_distribution_metadata(
    distribution_name: str,
) -> list[str]:
    """复制发行包的 dist-info 或 egg-info。

    Args:
        distribution_name: 发行包名。

    Returns:
        已复制的目标路径。
    """
    name = distribution_name.strip().strip("'\"")
    result = run_environment_query("metadata", name)

    source = Path(result["metadata_path"])
    destination = INTERNAL_DIR / source.name

    return copy_path(source, destination)


def copy_module_from_environment(module_name: str) -> list[str]:
    """从虚拟环境复制缺失模块到 _internal。

    对包复制整个顶层包，避免连续缺少相邻模块和数据文件。

    Args:
        module_name: 缺失模块名，例如 http.cookies。

    Returns:
        已复制的目标路径。
    """
    result = run_environment_query("module", module_name)

    top_level_name = result["top_level_name"]
    copied_paths: list[str] = []

    if result["is_package"]:
        for location_text in result["locations"]:
            source = Path(location_text)
            destination = INTERNAL_DIR / top_level_name
            copied_paths.extend(copy_path(source, destination))
    else:
        origin_text = result.get("origin")

        if not origin_text or origin_text in {"built-in", "frozen"}:
            raise RuntimeError(
                f"{module_name} 是内置或冻结模块，"
                "不能通过普通文件复制修复。"
            )

        source = Path(origin_text)
        destination = INTERNAL_DIR / source.name
        copied_paths.extend(copy_path(source, destination))

    # 尝试复制该模块对应发行包的元数据。
    try:
        distribution_result = run_environment_query(
            "distributions",
            top_level_name,
        )

        for distribution_name in distribution_result.get(
            "distributions",
            [],
        ):
            try:
                copied_paths.extend(
                    copy_distribution_metadata(distribution_name)
                )
            except Exception as exc:
                write_log(
                    f"[警告] 元数据复制失败："
                    f"{distribution_name}: {exc}"
                )
    except Exception as exc:
        write_log(
            f"[警告] 无法查询模块对应发行包："
            f"{top_level_name}: {exc}"
        )

    return list(dict.fromkeys(copied_paths))


def repair_tzdata() -> list[str]:
    """复制 tzdata 包及其元数据。

    Returns:
        已复制的目标路径。
    """
    copied_paths = copy_module_from_environment("tzdata")

    try:
        copied_paths.extend(
            copy_distribution_metadata("tzdata")
        )
    except Exception as exc:
        write_log(f"[警告] tzdata 元数据复制失败：{exc}")

    return list(dict.fromkeys(copied_paths))


def parse_file_not_found(output: str) -> str | None:
    """从异常输出中提取 FileNotFoundError 路径。

    Args:
        output: EXE 的异常输出。

    Returns:
        缺失文件路径；无法识别时返回 None。
    """
    for line in reversed(output.splitlines()):
        line = line.strip()

        if not line.startswith("FileNotFoundError:"):
            continue

        value = line.split("FileNotFoundError:", 1)[1].strip()

        value = re.sub(
            r"^\[Errno\s+2\]\s*"
            r"No such file or directory:\s*",
            "",
            value,
        )

        return value.strip().strip("'\"")

    return None


def parse_missing_item(output: str) -> MissingItem | None:
    """从启动日志中识别可自动修复的缺失项。

    Args:
        output: EXE 启动日志。

    Returns:
        缺失项；无法识别时返回 None。
    """
    for pattern in MODULE_PATTERNS:
        match = pattern.search(output)
        if match:
            return MissingItem(
                kind="module",
                name=match.group(1).strip(),
            )

    for pattern in METADATA_PATTERNS:
        match = pattern.search(output)
        if match:
            return MissingItem(
                kind="metadata",
                name=match.group(1).strip().strip("'\""),
            )

    if ZONEINFO_PATTERN.search(output):
        return MissingItem(
            kind="tzdata",
            name="tzdata",
        )

    missing_file = parse_file_not_found(output)
    if missing_file:
        return MissingItem(
            kind="file",
            name=missing_file,
        )

    return None


def copy_missing_bundle_file(
    missing_path_text: str,
) -> list[str]:
    """从虚拟环境复制 _internal 中缺失的文件。

    如果缺失文件属于某个顶层包，则复制整个顶层包。例如：
    Cython/Utility/CppSupport.cpp 会触发复制整个 Cython 包。

    Args:
        missing_path_text: 异常中报告的缺失文件路径。

    Returns:
        已复制的目标路径。
    """
    missing_path = Path(missing_path_text)

    try:
        relative_path = missing_path.relative_to(INTERNAL_DIR)
    except ValueError as exc:
        raise RuntimeError(
            f"缺失文件不在 _internal 中，无法自动映射："
            f"{missing_path}"
        ) from exc

    if not relative_path.parts:
        raise RuntimeError(
            f"无法识别缺失文件相对路径：{missing_path}"
        )

    search_roots = get_environment_search_roots()
    top_level_name = relative_path.parts[0]

    for root in search_roots:
        exact_source = root / relative_path

        if not exact_source.exists():
            continue

        package_source = root / top_level_name
        package_destination = INTERNAL_DIR / top_level_name

        if package_source.is_dir():
            shutil.copytree(
                package_source,
                package_destination,
                dirs_exist_ok=True,
            )
            return [str(package_destination)]

        destination = INTERNAL_DIR / relative_path
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(exact_source, destination)

        return [str(destination)]

    searched_paths = [
        str(root / relative_path)
        for root in search_roots
    ]

    raise FileNotFoundError(
        "在虚拟环境中没有找到对应源文件：\n"
        + "\n".join(searched_paths)
    )


def terminate_process_tree(
    process: subprocess.Popen[bytes],
) -> None:
    """终止测试进程及其子进程。

    Args:
        process: 需要终止的进程。
    """
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            [
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def run_exe_test() -> tuple[bool, str, int | None]:
    """运行 EXE，并判断启动阶段是否存在异常。

    在观察时间内仍运行不等于成功：
    如果输出中已经出现 Traceback，仍判定为失败。

    Returns:
        三元组：
        - 是否启动成功；
        - 捕获到的输出；
        - 退出码，测试期间仍运行时为 None。
    """
    process = subprocess.Popen(
        [str(EXE_PATH)],
        cwd=str(EXE_PATH.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = process.communicate(
            timeout=STARTUP_OBSERVE_SECONDS
        )

        output = (
            decode_output(stdout)
            + "\n"
            + decode_output(stderr)
        ).strip()

        has_error = contains_runtime_error(output)

        success = (
            process.returncode == 0
            and not has_error
        )

        return success, output, process.returncode

    except subprocess.TimeoutExpired:
        terminate_process_tree(process)

        stdout, stderr = process.communicate()

        output = (
            decode_output(stdout)
            + "\n"
            + decode_output(stderr)
        ).strip()

        has_error = contains_runtime_error(output)

        return not has_error, output, None


def save_manifest(records: list[RepairRecord]) -> None:
    """保存修复清单。

    Args:
        records: 全部修复记录。
    """
    data = {
        "exe": str(EXE_PATH),
        "venv_python": str(VENV_PYTHON),
        "internal_dir": str(INTERNAL_DIR),
        "records": [asdict(record) for record in records],
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def launch_exe_normally() -> None:
    """修复成功后正常启动 EXE。"""
    creation_flags = 0

    if os.name == "nt":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        )

    subprocess.Popen(
        [str(EXE_PATH)],
        cwd=str(EXE_PATH.parent),
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def validate_configuration() -> None:
    """检查配置路径。"""
    if not EXE_PATH.is_file():
        raise FileNotFoundError(
            f"找不到 EXE：{EXE_PATH}"
        )

    if not VENV_PYTHON.is_file():
        raise FileNotFoundError(
            f"找不到虚拟环境 Python：{VENV_PYTHON}"
        )

    if not INTERNAL_DIR.is_dir():
        raise FileNotFoundError(
            f"找不到 _internal：{INTERNAL_DIR}\n"
            "该脚本只适用于 PyInstaller onedir 模式。"
        )


def main() -> None:
    """自动运行 EXE，并循环修复缺失依赖。"""
    validate_configuration()

    LOG_PATH.write_text("", encoding="utf-8")

    repaired_items: set[MissingItem] = set()
    records: list[RepairRecord] = []

    write_log("=" * 70)
    write_log("PyInstaller EXE 自动依赖修复开始")
    write_log(f"EXE：{EXE_PATH}")
    write_log(f"虚拟环境：{VENV_PYTHON}")
    write_log(f"_internal：{INTERNAL_DIR}")
    write_log("=" * 70)

    for round_number in range(1, MAX_REPAIR_ROUNDS + 1):
        write_log(f"\n[第 {round_number} 轮] 启动 EXE")

        success, output, return_code = run_exe_test()

        write_log(
            f"退出码："
            f"{return_code if return_code is not None else '仍在运行'}"
        )

        if output:
            write_log("---------- 程序输出 ----------")
            write_log(output)
            write_log("------------------------------")
        else:
            write_log("[提示] 未捕获到控制台输出。")

        if success:
            write_log("\n启动阶段未发现异常，自动修复完成。")
            save_manifest(records)

            if LAUNCH_AFTER_SUCCESS:
                launch_exe_normally()
                write_log("已重新正常启动 EXE。")

            return

        if any(
            pattern.search(output)
            for pattern in DLL_ERROR_PATTERNS
        ):
            write_log(
                "\n检测到 DLL 加载错误，停止自动修复。"
            )
            write_log(
                "该类错误需要检查 .pyd 依赖、VC++ 运行库、"
                "Paddle/OpenCV/Qt 等二进制依赖。"
            )
            save_manifest(records)
            return

        missing_item = parse_missing_item(output)

        if missing_item is None:
            write_log(
                "\n无法从异常中识别可自动修复的缺失依赖。"
            )
            write_log(
                "请查看 auto_repair.log 中的完整错误。"
            )
            save_manifest(records)
            return

        write_log(
            f"检测到缺失项："
            f"kind={missing_item.kind}, "
            f"name={missing_item.name}"
        )

        if missing_item in repaired_items:
            write_log(
                "\n同一缺失项已经复制过，但错误仍然存在。"
            )
            write_log(
                "这通常说明问题不是普通文件缺失，而是"
                "包路径、二进制依赖、包数据或冻结导入机制问题。"
            )
            save_manifest(records)
            return

        try:
            if missing_item.kind == "module":
                copied_paths = copy_module_from_environment(
                    missing_item.name
                )
            elif missing_item.kind == "metadata":
                copied_paths = copy_distribution_metadata(
                    missing_item.name
                )
            elif missing_item.kind == "tzdata":
                copied_paths = repair_tzdata()
            elif missing_item.kind == "file":
                copied_paths = copy_missing_bundle_file(
                    missing_item.name
                )
            else:
                raise RuntimeError(
                    f"不支持的修复类型：{missing_item.kind}"
                )

        except Exception as exc:
            write_log(
                f"\n自动复制失败："
                f"{type(exc).__name__}: {exc}"
            )
            save_manifest(records)
            return

        repaired_items.add(missing_item)

        record = RepairRecord(
            round_number=round_number,
            kind=missing_item.kind,
            name=missing_item.name,
            copied_paths=copied_paths,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        records.append(record)
        save_manifest(records)

        write_log("已复制：")
        for copied_path in copied_paths:
            write_log(f"  - {copied_path}")

    write_log(
        f"\n达到最大修复轮数：{MAX_REPAIR_ROUNDS}"
    )
    save_manifest(records)


if __name__ == "__main__":
    main()