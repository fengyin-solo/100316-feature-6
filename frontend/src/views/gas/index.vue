<template>
  <section class="page" data-module="gas">
    <header class="page-head">
      <div>
        <h2>瓦斯监测管理</h2>
        <p class="page-desc">测点状态按 正常 → 浓度偏高 → 超限报警 → 已处置 顺序流转，不可跳级、不可回退；超限报警自动回写通风台账受影响清单。</p>
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
        <input v-model="filters.keyword" placeholder="按测点编号检索" />
      </label>
      <label class="filter-item">
        <span>测点状态</span>
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
          <th>下一步处置</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="nextAction(String(row.status))"
              class="link"
              type="button"
              :disabled="busyId === row.id"
              @click="runAction(String(nextAction(String(row.status))), row)"
            >
              {{ nextAction(String(row.status)) }}
            </button>
            <span v-else-if="row.status === '已处置'" class="muted-text">流程已闭环</span>
            <span v-else class="muted-text">历史人工判定记录</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无瓦斯监测数据，可先登记瓦斯测点</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条瓦斯监测记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记瓦斯测点</h3>
        <p class="modal-tip">所在区域必须与通风系统在册巷道一致，否则不予登记。</p>
        <label class="form-item">
          <span>测点编号</span>
          <input v-model="form.测点编号" placeholder="如 GAS-0010" required />
        </label>
        <label class="form-item">
          <span>所在区域（巷道）</span>
          <select v-model="form.所在区域" required>
            <option value="" disabled>请选择通风巷道</option>
            <option v-for="name in roadways" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label class="form-item">
          <span>瓦斯浓度</span>
          <input v-model="form.瓦斯浓度" placeholder="如 0.62%" required />
        </label>
        <label class="form-item">
          <span>一氧化碳浓度</span>
          <input v-model="form.一氧化碳浓度" placeholder="如 8ppm" />
        </label>
        <label class="form-item">
          <span>温度</span>
          <input v-model="form.温度" placeholder="如 22.0℃" />
        </label>
        <label class="form-item">
          <span>风速</span>
          <input v-model="form.风速" placeholder="如 2.5m/s" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="submit">提交登记</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/gas'
const columns = ['测点编号', '所在区域', '瓦斯浓度', '一氧化碳浓度', '温度', '风速', '监测时刻', '测点状态']
const statuses = ['正常', '浓度偏高', '超限报警', '已处置']
// 每个状态下唯一允许的下一步动作；已处置无下一步
const nextActions: Record<string, string> = {
  正常: '偏高预警',
  浓度偏高: '超限报警',
  超限报警: '处置确认',
  已处置: '',
}
const statsDefinition = [
  { label: '正常测点', status: '正常' },
  { label: '偏高测点', status: '浓度偏高' },
  { label: '超限测点', status: '超限报警' },
  { label: '已处置', status: '已处置' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref(statsDefinition.map((item) => ({ label: item.label, value: 0 })))
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const busyId = ref<number | string | null>(null)

const creating = ref(false)
const roadways = ref<string[]>([])
const form = reactive<Record<string, string>>({
  测点编号: '',
  所在区域: '',
  瓦斯浓度: '',
  一氧化碳浓度: '',
  温度: '',
  风速: '',
})

function nextAction(status: string): string {
  return nextActions[status] ?? ''
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openCreate() {
  errorMessage.value = ''
  try {
    const response = await request('/api/ventilation/roadways')
    const payload = await response.json()
    roadways.value = (payload.items ?? []) as string[]
  } catch {
    roadways.value = []
  }
  creating.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const values: Record<string, string> = {}
    for (const [key, value] of Object.entries(form)) {
      if (value.trim()) values[key] = value.trim()
    }
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message ?? '瓦斯测点登记失败'
      return
    }
    creating.value = false
    for (const key of Object.keys(form)) form[key] = ''
    noticeMessage.value = payload.message ?? '瓦斯测点已登记'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '瓦斯测点登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  busyId.value = row.id as number
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    // 后端业务校验失败时 HTTP 仍是 200，拒绝原因在 body.message，必须读出来
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message ?? '瓦斯监测动作未生效'
      return
    }
    noticeMessage.value = payload.message ?? '状态已更新'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '瓦斯监测操作失败'
  } finally {
    busyId.value = null
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const [listResponse, exportResponse] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}/export`),
    ])
    if (!listResponse.ok) throw new Error('瓦斯测点列表读取失败')
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length

    // 统计取全量口径，避免只统计当前分页
    if (exportResponse.ok) {
      const all = await exportResponse.json()
      const allRows = (all.items ?? []) as Row[]
      stats.value = statsDefinition.map((item) => ({
        label: item.label,
        value: allRows.filter((row) => row.status === item.status).length,
      }))
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '瓦斯监测列表读取失败'
  }
}

onMounted(reload)
</script>
