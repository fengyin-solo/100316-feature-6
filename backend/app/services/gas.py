"""瓦斯监测业务规则：状态流转、区域对齐、超限回写都收在这里。

状态机（强制顺序，不许跳级、不许回退）：
    正常 --偏高预警--> 浓度偏高 --超限报警--> 超限报警 --处置确认--> 已处置

存量数据里可能存在跳过中间环节的历史记录，那是当时的人工判定：
这里不补链路、不纠偏，只保证从当前状态往后的每一步仍然合法。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.ventilation import VentilationService
from app.store import store

MODULE = "gas"
REQUIRED_FIELDS = ["测点编号", "所在区域", "瓦斯浓度"]
STATUS_ORDER = ["正常", "浓度偏高", "超限报警", "已处置"]
# 动作只能把测点从"相邻的上一个"状态推进到目标状态
ACTION_RULES = {"偏高预警": "浓度偏高", "超限报警": "超限报警", "处置确认": "已处置"}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class GasService:
    def __init__(self) -> None:
        self.ventilation = VentilationService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("测点编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self._present(row) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """登记测点：必填字段齐全，且所在区域必须能在通风系统巷道里对上。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        area = str(values.get("所在区域") or "").strip()
        roadways = self.ventilation.roadway_names()
        if area not in roadways:
            hint = "、".join(roadways) if roadways else "通风台账暂未登记巷道"
            return None, f"所在区域「{area}」与通风系统巷道对不上，可选巷道：{hint}"

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["测点编号", "所在区域", "瓦斯浓度", "一氧化碳浓度", "温度", "风速", "监测时刻"]:
            value = values.get(field)
            if value is not None and str(value).strip():
                entry[field] = value
        entry.setdefault("监测时刻", _now_text())
        entry["status"] = STATUS_ORDER[0]
        self._apply_flags(entry)
        rows.append(entry)
        return self._present(entry), None

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str, bool]:
        """推进测点状态。

        返回 (测点, 说明, 是否真正生效)：重复提交时测点原样返回、不产生副作用，
        第三个结果用于区分"本次生效"与"此前已生效"。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"瓦斯测点 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于瓦斯监测可执行范围", False

        current = str(entry.get("status") or "")
        target = ACTION_RULES[action]
        if current not in STATUS_ORDER:
            return None, (
                f"测点当前状态「{current}」属于历史人工判定记录，"
                f"不纳入线上顺序流转，状态原样保留"
            ), False
        current_index = STATUS_ORDER.index(current)
        target_index = STATUS_ORDER.index(target)

        if target_index == current_index:
            # 幂等：同一条记录重复提交同一个动作，只第一次生效
            return self._present(entry), (
                f"测点已处于「{current}」，「{action}」此前已生效，"
                f"本次为重复提交，状态保持不变"
            ), False
        if target_index < current_index:
            # 不许回退：已处置完再点偏高预警，原样退回
            return None, (
                f"测点当前为「{current}」，状态只能按"
                f"{'→'.join(STATUS_ORDER)}顺序前进，不能再执行「{action}」；"
                f"请求原样退回，状态保持「{current}」"
            ), False
        if target_index > current_index + 1:
            return None, (
                f"不能从「{current}」直接{action}，需先经过"
                f"「{STATUS_ORDER[target_index - 1]}」环节，不允许跳级"
            ), False

        entry["status"] = target
        self._apply_flags(entry)
        message = f"瓦斯测点已{action}"
        if target == "超限报警":
            matched = self.ventilation.record_gas_alarm(entry, at=_now_text())
            if matched:
                names = "、".join(str(row.get("设备编号", "")) for row in matched)
                message += f"，报警结论已回写通风台账受影响清单（巷道设备：{names}）"
            else:
                message += "；通风台账中暂无该巷道的设备记录，回写未找到落点，请先核对巷道"
        return self._present(entry), message, True

    def _apply_flags(self, entry: dict[str, Any]) -> None:
        status = str(entry.get("status") or "")
        entry["pending"] = status != STATUS_ORDER[-1]
        entry["abnormal"] = status in ("浓度偏高", "超限报警")

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表/明细统一口径：页面读到的「测点状态」与内部 status 同源。"""
        row["测点状态"] = row.get("status")
        return row
