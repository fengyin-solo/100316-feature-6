"""通风系统业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "ventilation"
REQUIRED_FIELDS = ["设备编号", "设备类型", "额定风量"]
STATUS_ORDER = ["正常", "降频运行", "故障停机", "已更换"]
ACTION_RULES = {"降频运行": "降频运行", "故障停机": "故障停机", "办理更换": "已更换"}
NEGATIVE_ACTIONS = []


class VentilationService:
    def roadway_names(self) -> list[str]:
        """从通风台账归集巷道名称，供瓦斯测点登记时对齐所在区域。"""
        names: list[str] = []
        for row in store.rows(MODULE):
            name = str(row.get("所属巷道") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def record_gas_alarm(
        self, gas_entry: dict[str, Any], *, at: str
    ) -> list[dict[str, Any]]:
        """把超限报警结论回写到同巷道通风设备台账的受影响清单。

        受影响清单只保存瓦斯测点引用与回写时刻的结论快照；
        清单明细从瓦斯记录实时读取，两处报警始终同源。
        同一条瓦斯记录重复回写（重复超限报警提交）只登记一次。
        """
        gas_id = int(gas_entry.get("id", 0))
        area = str(gas_entry.get("所在区域") or "").strip()
        matched = [
            row for row in store.rows(MODULE)
            if str(row.get("所属巷道") or "").strip() == area
        ]
        snapshot = {
            "gas_id": gas_id,
            "测点编号": gas_entry.get("测点编号"),
            "报警时刻": at,
            "瓦斯浓度": gas_entry.get("瓦斯浓度"),
            "结论": "超限报警",
        }
        for row in matched:
            ledger = row.setdefault("受影响清单", [])
            if not any(int(item.get("gas_id", 0)) == gas_id for item in ledger):
                ledger.append(snapshot)
        return matched

    def affected_alarms(self) -> list[dict[str, Any]]:
        """汇总通风台账受影响清单：报警内容实时取自瓦斯记录，保证两边同源。"""
        result: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            for ref in row.get("受影响清单", []) or []:
                gas_id = int(ref.get("gas_id", 0))
                gas_entry = store.find("gas", gas_id)
                item = {
                    "设备编号": row.get("设备编号"),
                    "所属巷道": row.get("所属巷道"),
                    "回写时刻": ref.get("报警时刻"),
                    "回写结论": ref.get("结论"),
                }
                if gas_entry is not None:
                    item.update({
                        "gas_id": gas_id,
                        "测点编号": gas_entry.get("测点编号"),
                        "所在区域": gas_entry.get("所在区域"),
                        "瓦斯浓度": gas_entry.get("瓦斯浓度"),
                        "测点当前状态": gas_entry.get("status"),
                        "监测时刻": gas_entry.get("监测时刻"),
                    })
                else:
                    # 瓦斯记录被归档时退回快照，避免台账清单出现死链
                    item.update({
                        "gas_id": gas_id,
                        "测点编号": ref.get("测点编号"),
                        "所在区域": row.get("所属巷道"),
                        "瓦斯浓度": ref.get("瓦斯浓度"),
                        "测点当前状态": "记录已归档",
                        "监测时刻": None,
                    })
                result.append(item)
        return result

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
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

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
