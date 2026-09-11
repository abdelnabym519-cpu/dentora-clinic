import type { ApiResponse } from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'

export interface ConversationMessage {
  id: string
  channel: string
  direction: 'outbound' | 'inbound'
  message_kind: string
  status: string
  subject: string | null
  body_text: string | null
  template_key: string
  error_message: string | null
  created_at: string
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
}

const BASE = '/api/v1/notifications/conversations'

export function useConversation(patientId: string) {
  const api = useApi()
  const { t } = useI18n()
  const messages = ref<ConversationMessage[]>([])
  const loading = ref(false)
  const sending = ref(false)
  /**
   * A thread that failed to load is not an empty thread: rendering the
   * "no messages yet" state for an outage tells the clinician the
   * conversation never happened, and leaves the reply box looking usable.
   */
  const error = ref<string | null>(null)

  async function fetchThread(channel = 'whatsapp') {
    loading.value = true
    error.value = null
    try {
      const res = await api.get<ApiResponse<ConversationMessage[]>>(
        `${BASE}/${patientId}?channel=${channel}`,
        { silent: true }
      )
      messages.value = res.data ?? []
    } catch (e) {
      // Was try/finally with no catch: the rejection escaped the component's
      // bare `onMounted(() => conv.fetchThread())` as an unhandled rejection.
      console.error('Error loading conversation thread:', e)
      error.value = errorMessage(e, t('notifications.conversation.loadError'))
    } finally {
      loading.value = false
    }
  }

  async function reply(body: string, channel = 'whatsapp') {
    sending.value = true
    try {
      const res = await api.post<ApiResponse<ConversationMessage>>(
        `${BASE}/${patientId}/reply`,
        { channel, body }
      )
      messages.value.push(res.data)
      return true
    } finally {
      sending.value = false
    }
  }

  return { messages, loading, sending, error, fetchThread, reply }
}
