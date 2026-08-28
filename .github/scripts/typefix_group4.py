from pathlib import Path


def dedupe_exact_imports(path: str) -> None:
    p = Path(path)
    lines = p.read_text().splitlines(keepends=True)
    seen_imports: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line.startswith('import ') and line in seen_imports:
            continue
        if line.startswith('import '):
            seen_imports.add(line)
        out.append(line)
    p.write_text(''.join(out))


catalog = Path('backend/app/modules/catalog/frontend/components/catalog/CatalogItemModal.vue')
text = catalog.read_text()
while '  PricingStrategy,\n  PricingStrategy' in text:
    text = text.replace('  PricingStrategy,\n  PricingStrategy', '  PricingStrategy')
config_import = "import type { TreatmentClinicalCategory, TreatmentType } from '~~/app/config/odontogramConstants'\n"
while text.count(config_import) > 1:
    first = text.find(config_import)
    second = text.find(config_import, first + len(config_import))
    text = text[:second] + text[second + len(config_import):]
text = text.replace(
    "          '1': base, '2': base, '3': base, '4': base, '5': base\n",
    "          1: base, 2: base, 3: base, 4: base, 5: base\n",
)
catalog.write_text(text)

dedupe_exact_imports('backend/app/modules/catalog/frontend/components/catalog/CatalogItemModal.vue')
dedupe_exact_imports('backend/app/modules/payments/frontend/components/PatientPaymentsPanel.vue')


tooth_dual_view = Path('backend/app/modules/odontogram/frontend/components/odontogram/ToothDualView.vue')
text = tooth_dual_view.read_text()
text = text.replace('  TREATMENT_COLORS,\n', '')
tooth_dual_view.write_text(text)


clinical_tab = Path('backend/app/modules/patients/frontend/components/patient/ClinicalTab.vue')
text = clinical_tab.read_text()
text = text.replace(
    "type ClinicalMode = 'history' | 'diagnosis' | 'plans' | 'appointments'\n"
    "import type { TreatmentPlan } from '~~/app/types'\n"
    "import { PERMISSIONS } from '~~/app/config/permissions'\n",
    "import type { TreatmentPlan } from '~~/app/types'\n"
    "import { PERMISSIONS } from '~~/app/config/permissions'\n\n"
    "type ClinicalMode = 'history' | 'diagnosis' | 'plans' | 'appointments'\n",
)
clinical_tab.write_text(text)


patient_section_modal = Path('backend/app/modules/patients/frontend/components/patient/PatientSectionEditModal.vue')
text = patient_section_modal.read_text()
text = text.replace('  MedicalHistory,\n} from \'~~/app/types\'\n', '  MedicalHistory\n} from \'~~/app/types\'\n')
patient_section_modal.write_text(text)


verifactu_slot = Path('backend/app/modules/verifactu/frontend/components/verifactu/InvoiceVerifactuSlot.vue')
text = verifactu_slot.read_text()
text = text.replace(
    "const recordErrorMessage = computed(\n"
    "  () =>\n"
    "    liveRecord.value?.aeat_descripcion_error\n"
    "    ?? (es.value?.error_message as string | undefined)\n"
    "    ?? null\n"
    ")\n\n",
    '',
)
verifactu_slot.write_text(text)
