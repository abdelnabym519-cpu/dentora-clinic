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


types = 'frontend/app/types/index.ts'
p = Path(types)
text = p.read_text()
brief = """export interface BillingPatientBrief extends PatientBrief {
  billing_name?: string | null
  billing_tax_id?: string | null
  billing_address?: BillingAddress | null
  billing_email?: string | null
  has_complete_billing_info: boolean
}

"""
while text.count(brief) > 1:
    pos = text.rfind(brief)
    text = text[:pos] + text[pos + len(brief):]
p.write_text(text)

# Patients API nullability mirrors canonical Pydantic schemas.
replace(types,
    "  phone?: string\n  email?: string\n  date_of_birth?: string\n  notes?: string\n  status: 'active' | 'archived'",
    "  phone?: string | null\n  email?: string | null\n  date_of_birth?: string | null\n  notes?: string | null\n  status: 'active' | 'archived'")
replace(types,
    "  phone?: string\n  email?: string\n  date_of_birth?: string\n  notes?: string\n  do_not_contact?: boolean",
    "  phone?: string | null\n  email?: string | null\n  date_of_birth?: string | null\n  notes?: string | null\n  do_not_contact?: boolean")
replace(types,
    "  billing_name?: string\n  billing_tax_id?: string\n  billing_address?: PatientBillingAddress\n  billing_email?: string",
    "  billing_name?: string | null\n  billing_tax_id?: string | null\n  billing_address?: PatientBillingAddress | null\n  billing_email?: string | null")
replace(types,
    "export interface PatientBillingAddress {\n  street?: string\n  city?: string\n  postal_code?: string\n  province?: string\n  country?: string\n}",
    "export interface PatientBillingAddress {\n  street?: string | null\n  city?: string | null\n  postal_code?: string | null\n  province?: string | null\n  country?: string | null\n}")
replace(types,
    "export interface PatientAddress {\n  street?: string\n  city?: string\n  postal_code?: string\n  province?: string\n  country?: string\n}",
    "export interface PatientAddress {\n  street?: string | null\n  city?: string | null\n  postal_code?: string | null\n  province?: string | null\n  country?: string | null\n}")
replace(types,
    "  gender?: 'male' | 'female' | 'other' | 'prefer_not_say'\n  national_id?: string\n  national_id_type?: 'dni' | 'nie' | 'passport'\n  profession?: string\n  workplace?: string\n  preferred_language: string\n  address?: PatientAddress\n  photo_url?: string",
    "  gender?: 'male' | 'female' | 'other' | 'prefer_not_say' | null\n  national_id?: string | null\n  national_id_type?: 'dni' | 'nie' | 'passport' | null\n  profession?: string | null\n  workplace?: string | null\n  preferred_language: string\n  address?: PatientAddress | null\n  photo_url?: string | null")
replace(types,
    "  gender?: string\n  national_id?: string\n  national_id_type?: string\n  profession?: string\n  workplace?: string\n  preferred_language?: string\n  address?: PatientAddress\n  photo_url?: string",
    "  gender?: string | null\n  national_id?: string | null\n  national_id_type?: string | null\n  profession?: string | null\n  workplace?: string | null\n  preferred_language?: string | null\n  address?: PatientAddress | null\n  photo_url?: string | null")

# Agenda: PlannedTreatmentItem has no media collection.
replace('backend/app/modules/agenda/frontend/components/clinical/AppointmentModal.vue',
    "          : undefined,\n        media: []\n      }))",
    "          : undefined\n      }))")

# Billing response arrays are readonly; edit form owns a mutable copy.
replace('backend/app/modules/billing/frontend/components/billing/InvoiceItemModal.vue',
    '  form.surfaces = item.surfaces || []',
    '  form.surfaces = [...(item.surfaces ?? [])]')

