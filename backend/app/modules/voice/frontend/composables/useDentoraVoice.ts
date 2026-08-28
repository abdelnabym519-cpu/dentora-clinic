import { computed, nextTick, ref } from 'vue'

type VoiceState =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'executing'
  | 'success'
  | 'error'
  | 'confirmation_required'
  | 'clarification_required'

interface VoiceUIContext {
  route: string
  patient_id?: string
  current_study?: string
  selected_study?: string
  comparison_study?: string
  viewer_open: boolean
  implant_planner_open: boolean
}

interface UIAction {
  action: string
  payload: Record<string, unknown>
}

interface StepResult {
  command: string
  ok: boolean
  message?: string
  ui_action?: UIAction
  clarification_required: boolean
  confirmation_required: boolean
}

interface ExecuteResult {
  state: VoiceState
  steps: StepResult[]
}

interface RuntimeTranscription {
  text: string
  language?: string
  duration_seconds?: number
}

const LOOPBACK_RUNTIME = 'http://127.0.0.1:8765'

function currentContext(routePath: string): VoiceUIContext {
  const patientMatch = routePath.match(/^\/patients\/([0-9a-f-]{36})(?:\/|$)/i)
  return {
    route: routePath,
    patient_id: patientMatch?.[1],
    viewer_open: Boolean(document.querySelector('[data-testid="dental3d-card"]')),
    implant_planner_open: Boolean(
      document.querySelector('[data-testid="dental3d-implant-planning"]')
    )
  }
}

async function waitFor(selector: string, timeoutMs = 3500): Promise<HTMLElement | null> {
  const started = performance.now()
  while (performance.now() - started < timeoutMs) {
    const found = document.querySelector(selector)
    if (found instanceof HTMLElement) return found
    await new Promise(resolve => setTimeout(resolve, 75))
  }
  return null
}

export function useDentoraVoice() {
  const { post } = useApi()
  const route = useRoute()
  const state = ref<VoiceState>('idle')
  const transcript = ref('')
  const error = ref('')
  const language = ref('')
  const lastCommand = ref('')
  const recorder = ref<MediaRecorder | null>(null)
  const stream = ref<MediaStream | null>(null)
  const chunks = ref<Blob[]>([])

  const isBusy = computed(() =>
    ['listening', 'processing', 'executing'].includes(state.value)
  )

  async function applyAction(action: UIAction): Promise<boolean> {
    const payload = action.payload || {}
    const targetRoute = typeof payload.route === 'string' ? payload.route : null

    if (targetRoute && route.path !== targetRoute) {
      const query =
        typeof payload.search === 'string' && payload.search
          ? { search: payload.search }
          : undefined
      await navigateTo({ path: targetRoute, query })
      await nextTick()
    }

    const targets: Record<string, string> = {
      open_cbct: '[data-testid="dental3d-cbct-mpr"]',
      show_3d: '[data-testid="dental3d-card"]',
      show_tooth_segmentation: '[data-testid="dental3d-segmentation"]',
      show_nerve: '[data-testid="dental3d-nerve"]',
      open_implant_planner: '[data-testid="dental3d-implant-planning"]'
    }
    if (action.action === 'navigate') return true
    const selector = targets[action.action]
    if (!selector) return false
    const element = await waitFor(selector)
    if (!element) return false

    if (action.action === 'show_nerve') {
      const toggle = document.querySelector('[data-testid="dental3d-nerve-toggle"]')
      if (toggle instanceof HTMLInputElement && !toggle.checked) toggle.click()
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return true
  }

  async function executeTranscript(text: string): Promise<void> {
    state.value = 'executing'
    error.value = ''
    const response = await post<{ data: ExecuteResult }>('/voice/execute', {
      transcript: text,
      context: currentContext(route.path)
    })
    const result = response.data
    for (const step of result.steps) {
      lastCommand.value = step.command
      if (step.ui_action && step.ok) {
        const applied = await applyAction(step.ui_action)
        if (!applied) {
          state.value = 'error'
          error.value = 'voice_target_unavailable'
          return
        }
      }
      if (!step.ok) {
        state.value = step.clarification_required
          ? 'clarification_required'
          : step.confirmation_required
            ? 'confirmation_required'
            : 'error'
        error.value = step.message || 'voice_command_failed'
        return
      }
    }
    state.value = result.state
  }

  async function transcribe(blob: Blob): Promise<RuntimeTranscription> {
    const form = new FormData()
    form.append('audio', blob, 'dentora-voice.webm')
    const response = await fetch(`${LOOPBACK_RUNTIME}/transcribe`, {
      method: 'POST',
      body: form,
      credentials: 'omit',
      cache: 'no-store'
    })
    if (!response.ok) {
      throw new Error(`Local voice runtime unavailable (${response.status})`)
    }
    return (await response.json()) as RuntimeTranscription
  }

  async function start(): Promise<void> {
    if (isBusy.value) return
    error.value = ''
    transcript.value = ''
    const media = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.value = media
    const preferred = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    const instance = new MediaRecorder(media, { mimeType: preferred })
    recorder.value = instance
    chunks.value = []
    instance.ondataavailable = event => {
      if (event.data.size > 0) chunks.value.push(event.data)
    }
    instance.onstop = async () => {
      try {
        state.value = 'processing'
        const audio = new Blob(chunks.value, { type: preferred })
        const result = await transcribe(audio)
        transcript.value = result.text.trim().slice(0, 500)
        language.value = result.language || ''
        if (!transcript.value) throw new Error('No speech recognized')
        await executeTranscript(transcript.value)
      } catch (cause) {
        state.value = 'error'
        error.value = cause instanceof Error ? cause.message : 'voice_runtime_error'
      } finally {
        stream.value?.getTracks().forEach(track => track.stop())
        stream.value = null
        recorder.value = null
        chunks.value = []
      }
    }
    instance.start()
    state.value = 'listening'
  }

  function stop(): void {
    if (recorder.value?.state === 'recording') recorder.value.stop()
  }

  function reset(): void {
    if (!isBusy.value) {
      state.value = 'idle'
      error.value = ''
      transcript.value = ''
      lastCommand.value = ''
    }
  }

  return {
    state,
    transcript,
    error,
    language,
    lastCommand,
    isBusy,
    start,
    stop,
    reset
  }
}
