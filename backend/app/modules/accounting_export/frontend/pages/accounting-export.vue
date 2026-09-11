<script setup lang="ts">
import { computed, ref } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorMessage } from '~~/app/utils/error'
import { useAccountingExport, type ExportPreview } from '../composables/useAccountingExport'

definePageMeta({ middleware: ['auth'] })

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const exportApi = useAccountingExport()

if (!can(PERMISSIONS.accountingExport.read)) {
  await navigateTo('/')
}

// --- Date presets (computed client-side; backend only takes concrete dates) ---
function iso(d: Date): string {
  return d.toISOString().slice(0, 10)
}
type Preset = { key: string, range: () => { from: string, to: string } }
const now = new Date()
const y = now.getFullYear()
const m = now.getMonth()
const q = Math.floor(m / 3)
const presets: Preset[] = [
  { key: 'currentMonth', range: () => ({ from: iso(new Date(y, m, 1)), to: iso(new Date(y, m + 1, 0)) }) },
  { key: 'previousMonth', range: () => ({ from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0)) }) },
  { key: 'currentQuarter', range: () => ({ from: iso(new Date(y, q * 3, 1)), to: iso(new Date(y, q * 3 + 3, 0)) }) },
  { key: 'previousQuarter', range: () => ({ from: iso(new Date(y, q * 3 - 3, 1)), to: iso(new Date(y, q * 3, 0)) }) },
  { key: 'yearToDate', range: () => ({ from: iso(new Date(y, 0, 1)), to: iso(now) }) },
  { key: 'custom', range: () => ({ from: dateFrom.value, to: dateTo.value }) }
]
const presetOptions = computed(() =>
  presets.map(p => ({ value: p.key, label: t(`accountingExport.presets.${p.key}`) }))
)

const selectedPreset = ref('previousMonth')
const dateFrom = ref('')
const dateTo = ref('')

const range = computed(() => {
  const p = presets.find(x => x.key === selectedPreset.value)!
  return p.range()
})
const isCustom = computed(() => selectedPreset.value === 'custom')

const preview = ref<ExportPreview | null>(null)
const previewError = ref<string | null>(null)
const loadingPreview = ref(false)
const downloading = ref(false)

function filters() {
  return { date_from: range.value.from || undefined, date_to: range.value.to || undefined }
}

async function runPreview() {
  loadingPreview.value = true
  previewError.value = null
  try {
    preview.value = (await exportApi.preview(filters())).data
  } catch (e) {
    // Was try/finally with no catch: the rejection escaped the click handler
    // and, for the statuses the shared layer never toasts (422 on a bad
    // range, 404), the button simply appeared to do nothing.
    preview.value = null
    previewError.value = errorMessage(e, t('accountingExport.errors.previewFailed'))
  } finally {
    loadingPreview.value = false
  }
}

async function download() {
  downloading.value = true
  try {
    await exportApi.download(filters())
  } catch (e) {
    // This one bypasses useApi entirely (authenticated blob download), so no
    // shared report exists: without this catch a failed export was silent.
    toast.add({
      title: t('common.error'),
      description: errorMessage(e, t('accountingExport.errors.downloadFailed')),
      color: 'error'
    })
  } finally {
    downloading.value = false
  }
}

const invoiceCols = ['numero', 'fecha_emision', 'cliente', 'nif', 'base', 'cuota_iva', 'total', 'estado']
</script>

<template>
  <div class="container mx-auto p-4 space-y-4 max-w-4xl">
    <h1 class="text-h1">
      {{ t('accountingExport.title') }}
    </h1>
    <p class="text-subtle text-sm">
      {{ t('accountingExport.subtitle') }}
    </p>

    <UCard>
      <div class="flex flex-col sm:flex-row sm:items-end gap-3 flex-wrap">
        <UFormField
          :label="t('accountingExport.period')"
          class="w-full sm:w-auto"
        >
          <USelect
            v-model="selectedPreset"
            :items="presetOptions"
            class="w-full sm:w-56"
          />
        </UFormField>
        <template v-if="isCustom">
          <UFormField
            :label="t('accountingExport.from')"
            class="w-full sm:w-auto"
          >
            <input
              v-model="dateFrom"
              type="date"
              class="w-full sm:w-auto border rounded px-2 py-1.5"
            >
          </UFormField>
          <UFormField
            :label="t('accountingExport.to')"
            class="w-full sm:w-auto"
          >
            <input
              v-model="dateTo"
              type="date"
              class="w-full sm:w-auto border rounded px-2 py-1.5"
            >
          </UFormField>
        </template>
        <div class="flex gap-2 w-full sm:w-auto sm:ml-auto">
          <UButton
            icon="i-lucide-eye"
            variant="soft"
            block
            class="sm:w-auto"
            :loading="loadingPreview"
            @click="runPreview"
          >
            {{ t('accountingExport.actions.preview') }}
          </UButton>
          <UButton
            icon="i-lucide-download"
            block
            class="sm:w-auto"
            :loading="downloading"
            :disabled="!preview"
            @click="download"
          >
            {{ t('accountingExport.actions.download') }}
          </UButton>
        </div>
      </div>

      <!-- A preview that failed is not "this period has no invoices". -->
      <UAlert
        v-if="previewError"
        color="error"
        variant="soft"
        icon="i-lucide-alert-triangle"
        class="mt-4"
        :title="t('accountingExport.errors.previewFailed')"
        :description="previewError"
        data-testid="accounting-export-preview-error"
      />
    </UCard>

    <section
      v-if="preview"
      class="space-y-4"
    >
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
        <UCard :ui="{ body: 'p-2' }">
          <div class="text-h2 tnum">
            {{ preview.invoice_count }}
          </div>
          <div class="text-caption text-subtle">
            {{ t('accountingExport.counters.invoices') }}
          </div>
        </UCard>
        <UCard :ui="{ body: 'p-2' }">
          <div class="text-h2 tnum">
            {{ preview.payment_count }}
          </div>
          <div class="text-caption text-subtle">
            {{ t('accountingExport.counters.payments') }}
          </div>
        </UCard>
        <UCard :ui="{ body: 'p-2' }">
          <div class="text-h2 tnum">
            {{ preview.total_base }}
          </div>
          <div class="text-caption text-subtle">
            {{ t('accountingExport.counters.base') }}
          </div>
        </UCard>
        <UCard :ui="{ body: 'p-2' }">
          <div class="text-h2 tnum">
            {{ preview.total }}
          </div>
          <div class="text-caption text-subtle">
            {{ t('accountingExport.counters.total') }}
          </div>
        </UCard>
      </div>

      <UCard
        v-if="preview.sample_invoices.length"
        :ui="{ body: 'p-0 overflow-x-auto' }"
      >
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-subtle">
              <th
                v-for="c in invoiceCols"
                :key="c"
                class="px-2 py-1 whitespace-nowrap"
              >
                {{ t(`accountingExport.cols.${c}`) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in preview.sample_invoices"
              :key="i"
              class="border-t"
            >
              <td
                v-for="c in invoiceCols"
                :key="c"
                class="px-2 py-1 whitespace-nowrap"
              >
                {{ row[c] }}
              </td>
            </tr>
          </tbody>
        </table>
      </UCard>
    </section>
  </div>
</template>
