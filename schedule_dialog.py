from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
                             QTimeEdit, QDialogButtonBox, QWidget, QMessageBox,
                             QPushButton, QCheckBox)
from PyQt5.QtCore import QTime
from PyQt5.QtGui import QFont

class ScheduleDialog(QDialog):
    """
    一个用于设置定时任务（自动开始/自动关机）的独立对话框。
    支持多个任务周期的设置，并包含时间冲突验证。
    """
    default_settings = {
        'tasks': {
            'single': {'name': '单端任务', 'tab_index': 0, 'start_enabled': False, 'end_enabled': False,
                       'start_time': QTime(2, 5), 'end_time': QTime(10, 0)},
            'hoard':  {'name': '屯仓任务', 'tab_index': 1, 'start_enabled': False, 'end_enabled': False,
                       'start_time': QTime(1, 2), 'end_time': QTime(2, 2)},
            'dual':   {'name': '双端任务', 'tab_index': 2, 'start_enabled': False, 'end_enabled': False,
                       'start_time': QTime(0, 3), 'end_time': QTime(1, 0)}
        },
        'close_small_checkbox': True,
        'shutdown': {'enabled': False, 'time': QTime(10, 5)}
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        # 【重构】用于存储最终设置结果的字典，采用新的数据结构
        # 默认值仅用于初始化，实际值会由 set_settings 加载
        self.settings = {}

        # 初始化UI组件和布局
        self.task_widgets = {}  # 为每个任务创建一组控件，并存储起来方便后续访问
        self.init_ui()
        self.set_settings(self.default_settings)

    def init_ui(self):
        """初始化对话框的用户界面。"""
        self.setWindowTitle("定时任务设置")

        base_font = QFont("Microsoft YaHei", 12)  # 稍微调整字体大小以适应更多内容
        self.setFont(base_font)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # ===== 创建三个任务周期的设置框 =====

        for task_key, config in self.default_settings['tasks'].items():
            group = QGroupBox(f"{config['name']}")  # 创建组名
            group.setCheckable(True)                # 主开关，控制整个周期是否启用
            group.setChecked(False)                 # 默认不能用

            layout_inner = QHBoxLayout()

            # 开始时间
            start_time_label = QLabel("开始:")
            start_time_edit = QTimeEdit()
            start_time_edit.setDisplayFormat("HH:mm")

            # 结束时间
            end_time_label = QLabel("结束:")
            end_time_edit = QTimeEdit()
            end_time_edit.setDisplayFormat("HH:mm")

            layout_inner.addWidget(start_time_label)
            layout_inner.addWidget(start_time_edit)
            layout_inner.addSpacing(20)  # 增加一些间距
            layout_inner.addWidget(end_time_label)
            layout_inner.addWidget(end_time_edit)
            layout_inner.addStretch()

            if task_key == 'dual':
                # 对于双端的设置，新增一个结束后关闭小号
                # 步骤 A: 将包含时间控件的水平布局作为第一行，添加到垂直主布局中
                group_main_layout = QVBoxLayout()
                group_main_layout.addLayout(layout_inner)

                # 步骤 B: 创建“新组件”——复选框
                self.close_small_checkbox = QCheckBox("结束后关闭小号")
                self.close_small_checkbox.setChecked(self.default_settings['close_small_checkbox'])
                # 步骤 C: 将复选框作为第二行，添加到垂直主布局中
                group_main_layout.addWidget(self.close_small_checkbox)

                # 步骤 D: 将这个配置好的垂直主布局应用到 GroupBox 上
                group.setLayout(group_main_layout)
            else:
                # 对于其他任务，直接将水平布局应用到 GroupBox 上
                group.setLayout(layout_inner)

            # 将 GroupBox 添加到最外层的对话框布局中
            main_layout.addWidget(group)

            # 将控件存储起来，方便后续读写数据
            self.task_widgets[task_key] = {
                'group': group,
                'start_time_edit': start_time_edit,
                'end_time_edit': end_time_edit
            }

        # --- 定时自动关机部分 ---
        self.shutdown_group = QGroupBox("定时自动关机")
        self.shutdown_group.setCheckable(True)
        self.shutdown_group.setChecked(False)

        shutdown_layout_inner = QHBoxLayout()
        shutdown_layout_inner.addWidget(QLabel("关机时间:"))
        self.shutdown_time_edit = QTimeEdit()
        self.shutdown_time_edit.setDisplayFormat("HH:mm")
        shutdown_layout_inner.addWidget(self.shutdown_time_edit)
        shutdown_layout_inner.addStretch()
        self.shutdown_group.setLayout(shutdown_layout_inner)
        main_layout.addWidget(self.shutdown_group)
        # =================================

        # 其他按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)

        main_layout.addLayout(button_layout)

    def _collect_settings_from_ui(self) -> dict:
        """从UI控件收集当前的配置，返回一个新的设置字典。"""
        new_settings = {
            'tasks': {},
            'close_small_checkbox': True,
            'shutdown': {},
        }
        # 收集任务周期设置
        for task_key, widgets in self.task_widgets.items():
            # 只有当整个组被勾选时，才认为开始和结束都启用了
            is_enabled = widgets['group'].isChecked()   # 任务的开启情况
            new_settings['tasks'][task_key] = {
                'name': self.default_settings['tasks'][task_key]['name'],  # 保留原始名称和索引
                'tab_index': self.default_settings['tasks'][task_key]['tab_index'],
                'start_enabled': is_enabled,
                'end_enabled': is_enabled,
                'start_time': widgets['start_time_edit'].time(),
                'end_time': widgets['end_time_edit'].time()
            }

        # 关闭小号的设置
        new_settings['close_small_checkbox'] = self.close_small_checkbox.isChecked()    # 关闭小号

        # 收集关机设置
        new_settings['shutdown'] = {
            'enabled': self.shutdown_group.isChecked(),
            'time': self.shutdown_time_edit.time()
        }
        return new_settings

    def _validate_conflicts(self, settings_to_check: dict) -> tuple[bool, str]:
        """验证所有已启用的任务时间段是否有重叠。"""
        tasks = settings_to_check['tasks']
        enabled_periods = []

        for task_key, config in tasks.items():
            if config.get('start_enabled', False):
                start_t = config['start_time']
                end_t = config['end_time']

                # 【修改点1】检查单个时间段有效性，返回通用错误信息
                if start_t >= end_t:
                    return True, "结束时间必须晚于开始时间。"

                enabled_periods.append({"start": start_t, "end": end_t})  # 不再需要name

        if len(enabled_periods) < 2: return False, ""

        from itertools import combinations  # 移到需要时再导入
        for period1, period2 in combinations(enabled_periods, 2):
            # 【修改点2】检查重叠，返回通用错误信息
            if max(period1["start"], period2["start"]) <= min(period1["end"], period2["end"]):
                return True, "任务时间范围不能有重叠。"

        return False, ""

    def accept(self):
        """
        当用户点击“OK”时，先验证，再保存和关闭。
        """
        # 1. 从UI控件收集当前用户的设置
        current_ui_settings = self._collect_settings_from_ui()

        # 2. 调用验证函数
        has_conflict, message = self._validate_conflicts(current_ui_settings)

        # 3. 根据验证结果决定下一步
        if has_conflict:
            # 如果有冲突，显示警告信息，并且【不】关闭对话框
            QMessageBox.warning(self, "时间设置错误", message)
            return  # 退出 accept 函数，不执行关闭操作

        # 4. 如果没有冲突，将新设置保存到 self.settings
        self.settings = current_ui_settings

        # 5. 调用父类的accept()来关闭对话框并返回QDialog.Accepted状态码
        super().accept()

    def get_settings(self) -> dict:
        """提供一个公共接口，让外部调用者可以获取最终的设置结果。"""
        return self.settings

    def set_settings(self, settings: dict):
        """
        用于从外部加载已有设置，并更新UI的显示状态。
        """
        # 恢复任务周期设置
        for task_key, config in settings['tasks'].items():
            if task_key in self.task_widgets:
                widgets = self.task_widgets[task_key]
                # 开始和结束是联动的，所以只检查一个即可
                is_enabled = config.get('start_enabled', False)
                widgets['group'].setChecked(is_enabled)
                widgets['start_time_edit'].setTime(config.get('start_time', QTime(8, 0)))
                widgets['end_time_edit'].setTime(config.get('end_time', QTime(12, 0)))
        self.close_small_checkbox.setChecked(settings.get("close_small_checkbox", True))
        # 恢复关机设置
        shutdown_cfg = settings.get('shutdown', {})
        self.shutdown_group.setChecked(shutdown_cfg.get('enabled', False))
        self.shutdown_time_edit.setTime(shutdown_cfg.get('time', QTime(23, 30)))

        self.settings = self._collect_settings_from_ui()

# ==============================================================================
#                      独立的演示/测试启动案例
# ==============================================================================
if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTime

    app = QApplication(sys.argv)

    # 1. 创建对话框实例
    dialog = ScheduleDialog()

    # 2. (可选) 模拟加载一个已有的、符合新数据结构的设置
    print("加载模拟的初始设置...")
    # 将这个模拟的初始设置加载到对话框的UI上
    dialog.set_settings(dialog.default_settings)

    # 3. 显示对话框并等待用户交互
    print("\n请在弹出的对话框中进行设置...")
    print("提示：您可以尝试设置一个冲突的时间段（例如，将屯仓任务时间改为 10:00-11:00），然后点击“确定”来测试冲突验证功能。")

    # 如果用户点击“确定”并且验证通过，它返回 QDialog.Accepted
    result_code = dialog.exec_()

    # 4. 根据用户的操作，打印最终的结果
    if result_code == QDialog.Accepted:
        final_settings = dialog.get_settings()
        print("\n用户点击了 'OK' 并且时间验证通过，最终设置为:")

        # 遍历打印每个任务的设置
        for task_key, config in final_settings['tasks'].items():
            task_name = config['name']
            is_enabled = config['start_enabled']  # start_enabled 和 end_enabled 是联动的
            print(f"\n  - {task_name}: {'启用' if is_enabled else '禁用'}")
            if is_enabled:
                start_str = config['start_time'].toString('HH:mm')
                end_str = config['end_time'].toString('HH:mm')
                print(f"    时间范围: {start_str} - {end_str}")
            if task_name == '双端任务':
                print(f"    关闭小号: {'启用' if final_settings['close_small_checkbox'] else '禁用'}")

        # 打印关机设置
        shutdown_cfg = final_settings['shutdown']
        is_shutdown_enabled = shutdown_cfg['enabled']
        print(f"\n  - 定时关机: {'启用' if is_shutdown_enabled else '禁用'}")
        if is_shutdown_enabled:
            shutdown_str = shutdown_cfg['time'].toString('HH:mm')
            print(f"    关机时间: {shutdown_str}")

    else:
        print("\n用户点击了 'Cancel' 或关闭了窗口，设置未被应用。")