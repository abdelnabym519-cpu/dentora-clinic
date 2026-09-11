<script setup lang="ts">
/**
 * TreatmentNoteButton — small note action attached to every Treatment row
 * shown in the odontogram conditions list and the treatment-plan rows.
 *
 * Mounted via the ``odontogram.condition.actions`` slot. Receives
 * ``ctx.treatmentId`` (and optional toothNumber/status). Click opens a
 * popover with the latest treatment notes + an inline composer.
 */

import type { ClinicalNote, RecentNoteEntry } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorMessage } from '~~/app/utils/error'

const props = defineProps<{
  ctx: {
    treatmentId: string
    toothNumber?: number | null
    status?: string
    /** When provided, enables the inline attachment uploader on the composer. */
    patientId?: string | null
  }
}>()

const { t } = useI18n()
const { can } = usePermissions()
const {
  listForOwner,
  createNote,
  updateNote,
  deleteNote
} = useClinicalNotes()
const { user } = useAuth()

const open = ref(false)
const notes = ref<ClinicalNote[]>([])
const loading = ref(false)
/** Set when the treatment's notes could not be read. */
const loadError = ref<string | null>(null)
const composerOpen = ref(false)
const editingId = ref<string | null>(null)
const composerBody = ref('')
const saving = ref(false)

const canRead = computed(() => can(PERMISSIONS.clinicalNotes.read))
const canWrite = computed(() => can(PERMISSIONS.clinicalNotes.write))

async function loadCount() {
  if (!canRead.value) return
  try {
    // Ambient badge count on every treatment row: a failure here must not
    // broadcast a global toast over the odontogram.
    notes.value = await listForOwner('treatment', props.ctx.treatmentId, { silent: true })
  } catch {
    notes.value = []
  }
}

async function refreshFull() {
  loading.value = true
  loadError.value = null
  try {
    notes.value = await listForOwner('treatment', props.ctx.treatmentId, { silent: true })
  } catch (e) {
    // Was try/finally with no catch: the popover rendered "no notes yet" and,
    // worse, the failure escaped `handleSubmit`'s try/finally — so a note that
    // saved fine but whose refresh failed looked like a failed save, leaving
    // the composer open with the body still in it (a duplicate-note trap).
    console.error('Error loading treatment notes:', e)
    notes.value = []
    loadError.value = errorMessage(e, t('errors.loadFailed'))
  } finally {
    loading.value = false
  }
}

function asEntry(note: ClinicalNote): RecentNoteEntry {
  return {
    id: note.id,
    note_type: note.note_type,
    owner_type: note.owner_type,
    owner_id: note.owner_id,
    tooth_number: note.tooth_number,
    body: note.body,
    created_at: note.created_at,
    updated_at: note.updated_at,
    author: { id: note.author_id, full_name: null, email: null },
    linked: { kind: 'treatment', id: note.owner_id, label: null, tooth_number: null },
    attachments: note.attachments
  }
}

function handleOpen(value: boolean) {
  open.value = value
  if (value) refreshFull()
}

function startNew() {
  editingId.value = null
  composerBody.value = ''
  composerOpen.value = true
}

function startEdit(entry: RecentNoteEntry) {
  editingId.value = entry.id
  composerBody.value = entry.body
  composerOpen.value = true
}

async function handleSubmit(payload: {
  body: string
  toothNumber: number | null
  attachmentDocumentIds: string[]
}) {
  saving.value = true
  try {
    if (editingId.value) {
      await updateNote(editingId.value, payload.body)
    } else {
      await createNote({
        note_type: 'treatment',
        owner_type: 'treatment',
        owner_id: props.ctx.treatmentId,
        body: payload.body,
        attachment_document_ids: payload.attachmentDocumentIds
      })
    }
    composerOpen.value = false
    editingId.value = null
    composerBody.value = ''
    await refreshFull()
  } finally {
    saving.value = false
  }
}

async function handleDelete(entry: RecentNoteEntry) {
  const ok = await deleteNote(entry.id)
  if (ok) await refreshFull()
}

function canEditEntry(entry: RecentNoteEntry): boolean {
  return canWrite.value && !!entry.author?.id && entry.author.id === user.value?.id
}

const visibleCount = computed(() => notes.value.length)

watch(() => props.ctx?.treatmentId, loadCount, { immediate: true })
</script>

<template>
  <UPopover
    v-if="canRead"
    v-model:open="open"
    :ui="{ content: 'w-[min(28rem,90vw)]' }"
    @update:open="handleOpen"
  >
    <UButton
      :icon="visibleCount > 0 ? 'i-lucide-message-square-text' : 'i-lucide-message-square-plus'"
      size="xs"
      variant="ghost"
      :color="visibleCount > 0 ? 'success' : 'neutral'"
      :aria-label="t('clinicalNotes.treatmentButton.aria', { n: visibleCount })"
      :class="{ 'font-medium': visibleCount > 0 }"
    >
      <span
        v-if="visibleCount > 0"
        class="ml-1 text-caption tnum"
      >{{ visibleCount }}</span>
    </UButton>
    <template #content>
      <div class="p-3 space-y-3">
        <header class="flex items-center justify-between">
          <h4 class="font-medium text-sm">
            {{ t('clinicalNotes.treatmentButton.title') }}
            <span
              v-if="ctx?.toothNumber"
              class="text-caption text-muted ml-1"
            >· {{ t('clinicalNotes.linked.tooth', { n: ctx.toothNumber }) }}</span>
          </h4>
          <UButton
            v-if="canWrite && !composerOpen"
            size="xs"
            variant="soft"
            color="primary"
            icon="i-lucide-plus"
            @click="startNew"
          >
            {{ t('clinicalNotes.treatmentButton.add') }}
          </UButton>
        </header>

        <NoteComposer
          v-if="composerOpen && canWrite"
          :note-type="'treatment'"
          :initial-body="composerBody"
          :patient-id="ctx?.patientId"
          :busy="saving"
          autofocus
          @submit="handleSubmit"
          @cancel="composerOpen = false"
        />

        <div
          v-if="loading"
          class="space-y-2"
        >
          <USkeleton
            v-for="i in 2"
            :key="i"
            class="h-16 w-full"
          />
        </div>
        <div
          v-else-if="loadError"
          class="space-y-2"
          data-testid="treatment-notes-load-error"
        >
          <UAlert
            color="error"
            variant="soft"
            icon="i-lucide-alert-triangle"
            :title="t('errors.loadFailed')"
            :description="loadError"
          />
          <UButton
            variant="ghost"
            size="sm"
            icon="i-lucide-refresh-cw"
            data-testid="treatment-notes-retry"
            @click="refreshFull()"
          >
            {{ t('common.retry') }}
          </UButton>
        </div>
        <div
          v-else-if="notes.length === 0"
          class="text-center py-3 text-sm text-subtle"
        >
          {{ t('clinicalNotes.treatmentButton.empty') }}
        </div>
        <div
          v-else
          class="space-y-2 max-h-[40vh] overflow-y-auto pr-1"
        >
          <NoteCard
            v-for="note in notes"
            :key="note.id"
            :note-id="note.id"
            :note-type="note.note_type"
            :body="note.body"
            :created-at="note.created_at"
            :author="asEntry(note).author"
            :linked="asEntry(note).linked"
            :attachments="note.attachments"
            :can-edit="canEditEntry(asEntry(note))"
            @edit="startEdit(asEntry(note))"
            @delete="handleDelete(asEntry(note))"
          />
        </div>
      </div>
    </template>
  </UPopover>
</template>
