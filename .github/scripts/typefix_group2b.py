from pathlib import Path
import re


def replace(path: str, old: str, new: str, count: int = -1) -> None:
    p = Path(path)
    text = p.read_text()
    if old in text:
        p.write_text(text.replace(old, new, count))


def regex(path: str, pattern: str, repl: str, count: int = 0) -> None:
    p = Path(path)
    text = p.read_text()
    new, n = re.subn(pattern, repl, text, count=count, flags=re.MULTILINE | re.DOTALL)
    if n:
        p.write_text(new)

# Patient/UI contract fixes.
replace('backend/app/modules/patients/frontend/components/patient/PatientStickyHeader.vue',
    ':ui="{ text: \'font-semibold\' }"', ':ui="{ fallback: \'font-semibold\' }"')
path = 'backend/app/modules/patients/frontend/components/patient/info/VisitSummaryCard.vue'
p = Path(path)
text = p.read_text()
if 'const { t, locale } = useI18n()' not in text and 'const { t } = useI18n()' in text:
    text = text.replace('const { t } = useI18n()', 'const { t, locale } = useI18n()')
text = text.replace('treatment.name', "treatment.names[locale.value] || treatment.names.es || treatment.names.en || treatment.internal_code")
p.write_text(text)
path = 'backend/app/modules/patients_clinical/frontend/composables/usePatientAlerts.ts'
replace(path,
    "  function getSeverityColor(severity: PatientAlert['severity']): string {\n    const colors: Record<PatientAlert['severity'], string> = {",
    "  function getSeverityColor(severity: PatientAlert['severity']): 'error' | 'warning' | 'info' | 'neutral' {\n    const colors: Record<PatientAlert['severity'], 'error' | 'warning' | 'info' | 'neutral'> = {")
path = 'backend/app/modules/patients_clinical/frontend/components/patient/MedicalHistoryForm.vue'
replace(path, ":ui=\"{ item: { base: 'border rounded-lg mb-2' } }\"", ":ui=\"{ item: 'border rounded-lg mb-2' }\"")
path = 'backend/app/modules/patients_clinical/frontend/components/summary/MedicalHistoryCard.vue'
replace(path,
    "            v-for=\"a in topAllergies\"\n            :key=\"a.id\"",
    "            v-for=\"(a, index) in topAllergies\"\n            :key=\"`${a.name}-${index}`\"")

# Payments use Nuxt UI's actual item type and guard indexed allocation.
path = 'backend/app/modules/payments/frontend/components/PatientPaymentsPanel.vue'
replace(path,
    "import type { PatientExtended, PatientLedger, PatientLedgerEntry, PaymentMethod } from '~~/app/types'",
    "import type { PatientExtended, PatientLedger, PatientLedgerEntry, PaymentMethod } from '~~/app/types'\nimport type { DropdownMenuItem } from '@nuxt/ui'")
replace(path,
    "function rowMenuItems(entry: PatientLedgerEntry) {\n  if (entry.entry_type !== 'payment') return []\n  const items: Array<{ label: string, icon: string, to?: string, onSelect?: () => void, color?: string }> = [",
    "function rowMenuItems(entry: PatientLedgerEntry): DropdownMenuItem[] {\n  if (entry.entry_type !== 'payment') return []\n  const items: DropdownMenuItem[] = [")
path = 'backend/app/modules/payments/frontend/components/PaymentCreateModal.vue'
replace(path,
    "  if (form.value.allocations.length !== 1) return\n  form.value.allocations[0].amount = Number(newAmount) || 0",
    "  if (form.value.allocations.length !== 1) return\n  const allocation = form.value.allocations[0]\n  if (!allocation) return\n  allocation.amount = Number(newAmount) || 0")

# Periodontogram strict indexed access.
path = 'backend/app/modules/periodontogram/frontend/components/PerioArchBlock.vue'
replace(path,
    "function nextInCycle<T>(cycle: T[], current: T): T {\n  const idx = cycle.findIndex(v => v === current)\n  if (idx === -1) return cycle[1] ?? cycle[0]\n  return cycle[(idx + 1) % cycle.length]\n}",
    "function nextInCycle<T>(cycle: T[], current: T): T {\n  if (cycle.length === 0) return current\n  const idx = cycle.findIndex(v => v === current)\n  if (idx === -1) return cycle[1] ?? cycle[0] ?? current\n  return cycle[(idx + 1) % cycle.length] ?? current\n}")