# Budget's nested PatientBrief does not contain billing details. Fetch full patient.
path = 'backend/app/modules/billing/frontend/pages/invoices/from-budget/[budgetId].vue'
p = Path(path)
text = p.read_text()
fn = """function getCatalogItemName(item: BudgetItem): string {
  const names = item.catalog_item?.names
  if (!names) return item.catalog_item?.internal_code || ''
  return names[locale.value] || names.es || names.en || Object.values(names)[0] || item.catalog_item?.internal_code || ''
}

"""
while text.count(fn) > 1:
    pos = text.rfind(fn)
    text = text[:pos] + text[pos + len(fn):]
p.write_text(text)
replace(path,
    "import type { BudgetDetail, BudgetItem, InvoiceItemFromBudget, VatType } from '~~/app/types'",
    "import type { ApiResponse, BudgetDetail, BudgetItem, InvoiceItemFromBudget, Patient, VatType } from '~~/app/types'")
replace(path,
    "const budget = ref<BudgetDetail | null>(null)\nconst vatTypes = ref<VatType[]>([])",
    "const budget = ref<BudgetDetail | null>(null)\nconst billingPatient = ref<Patient | null>(null)\nconst vatTypes = ref<VatType[]>([])")
replace(path,
    "    budget.value = budgetData\n    vatTypes.value = vatResponse.data",
    "    budget.value = budgetData\n    vatTypes.value = vatResponse.data\n\n    if (budgetData?.patient?.id) {\n      const patientResponse = await api.get<ApiResponse<Patient>>(`/api/v1/patients/${budgetData.patient.id}`)\n      billingPatient.value = patientResponse.data\n    }")
replace(path, 'budget.patient.billing_name', 'billingPatient?.billing_name')
replace(path, 'budget.patient.billing_tax_id', 'billingPatient?.billing_tax_id')
replace(path, 'budget.patient.billing_email', 'billingPatient?.billing_email')
replace(path, 'budget.patient.billing_address.street', 'billingPatient?.billing_address?.street')
replace(path, 'budget.patient.billing_address.postal_code', 'billingPatient?.billing_address?.postal_code')
replace(path, 'budget.patient.billing_address.city', 'billingPatient?.billing_address?.city')
replace(path, 'budget.patient.billing_address', 'billingPatient?.billing_address')

# Catalog typed unions and payload construction.
path = 'backend/app/modules/catalog/frontend/components/catalog/CatalogItemModal.vue'
replace(path,
    "  TreatmentCatalogItemUpdate,\n  TreatmentCatalogItemCreate",
    "  TreatmentCatalogItemUpdate,\n  TreatmentCatalogItemCreate,\n  PricingStrategy")
replace(path,
    "} from '~~/app/config/odontogramConstants'",
    "} from '~~/app/config/odontogramConstants'\nimport type { TreatmentClinicalCategory, TreatmentType } from '~~/app/config/odontogramConstants'")
replace(path,
    "const odontogramType = ref<string | undefined>(undefined)\nconst clinicalCategory = ref<string | undefined>(undefined)",
    "const odontogramType = ref<TreatmentType | undefined>(undefined)\nconst clinicalCategory = ref<TreatmentClinicalCategory | undefined>(undefined)")
replace(path,
    "const scopeOptionsVisual = computed(() => [",
    "const scopeOptionsVisual = computed<Array<{ value: NonNullable<TreatmentCatalogItemUpdate['treatment_scope']>, label: string, icon: string }>>(() => [")
replace(path,
    "const strategyOptionsVisual = computed(() => [",
    "const strategyOptionsVisual = computed<Array<{ value: PricingStrategy, label: string, icon: string }>>(() => [")
replace(path,
    "        formData.value.surface_prices = {\n          1: base, 2: base, 3: base, 4: base, 5: base\n        } as unknown as Record<string, number>",
    "        formData.value.surface_prices = {\n          '1': base, '2': base, '3': base, '4': base, '5': base\n        }")
