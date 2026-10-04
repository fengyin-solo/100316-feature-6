"""瓦斯测点状态流转的端到端规则测试。

覆盖：逐级流转不许跳级、已处置原样退回、重复提交只生效一次、
区域与通风巷道一致性、超限结论回写通风台账并同源、历史跳级记录保留。
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_store():
    """每个用例跑完都把内存台账还原，互不影响。"""
    tables = copy.deepcopy(store._tables)
    alarms = copy.deepcopy(store._alarms)
    yield
    store._tables = tables
    store._alarms = alarms


def create_point(area: str = "一采区运输巷", code: str = "GAS-9001") -> dict:
    response = client.post("/api/gas", json={"values": {
        "测点编号": code, "所在区域": area, "瓦斯浓度": "0.6%",
    }})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"], payload["message"]
    return payload["entry"]


def run_action(entry_id: int, action: str, conclusion: str | None = None) -> dict:
    values = {"action": action}
    if conclusion is not None:
        values["结论"] = conclusion
    response = client.post(f"/api/gas/{entry_id}/actions", json={"values": values})
    assert response.status_code == 200
    return response.json()


def test_full_chain_flows_in_order():
    entry = create_point()
    assert entry["status"] == "正常"
    assert entry["available_actions"] == ["偏高预警"]

    step1 = run_action(entry["id"], "偏高预警")
    assert step1["ok"] and step1["entry"]["status"] == "浓度偏高"
    assert step1["entry"]["available_actions"] == ["超限报警"]

    step2 = run_action(entry["id"], "超限报警", conclusion="瓦斯超限，停电撤人")
    assert step2["ok"] and step2["entry"]["status"] == "超限报警"
    assert step2["entry"]["available_actions"] == ["处置确认"]

    step3 = run_action(entry["id"], "处置确认")
    assert step3["ok"] and step3["entry"]["status"] == "已处置"
    assert step3["entry"]["available_actions"] == []
    assert step3["entry"]["pending"] is False


def test_skip_level_is_blocked():
    entry = create_point()
    result = run_action(entry["id"], "超限报警")
    assert not result["ok"]
    assert "逐级流转" in result["message"]
    result = run_action(entry["id"], "处置确认")
    assert not result["ok"]
    # 状态没被改动
    detail = client.get(f"/api/gas/{entry['id']}").json()
    assert detail["status"] == "正常"


def test_handled_point_rejects_new_action():
    entry = create_point()
    run_action(entry["id"], "偏高预警")
    run_action(entry["id"], "超限报警")
    run_action(entry["id"], "处置确认")
    result = run_action(entry["id"], "偏高预警")
    assert not result["ok"]
    assert "原样退回" in result["message"]
    detail = client.get(f"/api/gas/{entry['id']}").json()
    assert detail["status"] == "已处置"


def test_duplicate_submission_applies_once():
    entry = create_point()
    first = run_action(entry["id"], "偏高预警")
    assert first["ok"]
    second = run_action(entry["id"], "偏高预警")
    assert second["ok"]
    assert "重复提交" in second["message"]
    assert second["entry"]["status"] == "浓度偏高"
    # 台账里只记了一次流转
    detail = client.get(f"/api/gas/{entry['id']}").json()
    assert [log["action"] for log in detail["action_log"]] == ["偏高预警"]


def test_duplicate_dispose_after_terminal_is_noop():
    entry = create_point()
    run_action(entry["id"], "偏高预警")
    run_action(entry["id"], "超限报警")
    run_action(entry["id"], "处置确认")
    again = run_action(entry["id"], "处置确认")
    assert again["ok"]
    assert "重复提交" in again["message"]
    assert again["entry"]["status"] == "已处置"


def test_area_must_match_ventilation_roadway():
    response = client.post("/api/gas", json={"values": {
        "测点编号": "GAS-9002", "所在区域": "不存在的巷道", "瓦斯浓度": "0.6%",
    }})
    payload = response.json()
    assert not payload["ok"]
    assert "通风系统巷道台账" in payload["message"]


def test_alarm_writes_back_to_ventilation_and_shares_source():
    entry = create_point(area="一采区回风巷", code="GAS-9003")
    run_action(entry["id"], "偏高预警")
    result = run_action(entry["id"], "超限报警", conclusion="回风巷瓦斯超限，需加强通风")
    assert result["ok"]

    alarms = client.get("/api/gas/alarms").json()["items"]
    mine = [a for a in alarms if a["测点编号"] == "GAS-9003"]
    assert len(mine) == 1
    assert mine[0]["结论"] == "回风巷瓦斯超限，需加强通风"

    # 通风台账按巷道读到同一条报警，内容一致（同源）
    vent = client.get("/api/ventilation", params={"keyword": "VENT-0002"}).json()["items"]
    assert len(vent) == 1
    affected = vent[0]["受影响清单"]
    assert len(affected) == 1
    assert "GAS-9003" in affected[0]
    assert "回风巷瓦斯超限，需加强通风" in affected[0]

    # 其它巷道的设备不受影响
    other = client.get("/api/ventilation", params={"keyword": "VENT-0001"}).json()["items"]
    assert other[0]["受影响清单"] == []


def test_alarm_written_only_once_on_repeat():
    entry = create_point(code="GAS-9004")
    run_action(entry["id"], "偏高预警")
    run_action(entry["id"], "超限报警")
    run_action(entry["id"], "超限报警")  # 重复提交不再生效
    alarms = client.get("/api/gas/alarms").json()["items"]
    assert len([a for a in alarms if a["测点编号"] == "GAS-9004"]) == 1


def test_legacy_skipped_record_is_kept_and_can_finish():
    # 种子里的 GAS-0003 历史上直接就是超限报警，按当时人工判定保留
    detail = client.get("/api/gas/3").json()
    assert detail["status"] == "超限报警"
    # 不强行补链，但允许从当前状态走下一步
    result = run_action(3, "处置确认")
    assert result["ok"] and result["entry"]["status"] == "已处置"


def test_alarm_requires_matching_roadway():
    # 历史遗留区域对不上巷道台账时，超限报警被拦下并说明原因
    rows = store.rows("gas")
    rows.append({
        "id": 900, "status": "浓度偏高", "pending": True, "abnormal": True,
        "测点编号": "GAS-9005", "所在区域": "已废弃老巷", "瓦斯浓度": "1.2%",
    })
    result = run_action(900, "超限报警")
    assert not result["ok"]
    assert "巷道台账" in result["message"]
