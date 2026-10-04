<template>
  <section class="page" data-module="ventilation">
    <header class="page-head">
      <div>
        <h2>通风系统管理</h2>
        <p class="page-desc">维护通风设备，围绕设备编号、设备类型、额定风量、运行频率做登记、筛选与状态流转；巷道受瓦斯超限影响的报警自动登记到下方清单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记通风设备</button>
        <button class="btn" type="button" @click="exportRows">导出通风系统清单</button>
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
        <span>设备编号</span>
        <input v-model="filters.keyword" placeholder="按设备编号检索" />
      </label>
      <label class="filter-item">
        <span>设备状态</span>
        <select v-model="filters.status">
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无通风系统数据，可先登记通风设备</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">瓦斯超限受影响清单（与瓦斯监测同源）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in alarmColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(alarm, index) in alarms" :key="`${alarm.gas_id}-${index}`">
          <td v-for="column in alarmColumns" :key="column">{{ alarm[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!alarms.length">
          <td :colspan="alarmColumns.length" class="empty-state">暂无受瓦斯超限影响的巷道设备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条通风系统记录，{{ alarms.length }} 条超限受影响记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/ventilation'
const columns = ['设备编号', '设备类型', '额定风量', '运行频率', '电流值', '所属巷道', '上次检修', '设备状态']
const actions = ['降频运行', '故障停机', '办理更换']
const statuses = ['正常', '降频运行', '故障停机', '已更换']
const stats = [{ label: '正常设备', value: 0 }, { label: '降频设备', value: 0 }, { label: '故障设备', value: 0 }]
const alarmColumns = ['设备编号', '所属巷道', '测点编号', '瓦斯浓度', '回写结论', '回写时刻', '测点当前状态']

const rows = ref<Row[]>([])
const alarms = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '通风设备登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '通风系统动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '通风系统操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const [listResponse, alarmResponse] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}/affected-alarms`),
    ])
    if (!listResponse.ok) {
      throw new Error('通风设备列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length

    if (alarmResponse.ok) {
      const alarmPayload = await alarmResponse.json()
      alarms.value = alarmPayload.items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '通风系统列表读取失败'
  }
}

onMounted(reload)
</script>
