<template>
  <section class="page" data-module="gas">
    <header class="page-head">
      <div>
        <h2>瓦斯监测管理</h2>
        <p class="page-desc">维护瓦斯测点，状态按 正常→浓度偏高→超限报警→已处置 逐级流转，超限结论自动回写通风台账受影响清单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记瓦斯测点</button>
        <button class="btn" type="button" @click="exportRows">导出瓦斯监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>测点编号</span>
        <input v-model="keyword" placeholder="按测点编号检索" />
      </label>
      <label class="filter-item">
        <span>测点状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="submitting"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length" class="action-done">
              {{ row.status === '已处置' ? '已办结' : '—' }}
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无瓦斯监测数据，可先登记瓦斯测点</td>
        </tr>
      </tbody>
    </table>

    <section class="alarm-panel">
      <h3 class="alarm-title">超限报警台账（与通风台账受影响清单同源）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in alarmColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="alarm in alarms" :key="String(alarm.id)">
            <td v-for="column in alarmColumns" :key="column">{{ alarm[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!alarms.length">
            <td :colspan="alarmColumns.length" class="empty-state">暂无超限报警记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条瓦斯监测记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null> & { id?: number }

const ENDPOINT = '/api/gas'
const columns = ["测点编号", "所在区域", "瓦斯浓度", "一氧化碳浓度", "温度", "风速", "监测时刻", "测点状态"]
const statuses = ["正常", "浓度偏高", "超限报警", "已处置"]
const alarmColumns = ["测点编号", "所在区域", "结论", "报警时间"]
const stats = [{"label": "正常测点", "value": 0}, {"label": "偏高测点", "value": 0}, {"label": "超限测点", "value": 0}]

const rows = ref<Row[]>([])
const alarms = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const submitting = ref(false)
const keyword = ref('')
const statusFilter = ref('')

function rowActions(row: Row): string[] {
  const actions = row.available_actions
  return Array.isArray(actions) ? (actions as string[]) : []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '瓦斯测点登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (submitting.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '超限报警') {
    const input = window.prompt('请输入超限报警结论（留空则使用默认结论）', '')
    if (input === null) return
    if (input.trim()) values['结论'] = input.trim()
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? payload?.detail ?? '瓦斯监测动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? '操作已生效'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '瓦斯监测操作失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const [listResponse, alarmResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/alarms`),
    ])
    if (!listResponse.ok) {
      throw new Error('瓦斯测点列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (alarmResponse.ok) {
      const alarmPayload = await alarmResponse.json()
      alarms.value = alarmPayload.items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '瓦斯监测列表读取失败'
  }
}

onMounted(reload)
</script>