path = 'backend/app/modules/periodontogram/frontend/components/PerioProfileStrip.vue'
replace(path,
    "  return toothIdx * COL_W + COL_W * offsets[siteIdx]",
    "  return toothIdx * COL_W + COL_W * (offsets[siteIdx] ?? 0.5)")
replace(path,
    "function siteAt(ti: number, si: number) {\n  const tooth = props.teeth[ti]\n  return tooth.sites.find(s => s.site_code === sites.value[si])\n}",
    "function siteAt(ti: number, si: number) {\n  const tooth = props.teeth[ti]\n  const code = sites.value[si]\n  if (!tooth || !code) return undefined\n  return tooth.sites.find(s => s.site_code === code)\n}")
path = 'backend/app/modules/periodontogram/frontend/components/PerioToothLateral.vue'
replace(path,
    "  const vbW = VIEWBOX_W_BY_POSITION[position] ?? VIEWBOX_W_BY_POSITION[1]\n  const gly = GUM_LINE_Y_BY_POSITION[position] ?? GUM_LINE_Y_BY_POSITION[1]",
    "  const vbW = VIEWBOX_W_BY_POSITION[position] ?? VIEWBOX_W_BY_POSITION[1] ?? 50\n  const gly = GUM_LINE_Y_BY_POSITION[position] ?? GUM_LINE_Y_BY_POSITION[1] ?? 97.5")
replace(path, ':site="siteByCode[code]"', ':site="siteByCode[code] ?? null"')
path = 'backend/app/modules/periodontogram/frontend/components/PeriodontogramView.vue'
replace(path,
    "    const last = timeline.value.dates[timeline.value.dates.length - 1]\n    await fetchSnapshot(last.snapshot_id)",
    "    const last = timeline.value.dates[timeline.value.dates.length - 1]\n    if (last) await fetchSnapshot(last.snapshot_id)")

# Recall literal union.
path = 'backend/app/modules/recalls/frontend/components/RecallSettingsPanel.vue'
replace(path,
    "import type { RecallSettings } from '../composables/useRecalls'",
    "import type { RecallReason, RecallSettings } from '../composables/useRecalls'")
replace(path, "const newCategoryReason = ref<string>('hygiene')", "const newCategoryReason = ref<RecallReason>('hygiene')")

# ISO date conversion returns a deterministic string.
for path in [
    'backend/app/modules/reports/frontend/pages/reports/billing.vue',
    'backend/app/modules/reports/frontend/pages/reports/budgets.vue'
]:
    p = Path(path)
    p.write_text(p.read_text().replace(".toISOString().split('T')[0]", ".toISOString().slice(0, 10)"))

# Schedules canonical type ownership and non-null UI form input.
path = 'backend/app/modules/schedules/frontend/components/WeeklyShiftGrid.vue'
replace(path,
    "  const padded = value.length === 5 ? `${value}:00` : value\n  current[index] = { ...current[index], [field]: padded }\n  updateDay(weekday, current)",
    "  const padded = value.length === 5 ? `${value}:00` : value\n  const shift = current[index]\n  if (!shift) return\n  current[index] = { ...shift, [field]: padded }\n  updateDay(weekday, current)")
path = 'backend/app/modules/schedules/frontend/components/settings/ProfessionalSchedulesPage.vue'
replace(path,
    "import type { ProfessionalHours, ProfessionalOverride, ProfessionalOverridePayload, WeekdayShifts } from '../../composables/useProfessionalHours'",
    "import type { ProfessionalHours, ProfessionalOverride, ProfessionalOverridePayload } from '../../composables/useProfessionalHours'\nimport type { WeekdayShifts } from '../../composables/useClinicHours'")
replace(path,
    "const overrideForm = ref<ProfessionalOverridePayload>({",
    "type ProfessionalOverrideForm = Omit<ProfessionalOverridePayload, 'reason'> & { reason: string }\nconst overrideForm = ref<ProfessionalOverrideForm>({")
path = 'backend/app/modules/schedules/frontend/components/settings/ClinicHoursPage.vue'
replace(path,
    "const overrideForm = ref<ClinicOverridePayload>({",
    "type ClinicOverrideForm = Omit<ClinicOverridePayload, 'reason'> & { reason: string }\nconst overrideForm = ref<ClinicOverrideForm>({")

