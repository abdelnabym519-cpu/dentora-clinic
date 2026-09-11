<script setup lang="ts">
// Global banner shown across the admin layout when at least one
// Verifactu record is rejected. Polls /verifactu/health every 60 s
// (cheap query) so the user sees the warning even on screens that
// don't otherwise touch verifactu data.
//
// ISOLATION CONTRACT — this component mounts on *every* screen of the
// default layout (patients, agenda, AI cards, settings), so its probe
// must never be able to speak for the page the user is looking at:
//
//   1. It only probes when the user holds the permission the endpoint
//      actually requires. ``GET /verifactu/health`` is a settings-scope
//      read (``verifactu.settings.read``); gating on queue/records
//      grants instead sent dentists and receptionists straight into a
//      403 they could do nothing about.
//   2. The probe is ``silent``: a denial stays inside this component and
//      never becomes a global "Access denied" toast.
//   3. A denial (or a clinic without the module) stops the polling
//      instead of re-firing every 60 s for the rest of the session.
//
// Nothing here weakens Verifactu authorization: the Verifactu screens
// keep reporting a genuine denial for the action the user performed.
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorStatus } from '~~/app/utils/error'

const { t } = useI18n()
const { health } = useVerifactu()
const { can } = usePermissions()

const rejectedCount = ref(0)
const showing = computed(() => rejectedCount.value > 0)
let timer: ReturnType<typeof setInterval> | null = null

// Set once the backend tells us this probe is pointless for this user
// (no grant) or this clinic (module not installed).
const disabled = ref(false)

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function refresh() {
  if (disabled.value) return
  if (!can(PERMISSIONS.verifactu.settingsRead)) {
    disabled.value = true
    stopPolling()
    return
  }
  try {
    const h = await health({ silent: true })
    rejectedCount.value = h.rejected_count ?? 0
  } catch (error: unknown) {
    // Silent — module may not be installed for this clinic, or the grant
    // may have been revoked mid-session. Neither is an error on the
    // screen the user is currently working in.
    rejectedCount.value = 0
    const status = errorStatus(error)
    if (status === 403 || status === 404) {
      disabled.value = true
      stopPolling()
    }
  }
}

onMounted(() => {
  void refresh()
  if (!disabled.value) {
    timer = setInterval(refresh, 60_000)
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <UAlert
    v-if="showing"
    color="error"
    variant="soft"
    icon="i-lucide-alert-octagon"
    :title="t('verifactu.globalBanner.title', { n: rejectedCount })"
    class="mb-4"
  >
    <template #description>
      <p class="mb-2">
        {{ t('verifactu.globalBanner.description') }}
      </p>
      <UButton
        to="/settings/verifactu/queue"
        color="primary"
        size="sm"
      >
        {{ t('verifactu.globalBanner.cta') }}
      </UButton>
    </template>
  </UAlert>
</template>
