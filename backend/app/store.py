"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 超限报警台账：瓦斯侧写入、通风侧读取，两边同源，不算独立业务模块
        self._alarms: list[dict[str, Any]] = []

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def append_alarm(self, record: dict[str, Any]) -> dict[str, Any]:
        """写入一条超限报警，返回带 id 的台账记录。"""
        alarm = dict(record)
        alarm["id"] = len(self._alarms) + 1
        self._alarms.append(alarm)
        return dict(alarm)

    def alarms(self, *, area: str | None = None, point: str | None = None) -> list[dict[str, Any]]:
        """按区域或测点编号读取报警台账；不传条件时返回全部，新的在前。"""
        records = self._alarms
        if area is not None:
            records = [a for a in records if a.get("所在区域") == area]
        if point is not None:
            records = [a for a in records if a.get("测点编号") == point]
        return [dict(a) for a in reversed(records)]

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