regex(path,
    r"function handleSubmit\(\) \{.*?\n\}\n\nfunction handleClose",
    """function handleSubmit() {
  if (!isValid.value) return

  const cleanData: TreatmentCatalogItemUpdate = { ...formData.value }
  if (odontogramType.value && clinicalCategory.value) {
    cleanData.odontogram_mapping = {
      odontogram_treatment_type: odontogramType.value,
      visualization_rules: getVisualizationRules(odontogramType.value),
      visualization_config: {},
      clinical_category: clinicalCategory.value
    }
  }
  cleanData.sessions = sessionsEnabled.value ? sessionsToPayload() : []

  if (isCreateMode.value) {
    const internalCode = cleanData.internal_code
    const categoryId = cleanData.category_id
    const names = cleanData.names
    if (!internalCode || !categoryId || !names) return
    emit('create', { ...cleanData, internal_code: internalCode, category_id: categoryId, names })
  } else {
    emit('save', cleanData)
  }
}

function handleClose""", count=1)
replace(path,
    "                    v-model.number=\"formData.default_price\"\n                    type=\"number\"",
    "                    :model-value=\"formData.default_price\"\n                    type=\"number\"\n                    @update:model-value=\"formData.default_price = Number($event)\"")
replace(path,
    "                    v-model.number=\"formData.cost_price\"\n                    type=\"number\"",
    "                    :model-value=\"formData.cost_price\"\n                    type=\"number\"\n                    @update:model-value=\"formData.cost_price = Number($event)\"")

# Typed payloads are valid object bodies in useApi.
replace('backend/app/modules/catalog/frontend/composables/useCatalog.ts',
    '        data as Record<string, unknown>', '        data')
path = 'backend/app/modules/catalog/frontend/composables/useTreatmentCatalog.ts'
replace(path,
    "    const treatments = treatmentsByCategory.value[categoryKey]\n    if (treatments && treatments.length > 0) {\n      return treatments[0].category_names[loc] || treatments[0].category_names.es || treatments[0].category_names.en || categoryKey\n    }",
    "    const first = treatmentsByCategory.value[categoryKey]?.[0]\n    if (first) {\n      return first.category_names[loc] || first.category_names.es || first.category_names.en || categoryKey\n    }")
path = 'backend/app/modules/catalog/frontend/composables/useVatTypes.ts'
replace(path,
    "      if (index !== -1) {\n        vatTypes.value[index] = { ...vatTypes.value[index], is_active: false }\n      }",
    "      const current = index !== -1 ? vatTypes.value[index] : undefined\n      if (current) {\n        vatTypes.value[index] = { ...current, is_active: false }\n      }")

# Web Headers API rather than dictionary cast.
path = 'backend/app/modules/media/frontend/composables/useDocuments.ts'
replace(path,
    "            if (options.headers) {\n              delete (options.headers as Record<string, string>)['Content-Type']\n            }",
    "            if (options.headers) {\n              const headers = new Headers(options.headers)\n              headers.delete('Content-Type')\n              options.headers = headers\n            }")

# Notification editable scalar fields and Nuxt UI v4 modal slot.
path = 'backend/app/modules/notifications/frontend/pages/settings/notifications.vue'
regex(path,
    r"function getSettingValue\(key: string, field: keyof NotificationTypeSettings\): boolean \| number \{.*?\n\}\n\nfunction updateLocalSetting\(key: string, field: keyof NotificationTypeSettings, value: boolean \| number\) \{.*?\n\}",
    """type EditableNotificationField = 'enabled' | 'auto_send' | 'hours_before'

function getSettingValue(key: string, field: EditableNotificationField): boolean | number {
  const setting = localSettings.value[key]
  if (!setting) return field === 'hours_before' ? 24 : false
  if (field === 'hours_before') return setting.hours_before ?? 24
  return setting[field]
}

function updateLocalSetting(key: string, field: EditableNotificationField, value: boolean | number) {
  const setting = localSettings.value[key]
  if (!setting) return
  if (field === 'hours_before') setting.hours_before = Number(value)
  else setting[field] = Boolean(value)
}""", count=1)
replace(path, ':ui="{ width: \'max-w-2xl\' }"', ':ui="{ content: \'sm:max-w-2xl\' }"')

# AdministrationTab consumes the treatment-plan relation exposed by list rows.
replace(types,
    "export interface BudgetListItem {\n  id: string\n  budget_number:",
    "export interface BudgetListItem {\n  id: string\n  treatment_plan_id?: string | null\n  budget_number:")
