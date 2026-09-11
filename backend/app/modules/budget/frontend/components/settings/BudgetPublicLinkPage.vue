<script setup lang="ts">
const { t } = useI18n()
const { settings, loading, saving, error, fetch, update } = useBudgetSettings()

const authDisabled = ref(false)

watch(settings, (s) => {
  if (s) authDisabled.value = s.budget_public_auth_disabled
})

onMounted(fetch)

async function save() {
  await update({ budget_public_auth_disabled: authDisabled.value })
}
</script>

<template>
  <!-- A failed load is not "this setting is off": rendering the form from
       defaults would invite the user to save a value that was never the
       clinic's. -->
  <div
    v-if="error"
    class="space-y-3"
    data-testid="budget-public-link-load-error"
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
      <div class="flex items-start justify-between gap-4">
        <div>
          <p class="font-medium">
            {{ t('budget.settings.publicLink.authDisabled') }}
          </p>
          <p class="text-xs text-[var(--ui-text-muted)] mt-1 max-w-xl">
            {{ t('budget.settings.publicLink.authDisabledHelp') }}
          </p>
        </div>
        <USwitch v-model="authDisabled" />
      </div>
      <UAlert
        v-if="authDisabled"
        color="warning"
        variant="soft"
        icon="i-lucide-shield-alert"
        :description="t('budget.settings.publicLink.authDisabledHelp')"
      />
    </div>
    <template #footer>
      <div class="flex justify-end">
        <UButton
          color="primary"
          :loading="saving"
          @click="save"
        >
          {{ t('budget.settings.publicLink.save') }}
        </UButton>
      </div>
    </template>
  </UCard>
</template>
