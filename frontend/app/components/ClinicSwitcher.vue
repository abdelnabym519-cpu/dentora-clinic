<script setup lang="ts">
/**
 * Multi-clinic switcher.
 *
 * Reads the user's clinic memberships from `/auth/me` (already fetched by
 * useAuth on boot) and lets a member of several clinics switch the
 * active one. Switching calls `auth.switchClinic`, which mints a new
 * token bound to the chosen clinic and reloads the clinic context — all
 * subsequent API calls carry X-Clinic-Id automatically via useApi.
 *
 * Hidden entirely for single-clinic / self-hosted installs.
 */
const { t } = useI18n()
const auth = useAuth()
const clinic = useClinic()
const selected = useSelectedClinicId()
const toast = useToast()

const options = computed(() => auth.clinics.value ?? [])

const multiple = computed(() => options.value.length > 1)

const currentName = computed(() =>
  options.value.find(c => c.id === selected.value)?.name
  ?? clinic.clinicName.value
  ?? ''
)

const switcherOpen = ref(false)

async function choose(id: string) {
  switcherOpen.value = false
  if (id === selected.value) return
  const ok = await auth.switchClinic(id)
  if (ok) {
    await clinic.fetchClinic()
    toast.add({
      title: t('common.success'),
      description: t('auth.clinicSwitched', 'Clínica cambiada'),
      color: 'success'
    })
    if (import.meta.client) {
      // Reload so every module re-queries with the new clinic scope.
      window.location.reload()
    }
  } else {
    toast.add({
      title: t('common.error'),
      description: t('auth.clinicSwitchFailed', 'No se pudo cambiar de clínica'),
      color: 'error'
    })
  }
}
</script>

<template>
  <ClientOnly>
    <div
      v-if="multiple"
      class="relative"
    >
      <button
        type="button"
        class="flex items-center gap-2 min-w-0 rounded-lg px-2 py-1.5 text-sm text-ui hover:bg-elevated transition-colors"
        :title="currentName"
        @click="switcherOpen = !switcherOpen"
      >
        <UIcon
          name="i-lucide-building-2"
          class="w-4 h-4 text-subtle shrink-0"
        />
        <span class="truncate max-w-[8rem] sm:max-w-[12rem]">{{ currentName }}</span>
        <UIcon
          name="i-lucide-chevrons-up-down"
          class="w-3.5 h-3.5 text-subtle shrink-0"
        />
      </button>

      <div
        v-if="switcherOpen"
        class="absolute right-0 top-full mt-1 z-50 min-w-[14rem] rounded-xl border border-default bg-surface shadow-xl overflow-hidden"
      >
        <button
          v-for="c in options"
          :key="c.id"
          type="button"
          class="w-full text-left px-3 py-2 text-sm hover:bg-elevated flex items-center justify-between gap-2"
          :class="c.id === selected ? 'text-accent font-medium' : 'text-ui'"
          @click="choose(c.id)"
        >
          <span class="truncate">{{ c.name }}</span>
          <span class="text-xs text-subtle uppercase">{{ c.role }}</span>
        </button>
      </div>
    </div>
  </ClientOnly>
</template>
