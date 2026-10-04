"""瓦斯监测业务规则：状态流转、字段校验与筛选口径都收在这里。

状态机：正常 → 浓度偏高 → 超限报警 → 已处置，逐级流转、不许跳级；
已处置是终点，再发动作原样退回；同一动作重复提交只生效第一次。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.store import store

MODULE = "gas"
REQUIRED_FIELDS = ["测点编号", "所在区域", "瓦斯浓度"]
STATUS_ORDER = ["正常", "浓度偏高", "超限报警", "已处置"]
ACTION_RULES = {"偏高预警": "浓度偏高", "超限报警": "超限报警", "处置确认": "已处置"}
# 每个状态下一步唯一允许的动作；已处置不在表里，是终点
NEXT_ACTION = {"正常": "偏高预警", "浓度偏高": "超限报警", "超限报警": "处置确认"}
TERMINAL_STATUS = "已处置"
ABNORMAL_STATUSES = {"浓度偏高", "超限报警"}
ALARM_STATUS = "超限报警"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _roadways() -> list[str]:
    """通风系统台账里的巷道清单，测点所在区域必须落在其中。"""
    seen: dict[str, None] = {}
    for row in store.rows("ventilation"):
        name = str(row.get("所属巷道") or "").strip()
        if name:
            seen.setdefault(name)
    return sorted(seen)


class GasService:
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
        return [self._attach(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        data = self._attach(entry)
        data["alarms"] = store.alarms(point=str(entry.get("测点编号") or ""))
        return data

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        area = str(values.get("所在区域") or "").strip()
        if area:
            roadways = _roadways()
            if area not in roadways:
                problems.append(
                    f"所在区域「{area}」在通风系统巷道台账中不存在，可选：{'、'.join(roadways) or '（通风台账暂无巷道）'}"
                )
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["action_log"] = []
        rows.append(entry)
        return self._attach(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        conclusion: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """执行动作，返回（明细、说明）。被拦下时明细数为 None；重复提交返回原明细、不再生效。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"瓦斯测点 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于瓦斯监测可执行范围"
        log = entry.setdefault("action_log", [])
        if log and log[-1].get("action") == action:
            return self._attach(entry), f"「{action}」已提交过，测点保持「{entry['status']}」，重复提交不再生效"
        status = str(entry.get("status") or "")
        if status == TERMINAL_STATUS:
            return None, f"测点已处置完成，「{action}」原样退回，记录不再变动"
        expected = NEXT_ACTION.get(status)
        if expected is None:
            return None, f"测点当前状态「{status}」不在标准链路里，按当时人工判定保留，不再流转"
        if action != expected:
            return None, (
                f"测点须按 {'→'.join(STATUS_ORDER)} 逐级流转，"
                f"当前「{status}」下一步只能执行「{expected}」，「{action}」被拦下"
            )
        if ACTION_RULES[action] == ALARM_STATUS:
            roadways = _roadways()
            area = str(entry.get("所在区域") or "").strip()
            if area not in roadways:
                return None, (
                    f"测点所在区域「{area}」对不上通风系统巷道台账，"
                    "超限报警无法回写受影响清单，请先核对区域"
                )
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != TERMINAL_STATUS
        entry["abnormal"] = target in ABNORMAL_STATUSES
        log.append({"action": action, "from": status, "to": target, "at": _now()})
        if target == ALARM_STATUS:
            alarm = store.append_alarm({
                "测点编号": entry.get("测点编号"),
                "所在区域": entry.get("所在区域"),
                "结论": (conclusion or "").strip()
                or f"测点{entry.get('测点编号')}瓦斯浓度{entry.get('瓦斯浓度')}超限，需联动通风系统处置",
                "报警时间": _now(),
            })
            entry["latest_alarm_id"] = alarm["id"]
            return self._attach(entry), f"瓦斯测点已{action}，结论已回写通风台账受影响清单"
        return self._attach(entry), f"瓦斯测点已{action}"

    def list_alarms(self) -> list[dict[str, Any]]:
        """超限报警台账：与通风台账受影响清单读的是同一份数据。"""
        return store.alarms()

    def _attach(self, row: dict[str, Any]) -> dict[str, Any]:
        """补出页面要用的可执行动作；返回副本，不动台账里的原始记录。"""
        data = dict(row)
        expected = NEXT_ACTION.get(str(row.get("status") or ""))
        data["available_actions"] = [expected] if expected else []
        return data
