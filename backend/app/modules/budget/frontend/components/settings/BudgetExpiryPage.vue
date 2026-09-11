<script setup lang="ts">
const { t } = useI18n()
const { settings, loading, saving, error, fetch, update } = useBudgetSettings()

const validityDays = ref(30)
const autoCloseDays = ref(30)

watch(
  settings,
  (s) => {
    if (s) {
      validityDays.value = s.budget_expiry_days
      autoCloseDays.value = s.plan_auto_close_days_after_expiry
    }
  }
)

onMounted(fetch)

async function save() {
  await update({
    budget_expiry_days: validityDays.value,
    plan_auto_close_days_after_expiry: autoCloseDays.value
  })
}
</script>

<template>
  <!-- A failed load is not "this setting is off": rendering the form from
       defaults would invite the user to save a value that was never the
       clinic's. -->
  <div
    v-if="error"
    class="space-y-3"
    data-testid="budget-expiry-load-error"
  >
    <UAlert
      color="error"
      variant="soft"
      icon="i-lucide-alert-triangle"
      :title="t('errors.loadFailed')"
      :description="error"
    />
    <UButton
      variant="ghost"
      size="sm"
      icon="i-lucide-refresh-cw"
      @click="fetch()"
    >
      {{ t('common.retry') }}
    </UButton>
  </div>
  <UCard v-else-if="!loading">
    <div class="space-y-4">
      <UFormField
        :label="t('budget.settings.expiry.validityDays')"
        :hint="t('budget.settings.expiry.validityHelp')"
      >
        <UInput
          v-model.number="validityDays"
          type="number"
          :min="7"
          :max="180"
        />
      </UFormField>
      <UFormField
        :label="t('budget.settings.expiry.autoCloseDays')"
        :hint="t('budget.settings.expiry.autoCloseHelp')"
      >
        <UInput
          v-model.number="autoCloseDays"
          type="number"
          :min="7"
          :max="180"
        />
      </UFormField>
    </div>
    <template #footer>
      <div class="flex justify-end">
        <UButton
          color="primary"
          :loading="saving"
          @click="save"
        >
          {{ t('budget.settings.expiry.save') }}
        </UButton>
      </div>
    </template>
  </UCard>
</template>
