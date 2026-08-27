<script setup lang="ts">
import type { TreatmentPlanStatus } from '~~/app/types'

const props = defineProps<{
  status: TreatmentPlanStatus
  size?: 'xs' | 'sm' | 'md'
}>()

const { t } = useI18n()

const colorMap: Record<TreatmentPlanStatus, 'neutral' | 'info' | 'success' | 'error'> = {
  draft: 'neutral',
  active: 'info',
  completed: 'success',
  archived: 'neutral',
  cancelled: 'error'
}

const color = computed(() => colorMap[props.status] || 'neutral')
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
