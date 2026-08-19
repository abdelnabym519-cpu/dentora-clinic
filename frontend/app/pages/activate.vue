<script setup lang="ts">
definePageMeta({ layout: 'guest' })

const config = useRuntimeConfig()
const { locale } = useI18n()

interface LicenseStatus {
  enforced: boolean
  installation_id: string
  active: boolean
  state: string
  reason?: string | null
}

const licenseKey = ref('')
const statusData = ref<LicenseStatus | null>(null)
const loading = ref(false)
const activating = ref(false)
const errorMessage = ref('')

const ar = computed(() => locale.value === 'ar')
const text = computed(() => ar.value
  ? {
      title: 'تفعيل DentalPin',
      subtitle: 'أدخل مفتاح الترخيص الخاص بالعيادة قبل إنشاء حساب المسؤول.',
      key: 'مفتاح الترخيص',
      placeholder: 'DP-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX',
      activate: 'تفعيل النظام',
      activating: 'جاري التفعيل...',
      installation: 'معرّف التثبيت',
      help: 'إذا لم يكن لديك مفتاح ترخيص، تواصل مع مزود DentalPin.',
      loadError: 'تعذر الاتصال بخدمة DentalPin المحلية.',
      required: 'أدخل مفتاح الترخيص أولًا.',
      failed: 'تعذر تفعيل مفتاح الترخيص.'
    }
  : {
      title: 'Activate DentalPin',
      subtitle: 'Enter this clinic\'s license key before creating the administrator account.',
      key: 'License key',
      placeholder: 'DP-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX',
      activate: 'Activate system',
      activating: 'Activating...',
      installation: 'Installation ID',
      help: 'If you do not have a license key, contact your DentalPin provider.',
      loadError: 'Could not reach the local DentalPin service.',
      required: 'Enter the license key first.',
      failed: 'Could not activate this license key.'
    })

const baseURL = computed(() => import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl)

async function loadStatus() {
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await $fetch<{ data: LicenseStatus }>('/api/v1/license/status', { baseURL: baseURL.value })
    statusData.value = res.data
    if (!res.data.enforced || res.data.active) await navigateTo('/')
  } catch {
    errorMessage.value = text.value.loadError
  } finally {
    loading.value = false
  }
}

async function activate() {
  const key = licenseKey.value.trim().toUpperCase()
  if (!key) {
    errorMessage.value = text.value.required
    return
  }
  activating.value = true
  errorMessage.value = ''
  try {
    const res = await $fetch<{ data: LicenseStatus }>('/api/v1/license/activate', {
      baseURL: baseURL.value,
      method: 'POST',
      body: { license_key: key }
    })
    statusData.value = res.data
    if (res.data.active) await navigateTo('/')
  } catch (error: unknown) {
    const apiError = error as { data?: { message?: string, detail?: string, errors?: string[] } }
    errorMessage.value = apiError.data?.message || apiError.data?.detail || apiError.data?.errors?.[0] || text.value.failed
  } finally {
    activating.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <div class="w-full max-w-[480px] p-6">
    <div class="text-center mb-6">
      <img
        src="/logo-icon.svg"
        alt="DentalPin"
        width="64"
        height="64"
        class="mx-auto mb-3"
      >
      <h1 class="text-h1 text-default">
        {{ text.title }}
      </h1>
      <p class="text-caption text-muted mt-1">
        {{ text.subtitle }}
      </p>
    </div>

    <UCard>
      <div
        v-if="errorMessage"
        class="alert-surface-danger rounded-token-md px-3 py-2 mb-4"
        role="alert"
      >
        {{ errorMessage }}
      </div>

      <div
        v-if="loading"
        class="py-8 text-center text-muted"
      >
        <UIcon
          name="i-lucide-loader-circle"
          class="w-6 h-6 animate-spin mx-auto"
        />
      </div>

      <form
        v-else
        class="space-y-4"
        @submit.prevent="activate"
      >
        <UFormField :label="text.key">
          <UInput
            v-model="licenseKey"
            class="w-full"
            :placeholder="text.placeholder"
            autocomplete="off"
            spellcheck="false"
            :disabled="activating"
          />
        </UFormField>

        <div
          v-if="statusData?.installation_id"
          class="rounded-token-md bg-muted px-3 py-2"
        >
          <div class="text-caption text-muted">
            {{ text.installation }}
          </div>
          <code class="text-xs break-all select-all">{{ statusData.installation_id }}</code>
        </div>

        <p class="text-caption text-muted">
          {{ text.help }}
        </p>

        <UButton
          type="submit"
          block
          :loading="activating"
          :disabled="activating"
        >
          {{ activating ? text.activating : text.activate }}
        </UButton>
      </form>
    </UCard>
  </div>
</template>
