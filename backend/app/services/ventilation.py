"""通风系统业务规则：状态流转、字段校验与筛选口径都收在这里。

受影响清单：直接读瓦斯超限报警台账（store.alarms），与瓦斯监测页同源，
按所属巷道匹配到每台通风设备。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "ventilation"
REQUIRED_FIELDS = ["设备编号", "设备类型", "额定风量"]
STATUS_ORDER = ["正常", "降频运行", "故障停机", "已更换"]
ACTION_RULES = {"降频运行": "降频运行", "故障停机": "故障停机", "办理更换": "已更换"}
NEGATIVE_ACTIONS = []


def _affected_alarms(roadway: str) -> list[str]:
    """该巷道名下的超限报警结论，来自瓦斯侧写入的同一份台账。"""
    return [
        f"{alarm.get('测点编号')}：{alarm.get('结论')}（{alarm.get('报警时间')}）"
        for alarm in store.alarms(area=roadway)
    ]


class VentilationService:
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
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._attach(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._attach(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"通风设备 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于通风系统可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"通风设备已{action}"

    def _attach(self, row: dict[str, Any]) -> dict[str, Any]:
        """补出受影响清单；返回副本，不动台账里的原始记录。"""
        data = dict(row)
        data["受影响清单"] = _affected_alarms(str(row.get("所属巷道") or "").strip())
        return data
