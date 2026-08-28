from pathlib import Path
import re


def edit(path: str, transform) -> None:
    p = Path(path)
    text = p.read_text()
    new = transform(text)
    if new != text:
        p.write_text(new)


def replace(path: str, old: str, new: str) -> None:
    edit(path, lambda text: text.replace(old, new))


# Catalog: validate API string values at the typed UI boundary; keep numeric/UI props typed.
path = 'backend/app/modules/catalog/frontend/components/catalog/CatalogItemModal.vue'
replace(path,
"""      if (newItem.odontogram_mapping) {
        odontogramType.value = newItem.odontogram_mapping.odontogram_treatment_type
        clinicalCategory.value = newItem.odontogram_mapping.clinical_category
      } else {""",
"""      if (newItem.odontogram_mapping) {
        odontogramType.value = ALL_TREATMENT_TYPES.find(
          type => type === newItem.odontogram_mapping?.odontogram_treatment_type
        )
        clinicalCategory.value = TREATMENT_CATEGORIES.find(
          category => category.key === newItem.odontogram_mapping?.clinical_category
        )?.key
      } else {""")
replace(path, '                  rows="2"', '                  :rows="2"')

path = 'backend/app/modules/catalog/frontend/composables/useTreatmentCatalog.ts'
replace(path,
"""      const treatments = treatmentsByCategory.value[categoryKey]
      if (treatments && treatments.length > 0) {
        return treatments[0].category_names[loc] || treatments[0].category_names.es || treatments[0].category_names.en || categoryKey
      }""",
"""      const first = treatmentsByCategory.value[categoryKey]?.[0]
      if (first) {
        return first.category_names[loc] || first.category_names.es || first.category_names.en || categoryKey
      }""")

# Notifications: only editable scalar fields are exposed; no dictionary cast.
path = 'backend/app/modules/notifications/frontend/pages/settings/notifications.vue'
pattern = re.compile(r"// Get setting value with fallback\nfunction getSettingValue\(.*?\n\}\n\n// Update local setting\nfunction updateLocalSetting\(.*?\n\}", re.S)
replacement = """// Get setting value with fallback
type EditableNotificationField = 'enabled' | 'auto_send' | 'hours_before'

function getSettingValue(key: string, field: EditableNotificationField): boolean | number {
  const setting = localSettings.value[key]
  if (!setting) return field === 'hours_before' ? 24 : true
  if (field === 'hours_before') return setting.hours_before ?? 24
  return setting[field]
}

// Update local setting
function updateLocalSetting(key: string, field: EditableNotificationField, value: boolean | number) {
  const setting = localSettings.value[key] ?? { auto_send: true, enabled: true }
  localSettings.value[key] = setting
  if (field === 'hours_before') setting.hours_before = Number(value)
  else setting[field] = Boolean(value)
  onSettingChange()
}"""
edit(path, lambda text: pattern.sub(replacement, text, count=1))

# Odontogram strict indexing and canonical color helpers.
path = 'backend/app/modules/odontogram/frontend/components/clinical/DiagnosisCTA.vue'
replace(path,
"const selectedDraftId = ref<string>('')\n",
"const selectedDraftId = ref<string>('')\nconst singleDraft = computed(() => props.draftPlans.length === 1 ? props.draftPlans[0] : undefined)\n")
replace(path, '        v-else-if="draftPlans.length === 1"', '        v-else-if="singleDraft"')
replace(path, "@click=\"emit('continue', draftPlans[0].id)\"", "@click=\"emit('continue', singleDraft.id)\"")
replace(path, "{ name: draftPlans[0].title || t('treatmentPlans.untitledPlan') }", "{ name: singleDraft.title || t('treatmentPlans.untitledPlan') }")

