<script setup lang="ts">
const { t } = useI18n()
const { settings, loading, saving, error, fetch, update } = useCommunicationsSettings()

const language = ref<'es' | 'en' | 'fr' | 'pt'>('es')

const SUPPORTED = ['en', 'fr', 'pt'] as const

watch(settings, (s) => {
  if (s) language.value = (SUPPORTED.includes(s.language as typeof SUPPORTED[number]) ? s.language as typeof language.value : 'es')
})

onMounted(fetch)

const options = [
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
  { value: 'pt', label: 'Português' }
]

async function save() {
  await update({ language: language.value })
}
</script>

<template>
  <!-- A failed load is not "the clinic speaks Spanish": the picker would be
       showing a default nobody chose, one click away from being saved. -->
  <div
    v-if="error"
    class="space-y-3"
    data-testid="clinic-language-load-error"
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
      <div>
        <p class="font-medium">
          {{ t('notifications.communications.language.title') }}
        </p>
        <p class="text-xs text-[var(--ui-text-muted)] mt-1 max-w-xl">
          {{ t('notifications.communications.language.help') }}
        </p>
      </div>
      <UFormField :label="t('notifications.communications.language.label')">
        <USelect
          v-model="language"
          :items="options"
          class="w-full max-w-xs"
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
          {{ t('notifications.communications.language.save') }}
        </UButton>
      </div>
    </template>
  </UCard>
</template>
