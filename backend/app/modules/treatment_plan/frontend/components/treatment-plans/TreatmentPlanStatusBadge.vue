<script setup lang="ts">
import type { TreatmentPlanStatus } from '~~/app/types'

const props = defineProps<{
  status: TreatmentPlanStatus
  size?: 'xs' | 'sm' | 'md'
}>()

const { t } = useI18n()

const colorMap: Record<TreatmentPlanStatus, 'neutral' | 'warning' | 'success' | 'info' | 'error'> = {
  draft: 'neutral',
  pending: 'warning',
  active: 'success',
  completed: 'info',
  archived: 'neutral',
  closed: 'error',
  cancelled: 'error'
}

const color = computed(() => colorMap[props.status] ?? 'neutral')
const label = computed(() => t(`treatmentPlans.status.${props.status}`))
</script>

<template>
  <UBadge
    :color="color"
    :size="size || 'sm'"
    variant="subtle"
  >
    {{ label }}
  </UBadge>
</template>