path = 'backend/app/modules/odontogram/frontend/components/clinical/HistoryMode.vue'
replace(path,
"""    if (timelineDates.value.length > 0) {
      const mostRecent = timelineDates.value[timelineDates.value.length - 1]
      await fetchOdontogramAtDate(props.patientId, mostRecent.date)
    }""",
"""    const mostRecent = timelineDates.value.at(-1)
    if (mostRecent) {
      await fetchOdontogramAtDate(props.patientId, mostRecent.date)
    }""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ChangeHistorySection.vue'
replace(path,
"import { getToothNameKey, getToothPositionKeys, TREATMENT_COLORS } from '~~/app/config/odontogramConstants'",
"import { getToothNameKey, getToothPositionKeys, getTreatmentColor as resolveTreatmentColor } from '~~/app/config/odontogramConstants'")
replace(path,
"""function getConditionColor(condition?: string): string {
  if (!condition) return '#E5E7EB'
  return TREATMENT_COLORS[condition] || '#E5E7EB'
}""",
"""function getConditionColor(condition?: string): string {
  return condition ? resolveTreatmentColor(condition) : '#E5E7EB'
}""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/GlobalTreatmentsStrip.vue'
replace(path,
"""  if (tr.clinical_type === 'migrated' && tr.notes) {
    const trimmed = tr.notes.trim()
    return trimmed.length > 60 ? `${trimmed.slice(0, 60)}…` : trimmed
  }""",
"""  if (tr.notes) {
    const trimmed = tr.notes.trim()
    if (trimmed) return trimmed.length > 60 ? `${trimmed.slice(0, 60)}…` : trimmed
  }""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ImplantSVG.vue'
replace(path, "import { STATUS_STYLES } from './ToothSVGPaths'", "import { STATUS_STYLES } from '~~/app/config/odontogramConstants'")
replace(path, "const statusStyle = computed(() => STATUS_STYLES[props.status] || STATUS_STYLES.existing)", "const statusStyle = computed(() => STATUS_STYLES[props.status])")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/OdontogramChart.vue'
replace(path, "actions: [{ label: t('common.undo'), click: handleUndo }]", "actions: [{ label: t('common.undo'), onClick: handleUndo }]")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TimelineSlider.vue'
replace(path,
"""  const lastDate = props.dates[props.dates.length - 1].date
  const today = new Date().toISOString().split('T')[0]
  return lastDate === today""",
"""  const lastDate = props.dates.at(-1)?.date
  const today = new Date().toISOString().slice(0, 10)
  return lastDate === today""")
replace(path,
"""  if (currentIndex.value === null) return t('common.now')
  return formatDate(props.dates[currentIndex.value].date)""",
"""  if (currentIndex.value === null) return t('common.now')
  const item = props.dates[currentIndex.value]
  return item ? formatDate(item.date) : t('common.now')""")
replace(path,
"""  const isLastAndToday = lastDateIsToday.value && index === props.dates.length - 1
  return isLastAndToday ? t('common.now') : formatDate(props.dates[index].date)""",
"""  const isLastAndToday = lastDateIsToday.value && index === props.dates.length - 1
  if (isLastAndToday) return t('common.now')
  const item = props.dates[index]
  return item ? formatDate(item.date) : ''""")
replace(path,
"  emit('update:currentDate', props.dates[index].date)",
"  const item = props.dates[index]\n  emit('update:currentDate', item?.date ?? null)")
replace(path,
"""  const clientX = 'touches' in event ? event.touches[0].clientX : event.clientX
  const rect = sliderRef.value.getBoundingClientRect()""",
"""  const touch = 'touches' in event ? event.touches[0] : undefined
  const clientX = touch?.clientX ?? ('clientX' in event ? event.clientX : undefined)
  if (clientX === undefined) return
  const rect = sliderRef.value.getBoundingClientRect()""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ToothDualView.vue'
replace(path,
"import type { Surface, ToothTreatmentView, TreatmentStatus } from '~~/app/types'",
"import type { Surface, ToothTreatmentView, TreatmentStatus } from '~~/app/types'")
replace(path, 'function getTreatmentOfType(type: string): Treatment | undefined', 'function getTreatmentOfType(type: string): ToothTreatmentView | undefined')
replace(path, 'function getImplantFill(_treatment: Treatment): string {\n  return TREATMENT_COLORS.implant || \'#10B981\'\n}', "function getImplantFill(_treatment: ToothTreatmentView): string {\n  return getTreatmentColor('implant')\n}")
replace(path, 'function getPulpTreatment(): Treatment | undefined', 'function getPulpTreatment(): ToothTreatmentView | undefined')
replace(path, 'function getOcclusalConfig(treatment: Treatment)', 'function getOcclusalConfig(treatment: ToothTreatmentView)')
replace(path, 'function _getPatternConfig(treatment: Treatment)', 'function _getPatternConfig(treatment: ToothTreatmentView)')
insert_marker = "function getImplantFill(_treatment: ToothTreatmentView): string {\n  return getTreatmentColor('implant')\n}\n"
if insert_marker in Path(path).read_text() and 'function getTreatmentOpacity(type: string)' not in Path(path).read_text():
    replace(path, insert_marker, insert_marker + "\nfunction getTreatmentOpacity(type: string): number {\n  const treatment = getTreatmentOfType(type)\n  return treatment ? (STATUS_STYLES[treatment.status]?.opacity ?? 1) : 1\n}\n")
replace(path, ':fill="TREATMENT_COLORS.root_canal"', ':fill="getTreatmentColor(\'root_canal\')"')
replace(path, ":opacity=\"STATUS_STYLES[getTreatmentOfType('root_canal')!.status].opacity\"", ":opacity=\"getTreatmentOpacity('root_canal')\"")
replace(path, ':fill="TREATMENT_COLORS.post"', ':fill="getTreatmentColor(\'post\')"')
replace(path, ":opacity=\"STATUS_STYLES[getTreatmentOfType('post')!.status].opacity\"", ":opacity=\"getTreatmentOpacity('post')\"")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ToothQuadrant.vue'
replace(path, ":ui=\"{ width: 'min-w-48 max-w-72' }\"", ":ui=\"{ content: 'min-w-48 max-w-72' }\"")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ToothSVGPaths.ts'
replace(path,
"  return TOOTH_DISPLAY_CONFIG[position] || TOOTH_DISPLAY_CONFIG[1]",
"""  const config = TOOTH_DISPLAY_CONFIG[position] ?? TOOTH_DISPLAY_CONFIG[1]
  if (!config) throw new Error('Missing canonical tooth display configuration')
  return config""")
replace(path,
"  return LATERAL_PATHS_BY_POSITION[position] || LATERAL_PATHS_BY_POSITION[1]",
"""  const paths = LATERAL_PATHS_BY_POSITION[position] ?? LATERAL_PATHS_BY_POSITION[1]
  if (!paths) throw new Error('Missing canonical lateral tooth paths')
  return paths""")
replace(path,
"  return OCCLUSAL_PATHS_BY_POSITION[position] || OCCLUSAL_PATHS_BY_POSITION[1]",
"""  const paths = OCCLUSAL_PATHS_BY_POSITION[position] ?? OCCLUSAL_PATHS_BY_POSITION[1]
  if (!paths) throw new Error('Missing canonical occlusal tooth paths')
  return paths""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/ToothTooltip.vue'
replace(path, "import { TREATMENT_COLORS } from '~~/app/config/odontogramConstants'", "import { getTreatmentColor } from '~~/app/config/odontogramConstants'")
replace(path, 'const groups: Record<TreatmentStatus, Treatment[]> = {', 'const groups: Record<TreatmentStatus, ToothTreatmentView[]> = {')
replace(path, 'function handleEditClick(event: Event, treatment: Treatment)', 'function handleEditClick(event: Event, treatment: ToothTreatmentView)')
replace(path, ":style=\"{ backgroundColor: TREATMENT_COLORS[treatment.treatment_type] || '#9CA3AF' }\"", ':style="{ backgroundColor: getTreatmentColor(treatment.treatment_type) }"')

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TreatmentBar.vue'
replace(path,
"""  const allowedStatuses = getEffectiveAllowedStatuses(item.odontogramType)
  if (allowedStatuses.length === 1 && !allowedStatuses.includes(props.selectedStatus)) {
    emit('update:selectedStatus', allowedStatuses[0])
  } else if (!allowedStatuses.includes(props.selectedStatus)) {
    emit('update:selectedStatus', allowedStatuses[0])
  }""",
"""  const allowedStatuses = getEffectiveAllowedStatuses(item.odontogramType)
  const preferredStatus = allowedStatuses[0]
  if (preferredStatus && !allowedStatuses.includes(props.selectedStatus)) {
    emit('update:selectedStatus', preferredStatus)
  }""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TreatmentEditModal.vue'
replace(path,
"import { TREATMENT_COLORS, isSurfaceTreatment, getAllowedStatusesForTreatment } from '~~/app/config/odontogramConstants'",
"import { getTreatmentColor, isSurfaceTreatment, getAllowedStatusesForTreatment } from '~~/app/config/odontogramConstants'")
replace(path,
"""const treatmentColor = computed(() => {
  if (!props.treatment) return '#9CA3AF'
  return TREATMENT_COLORS[props.treatment.treatment_type] || '#9CA3AF'
})""",
"""const treatmentColor = computed(() => {
  if (!props.treatment) return '#9CA3AF'
  return getTreatmentColor(props.treatment.treatment_type)
})""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TreatmentIcons.ts'
replace(path,
"""export function getTreatmentIcon(treatmentType: string): string {
  return TREATMENT_ICONS[treatmentType] || TREATMENT_ICONS.filling
}""",
"""export function getTreatmentIcon(treatmentType: string): string {
  const icon = TREATMENT_ICONS[treatmentType] ?? TREATMENT_ICONS.filling
  if (!icon) throw new Error('Missing canonical treatment icon fallback')
  return icon
}""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TreatmentListSection.vue'
replace(path,
"import { getToothNameKey, getToothPositionKeys, TREATMENT_COLORS } from '~~/app/config/odontogramConstants'",
"import { getToothNameKey, getToothPositionKeys, getTreatmentColor as resolveTreatmentColor } from '~~/app/config/odontogramConstants'")
replace(path,
"""function getTreatmentColor(treatmentType: string): string {
  return TREATMENT_COLORS[treatmentType] || '#9CA3AF'
}""",
"""function getTreatmentColor(treatmentType: string): string {
  return resolveTreatmentColor(treatmentType)
}""")

path = 'backend/app/modules/odontogram/frontend/components/odontogram/TreatmentSummary.vue'
replace(path, "import { TREATMENT_COLORS, STATUS_STYLES } from './ToothSVGPaths'", "import { getTreatmentColor } from '~~/app/config/odontogramConstants'")
replace(path,
"""    if (!grouped[treatment.treatment_type]) {
      grouped[treatment.treatment_type] = { count: 0, teeth: [], treatments: [] }
    }
    grouped[treatment.treatment_type].count++
    if (!grouped[treatment.treatment_type].teeth.includes(treatment.tooth_number)) {
      grouped[treatment.treatment_type].teeth.push(treatment.tooth_number)
    }
    grouped[treatment.treatment_type].treatments.push(treatment)""",
"""    let group = grouped[treatment.treatment_type]
    if (!group) {
      group = { count: 0, teeth: [], treatments: [] }
      grouped[treatment.treatment_type] = group
    }
    group.count++
    if (!group.teeth.includes(treatment.tooth_number)) {
      group.teeth.push(treatment.tooth_number)
    }
    group.treatments.push(treatment)""")
if 'function getStatusDotColor' not in Path(path).read_text():
    replace(path,
"""function getTreatmentLabel(type: string): string {
  return t(`odontogram.treatments.types.${type}`, type)
}""",
"""function getTreatmentLabel(type: string): string {
  return t(`odontogram.treatments.types.${type}`, type)
}

function getStatusDotColor(status: TreatmentStatus): string {
  return status === 'planned' ? '#F59E0B' : '#6B7280'
}""")
replace(path, ':style="{ backgroundColor: STATUS_STYLES[status].border }"', ':style="{ backgroundColor: getStatusDotColor(status) }"')
replace(path, ":style=\"{ backgroundColor: TREATMENT_COLORS[entry.type] || '#9CA3AF' }\"", ':style="{ backgroundColor: getTreatmentColor(entry.type) }"')

# Patient timeline and UI form state are non-null strings; API DTO stays nullable at submit boundary.
path = 'backend/app/modules/patient_timeline/frontend/components/patient/PatientTimeline.vue'
replace(path,
"""    (entries) => {
      if (entries[0].isIntersecting && hasMore.value && !isLoadingMore.value) {
        loadMore()
      }
    },""",
"""    (entries) => {
      const firstEntry = entries[0]
      if (firstEntry?.isIntersecting && hasMore.value && !isLoadingMore.value) {
        loadMore()
      }
    },""")

path = 'backend/app/modules/patients/frontend/components/patient/PatientSectionEditModal.vue'
replace(path, '  PatientAddress,\n  PatientBillingAddress\n', '')
replace(path, "  address: {\n    street: '',\n    city: '',\n    postal_code: '',\n    province: '',\n    country: 'ES'\n  } as PatientAddress", "  address: {\n    street: '',\n    city: '',\n    postal_code: '',\n    province: '',\n    country: 'ES'\n  }")
replace(path, "  billing_address: {\n    street: '',\n    city: '',\n    postal_code: '',\n    province: '',\n    country: 'ES'\n  } as PatientBillingAddress", "  billing_address: {\n    street: '',\n    city: '',\n    postal_code: '',\n    province: '',\n    country: 'ES'\n  }")
replace(path, '    demographicsForm.gender = props.patient.gender', '    demographicsForm.gender = props.patient.gender ?? undefined')
replace(path, '    demographicsForm.national_id_type = props.patient.national_id_type', '    demographicsForm.national_id_type = props.patient.national_id_type ?? undefined')
replace(path,
"    demographicsForm.address = props.patient.address || { street: '', city: '', postal_code: '', province: '', country: 'ES' }",
"""    Object.assign(demographicsForm.address, {
      street: props.patient.address?.street ?? '',
      city: props.patient.address?.city ?? '',
      postal_code: props.patient.address?.postal_code ?? '',
      province: props.patient.address?.province ?? '',
      country: props.patient.address?.country ?? 'ES'
    })""")
replace(path,
"    billingForm.billing_address = props.patient.billing_address || { street: '', city: '', postal_code: '', province: '', country: 'ES' }",
"""    Object.assign(billingForm.billing_address, {
      street: props.patient.billing_address?.street ?? '',
      city: props.patient.billing_address?.city ?? '',
      postal_code: props.patient.billing_address?.postal_code ?? '',
      province: props.patient.billing_address?.province ?? '',
      country: props.patient.billing_address?.country ?? 'ES'
    })""")

path = 'backend/app/modules/patients/frontend/components/patient/info/VisitSummaryCard.vue'
replace(path,
"""function appointmentTreatment(a: Appointment): string | null {
  if (a.treatments?.length) return a.treatments[0]?.name ?? null
  return a.treatment_type ?? null
}""",
"""function appointmentTreatment(a: Appointment): string | null {
  const treatment = a.treatments?.[0]
  if (treatment) {
    return treatment.names[locale.value] || treatment.names.es || treatment.names.en || treatment.internal_code
  }
  return a.treatment_type ?? null
}""")

path = 'backend/app/modules/patients/frontend/pages/patients/index.vue'
replace(path, "import type { Patient, PatientCreate, PaginatedResponse, ApiResponse } from '~~/app/types'", "import type { Patient, PaginatedResponse, ApiResponse } from '~~/app/types'")
replace(path, 'const newPatient = reactive<PatientCreate>({', 'const newPatient = reactive({')

# Schedule selector local UI state uses undefined, not API null.
path = 'backend/app/modules/schedules/frontend/components/settings/ProfessionalSchedulesPage.vue'
replace(path, 'const selectedProfessional = ref<string | null>(null)', 'const selectedProfessional = ref<string | undefined>(undefined)')

# Treatment-plan literal unions and Nuxt UI v4 slots.
path = 'backend/app/modules/treatment_plan/frontend/components/clinical/modals/ClosePlanModal.vue'
replace(path, "const reason = ref<string>('cancelled_by_clinic')", "type ClosureReason = typeof REASONS[number]\nconst reason = ref<ClosureReason>('cancelled_by_clinic')")

path = 'backend/app/modules/treatment_plan/frontend/components/clinical/modals/ContactLogModal.vue'
replace(path, "const channel = ref<string>('call')", "type ContactChannel = typeof CHANNELS[number]\nconst channel = ref<ContactChannel>('call')")

path = 'backend/app/modules/treatment_plan/frontend/components/treatment-plans/TreatmentPlanModal.vue'
replace(path, ":ui=\"{ width: 'sm:max-w-lg' }\"", ":ui=\"{ content: 'sm:max-w-lg' }\"")

path = 'backend/app/modules/treatment_plan/frontend/components/treatment-plans/TreatmentPlanStatusBadge.vue'
replace(path,
"const colorMap: Record<TreatmentPlanStatus, 'neutral' | 'info' | 'success' | 'error'> = {",
"const colorMap: Record<TreatmentPlanStatus, 'neutral' | 'info' | 'success' | 'warning' | 'error'> = {")