# Treatment-plan stale UI assumptions.
path = 'backend/app/modules/treatment_plan/frontend/components/clinical/PlanTreatmentList.vue'
regex(path,
    r"  const clinicalType = item\.treatment\?\.clinical_type\n  if \(clinicalType === 'migrated' && item\.treatment\?\.notes\) \{.*?\n  \}\n  if \(clinicalType\) \{",
    """  const freeText = item.notes?.trim()
  if (freeText) return freeText.length > 60 ? `${freeText.slice(0, 60)}…` : freeText
  const clinicalType = item.treatment?.clinical_type
  if (clinicalType) {""", count=1)
replace('backend/app/modules/treatment_plan/frontend/components/clinical/PlansMode.vue',
    '@activate="fetchPatientPlans(patientId)"', '@activate="loadPatientPlans"')
path = 'backend/app/modules/treatment_plan/frontend/components/treatment-plans/TreatmentPlanMiniCard.vue'
p = Path(path)
text = p.read_text().replace("  cancelled: 'error',", "  pending: 'warning',\n  closed: 'error',")
p.write_text(text)
path = 'backend/app/modules/treatment_plan/frontend/components/treatment-plans/TreatmentPlanStatusBadge.vue'
p = Path(path)
text = p.read_text().replace("  cancelled: 'error'", "  pending: 'warning',\n  closed: 'error'")
p.write_text(text)
replace('backend/app/modules/treatment_plan/frontend/components/treatment-plans/TreatmentPlanModal.vue',
    ":ui=\"{ width: 'max-w-2xl' }\"", ":ui=\"{ content: 'sm:max-w-2xl' }\"")

# Verifactu symbol shadowing and semantic UI colors.
path = 'backend/app/modules/verifactu/frontend/components/verifactu/InvoiceVerifactuSlot.vue'
replace(path, 'const errorMessage = computed(', 'const recordErrorMessage = computed(')
replace(path, '{{ errorMessage }}', '{{ recordErrorMessage }}')
replace('backend/app/modules/verifactu/frontend/pages/settings/verifactu/queue.vue',
    "color: r.failed.length === 0 ? 'green' : 'amber'", "color: r.failed.length === 0 ? 'success' : 'warning'")
path = 'backend/app/modules/verifactu/frontend/pages/settings/verifactu/index.vue'
replace(path, "if (days < 0) return { color: 'error', message:", "if (days < 0) return { color: 'error' as const, message:")
path = 'backend/app/modules/verifactu/frontend/pages/settings/verifactu/vat-mapping.vue'
replace(path,
    "const AUTO_VALUE = '__auto__'\n\ninterface Row {\n  data: VatClassificationItem\n  selected: string",
    "const AUTO_VALUE = '__auto__' as const\ntype ClassificationValue = typeof CLASSIFICATIONS[number]['value']\ntype RowSelection = ClassificationValue | typeof AUTO_VALUE\n\ninterface Row {\n  data: VatClassificationItem\n  selected: RowSelection")
replace(path,
    "    selected: it.override_classification || AUTO_VALUE,",
    "    selected: (it.override_classification as ClassificationValue | null) || AUTO_VALUE,")

# Shared strict-index access.
path = 'frontend/app/components/shared/PatientSearch.vue'
replace(path,
    "      if (highlightedIndex.value >= 0 && patients.value[highlightedIndex.value]) {\n        selectPatient(patients.value[highlightedIndex.value])\n      }",
    "      if (highlightedIndex.value >= 0) {\n        const patient = patients.value[highlightedIndex.value]\n        if (patient) selectPatient(patient)\n      }")
path = 'frontend/app/components/shared/PlannedTreatmentSelector.vue'
replace(path,
    "  if (teeth.length === 1) {\n    const tooth = teeth[0]\n    const surfaces = (tooth.surfaces as string[] | undefined)?.join(', ')\n    return surfaces ? `#${tooth.tooth_number} (${surfaces})` : `#${tooth.tooth_number}`\n  }",
    "  if (teeth.length === 1) {\n    const tooth = teeth[0]\n    if (!tooth) return null\n    const surfaces = tooth.surfaces?.join(', ')\n    return surfaces ? `#${tooth.tooth_number} (${surfaces})` : `#${tooth.tooth_number}`\n  }")
