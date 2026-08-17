<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card">
      <div class="budget-row">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budget') }}</label>
        <input
          id="budget-slider"
          class="budget-slider"
          type="range"
          min="0"
          max="12000"
          step="250"
          v-model.number="budget"
          @input="onBudgetInput"
        >
        <span class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
      </div>
    </div>

    <div v-if="successMessage" class="success-banner">
      <span>{{ successMessage }}</span>
      <button class="dismiss-btn" type="button" @click="successMessage = null">&times;</button>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ totalCost.toLocaleString() }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.itemsToRestock') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendationsTitle') }}</h3>
          <button
            class="place-order-btn"
            type="button"
            :disabled="items.length === 0 || submitting || refreshPending || loading"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <!-- No table when there are no recommended items within budget -->
        <div v-if="items.length === 0" class="no-recommendations">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.warehouse') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.demandGap') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ translateProductName(item.name) }}</td>
                <td>{{ translateWarehouse(item.warehouse) }}</td>
                <td>
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
                <td>{{ item.demand_gap }}</td>
                <td><strong>{{ item.recommended_quantity }}</strong></td>
                <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                <td>{{ currencySymbol }}{{ item.line_cost.toLocaleString() }}</td>
                <td>{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName, translateWarehouse } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const DEFAULT_BUDGET = 5000
    const budget = ref(DEFAULT_BUDGET)
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)
    // True whenever a slider change has a debounced/in-flight refresh that hasn't
    // resolved yet, so the Place Order button can't submit a stale recommendation set.
    const refreshPending = ref(false)

    const items = ref([])
    const totalCost = ref(0)
    const remainingBudget = ref(0)

    let debounceTimer = null
    // Monotonically increasing request id. Only the response matching the latest
    // request is allowed to write to refs, so a slow older fetch can't clobber a newer one.
    let requestSeq = 0

    const loadRecommendations = async () => {
      const seq = ++requestSeq
      try {
        loading.value = true
        error.value = null
        const data = await api.getRestockingRecommendations(budget.value)
        if (seq !== requestSeq) return
        items.value = data.items
        totalCost.value = data.total_cost
        remainingBudget.value = data.remaining_budget
      } catch (err) {
        if (seq !== requestSeq) return
        error.value = 'Failed to load restocking recommendations: ' + err.message
      } finally {
        if (seq === requestSeq) {
          loading.value = false
          // Only the latest request clears the pending flag; an older, already-superseded
          // request must not mark the (newer) in-flight refresh as done.
          refreshPending.value = false
        }
      }
    }

    const onBudgetInput = () => {
      // Debounce API calls while the user drags the slider to avoid flooding the backend
      refreshPending.value = true
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        loadRecommendations()
      }, 300)
    }

    const placeOrder = async () => {
      submitting.value = true
      error.value = null
      try {
        const orderItems = items.value.map(item => ({ sku: item.sku, quantity: item.recommended_quantity }))
        const created = await api.createRestockingOrder(orderItems)
        successMessage.value = t('restocking.orderPlaced', {
          orders: created.map(order => order.order_number).join(', ')
        })
        await loadRecommendations()
      } catch (err) {
        error.value = 'Failed to place restocking order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)
    // Prevent a pending debounce from firing after the component is gone.
    onUnmounted(() => clearTimeout(debounceTimer))

    return {
      t,
      currencySymbol,
      translateProductName,
      translateWarehouse,
      budget,
      loading,
      error,
      submitting,
      refreshPending,
      successMessage,
      items,
      totalCost,
      remainingBudget,
      onBudgetInput,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-row {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.budget-value {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 90px;
  text-align: right;
  flex-shrink: 0;
}

.budget-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
}

.place-order-btn {
  padding: 0.5rem 1.25rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.no-recommendations {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.success-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 0.875rem 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.dismiss-btn {
  background: none;
  border: none;
  color: #065f46;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
}
</style>
