<script setup lang="ts">
const { t } = useI18n()
const { state, transcript, error, lastCommand, isBusy, start, stop, reset } = useDentoraVoice()
const open = ref(false)

const icon = computed(() => state.value === 'listening' ? 'i-lucide-square' : 'i-lucide-mic')
const statusLabel = computed(() => t(`voice.states.${state.value}`))
</script>

<template>
  <div class="fixed bottom-5 right-5 z-[100] flex flex-col items-end gap-2">
    <div
      v-if="open"
      data-testid="dentora-voice-panel"
      class="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-default bg-default p-4 shadow-xl"
    >
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-sm font-semibold text-default">
            {{ t('voice.title') }}
          </p>
          <p class="text-caption text-muted">
            {{ statusLabel }}
          </p>
        </div>
        <UButton
          icon="i-lucide-x"
          variant="ghost"
          color="neutral"
          size="xs"
          :aria-label="t('voice.close')"
          @click="open = false"
        />
      </div>

      <div
        v-if="transcript"
        data-testid="dentora-voice-transcript"
        class="mb-3 rounded-md bg-elevated p-2 text-sm text-default"
      >
        {{ transcript }}
      </div>
      <p
        v-if="lastCommand"
        class="mb-2 text-caption text-muted"
      >
        {{ lastCommand }}
      </p>
      <p
        v-if="error"
        data-testid="dentora-voice-error"
        class="mb-3 text-caption text-error"
      >
        {{ t(`voice.errors.${error}`, error) }}
      </p>

      <div class="flex gap-2">
        <UButton
          v-if="state !== 'listening'"
          data-testid="dentora-voice-start"
          icon="i-lucide-mic"
          :disabled="isBusy"
          @click="start"
        >
          {{ t('voice.listen') }}
        </UButton>
        <UButton
          v-else
          data-testid="dentora-voice-stop"
          icon="i-lucide-square"
          color="error"
          @click="stop"
        >
          {{ t('voice.stop') }}
        </UButton>
        <UButton
          v-if="!isBusy && state !== 'idle'"
          variant="ghost"
          color="neutral"
          @click="reset"
        >
          {{ t('voice.reset') }}
        </UButton>
      </div>
      <p class="mt-3 text-xs text-muted">
        {{ t('voice.localOnly') }}
      </p>
    </div>

    <UButton
      data-testid="dentora-voice-launcher"
      :icon="icon"
      size="xl"
      :color="state === 'error' ? 'error' : 'primary'"
      class="rounded-full shadow-lg"
      :aria-label="t('voice.title')"
      @click="state === 'listening' ? stop() : (open = !open)"
    />
  </div>
</template>
