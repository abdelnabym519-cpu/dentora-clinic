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
const isSwitching = ref(false)

const rootEl = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLButtonElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

/**
 * This menu is hand-rolled rather than a `UDropdownMenu`, so the keyboard and
 * pointer behaviour a menu is expected to have has to be here explicitly:
 * Escape dismisses it, a click anywhere outside dismisses it, the arrow keys
 * walk the clinics, and focus goes back to the trigger on the way out. Without
 * it the panel stayed open over the page content until the trigger was clicked
 * a second time, and there was no way to reach it from the keyboard at all.
 */
function menuItems(): HTMLButtonElement[] {
  if (!listEl.value) return []
  return Array.from(listEl.value.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]'))
}

function closeMenu(restoreFocus = true) {
  switcherOpen.value = false
  if (restoreFocus) triggerEl.value?.focus()
}

function onDocumentPointerDown(event: MouseEvent) {
  if (!switcherOpen.value) return
  if (rootEl.value && !rootEl.value.contains(event.target as Node)) closeMenu()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (!switcherOpen.value) return

  if (event.key === 'Escape') {
    event.stopPropagation()
    closeMenu()
    return
  }

  const items = menuItems()
  if (items.length === 0) return

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'ArrowDown'
      ? (current + 1) % items.length
      : (current <= 0 ? items.length - 1 : current - 1)
    items[next]?.focus()
    return
  }

  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    const target = event.key === 'Home' ? items[0] : items[items.length - 1]
    target?.focus()
  }
}

function bindDocumentListeners() {
  if (import.meta.server) return
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
}

function unbindDocumentListeners() {
  if (import.meta.server) return
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
}

watch(switcherOpen, (open) => {
  if (open) {
    bindDocumentListeners()
    // Land on the clinic that is currently active, so Enter confirms what the
    // trigger already says.
    nextTick(() => {
      const items = menuItems()
      const active = items.find(item => item.dataset.clinicId === selected.value) ?? items[0]
      active?.focus()
    })
  } else {
    unbindDocumentListeners()
  }
})

onBeforeUnmount(unbindDocumentListeners)

async function choose(id: string) {
  switcherOpen.value = false
  if (id === selected.value) return
  // Switching mints a new token and reloads the page. A second click in that
  // window would mint a token for a *different* clinic and race the reload, so
  // the switch is single-flight and the trigger shows it.
  if (isSwitching.value) return
  isSwitching.value = true
  try {
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
  } finally {
    isSwitching.value = false
  }
}
</script>

<template>
  <ClientOnly>
    <div
      v-if="multiple"
      ref="rootEl"
      class="relative"
    >
      <button
        ref="triggerEl"
        type="button"
        class="flex items-center gap-2 min-w-0 rounded-lg px-2 py-1.5 text-sm text-ui hover:bg-elevated transition-colors"
        :title="currentName"
        aria-haspopup="menu"
        :aria-expanded="switcherOpen"
        :disabled="isSwitching"
        @click="switcherOpen = !switcherOpen"
      >
        <UIcon
          name="i-lucide-building-2"
          class="w-4 h-4 text-subtle shrink-0"
        />
        <span class="truncate max-w-[8rem] sm:max-w-[12rem]">{{ currentName }}</span>
        <UIcon
          :name="isSwitching ? 'i-lucide-loader-2' : 'i-lucide-chevrons-up-down'"
          class="w-3.5 h-3.5 text-subtle shrink-0"
          :class="isSwitching ? 'animate-spin' : ''"
        />
      </button>

      <div
        v-if="switcherOpen"
        ref="listEl"
        role="menu"
        aria-orientation="vertical"
        class="absolute right-0 top-full mt-1 z-50 min-w-[14rem] rounded-xl border border-default bg-surface shadow-xl overflow-hidden"
      >
        <button
          v-for="c in options"
          :key="c.id"
          type="button"
          role="menuitem"
          :data-clinic-id="c.id"
          :aria-current="c.id === selected ? 'true' : undefined"
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
