# 月饼的滚仓工具（开源版）

作者：月饼

这是一个基于 PyQt5、Windows API、图像识别和 OCR 的桌面自动化工具。程序通过绑定目标窗口、识别画面元素并模拟输入，完成特定场景下的自动化操作。

> 注意：本项目仅供学习、研究和个人自动化实践。使用自动化工具可能违反第三方软件或游戏平台的服务条款，并可能带来账号、数据或系统操作风险。请自行确认使用场景的合法性和合规性。

## 功能概览

![](/debug/preview.png)

- 绑定 Windows 窗口并转换窗口坐标
- 基于模板匹配和 OCR 识别画面内容
- 支持双端、屯仓、测试等任务模式
- 支持全局快捷键开始/停止
- 支持保存和加载 JSON 配置
- 支持定时任务和可取消的自动关机提示

## 运行环境

- 操作系统：Windows
- Python：Python 3.10
- 分辨率：目标窗口客户端区域需为 `1440x1080`
- 权限：需要管理员权限

## 安装教程

以下命令默认在 Windows 的 Anaconda Prompt 或 PowerShell 中执行。

1. 进入项目目录

2. 创建 conda 环境

```powershell
conda create -n yuebing-open python=3.10 -y
```

3. 激活环境

```powershell
conda activate yuebing-open
```

4. 升级 pip （可选）

```powershell
python -m pip install --upgrade pip
```

5. 安装依赖

```powershell
pip install -r requirements.txt
```

依赖的库很多，安装会比较慢，请耐心等待。

6. 启动程序

```powershell
python main.py
```

如果安装 PaddlePaddle 失败，通常是 Python 版本或系统平台不匹配。请确认当前环境是 Python 3.10：

```powershell
python --version
```

7. 打包成 exe （可选）

```powershell
PyInstaller main.spec --clean --noconfirm
```

库比较多，我建议你用附带的 main.spec 打包，不然打包完很可能无法运行

## 启动

在 `开源版` 目录下运行：

```powershell
python main.py
```

程序启动后：

1. 选择并绑定目标窗口。
2. 确认目标窗口客户端区域为 `1440x1080`。
3. 根据需要切换任务标签页并设置参数。
4. 点击开始，或使用设置页中的快捷键。

## 配置文件

程序支持从 UI 保存和加载 JSON 配置。示例文件见：

```text
config.example.json
```

你可以在程序中点击“加载配置”选择该文件，也可以将它复制为：

```text
config_bullets/config.json
```

快捷键配置由程序单独保存到：

```text
config_bullets/hotkeys.json
```

## 目录说明
```text
config_bullets/          本地配置目录
debug/                   调试图片输出目录
运行日志/                 每次运行后日志目录
template/                存放模板图片目录
inference/               存放ocr参数目录
```

## 文件说明
```text
main.py                  程序入口
ui.py                    主界面和配置管理
worker.py                自动化任务线程
window_operator.py       窗口绑定、坐标转换、输入模拟
template_recognizer.py   模板匹配和图像处理
ocr_recognizer.py        OCR 识别
resolution_m.py          分辨率坐标配置
schedule_dialog.py       定时任务设置对话框
shutdown_dialog.py       自动关机倒计时对话框
main.spec                PyInstaller 打包配置文件
```

## 自动关机说明

项目包含自动关机能力。该能力默认需要用户在定时任务中启用，并会在真正关机前弹出倒计时窗口，用户可以取消。

Windows 下执行的命令类似：

```powershell
shutdown /s /t 0 /f /c "自动化任务完成，系统将关机"
```

请在使用定时任务前确认你理解该行为。

## 开源版说明

本开源版已移除商业授权入口，不包含卡密、订单号、授权服务器地址、运行日志、数据库和打包产物。

## 许可证

本项目使用 MIT License，详见 `LICENSE`。
