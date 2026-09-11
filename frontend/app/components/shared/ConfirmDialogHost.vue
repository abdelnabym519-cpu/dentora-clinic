<script setup lang="ts">
/**
 * Renders whatever `useConfirmDialog()` is currently asking and resolves the
 * caller's promise. Mounted once in `app.vue`, so it covers every layout.
 */
const { t } = useI18n()
const { request, resolveConfirmDialog } = useConfirmDialog()

const isOpen = computed(() => request.value !== null)

function onOpenChange(open: boolean): void {
  // Dismissing (Escape, backdrop click) is a "no" — the caller's `await`
  // must always settle, or its `isSubmitting` flag stays stuck.
  if (!open) resolveConfirmDialog(false)
}
</script>

<template>
  <UModal
    :open="isOpen"
    data-testid="confirm-dialog"
    @update:open="onOpenChange"
  >
    <template #content>
      <UCard>
        <template #header>
          <div class="flex items-center gap-2">
            <UIcon
              :name="request?.danger ? 'i-lucide-alert-triangle' : 'i-lucide-help-circle'"
              class="w-5 h-5 shrink-0"
              :class="request?.danger ? 'text-danger-accent' : 'text-primary-accent'"
            />
            <h3 class="font-semibold text-default">
              {{ request?.title }}
            </h3>
          </div>
        </template>

        <p
          v-if="request?.description"
          class="text-muted"
        >
          {{ request.description }}
        </p>

        <div class="flex justify-end gap-2 pt-6">
          <UButton
            variant="ghost"
            data-testid="confirm-dialog-cancel"
            @click="resolveConfirmDialog(false)"
          >
            {{ request?.cancelLabel ?? t('common.cancel') }}
          </UButton>
          <UButton
            :color="request?.danger ? 'error' : 'primary'"
            data-testid="confirm-dialog-accept"
            @click="resolveConfirmDialog(true)"
          >
            {{ request?.confirmLabel ?? t('common.confirm') }}
          </UButton>
        </div>
      </UCard>
    </template>
  </UModal>
</template>
