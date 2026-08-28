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
catalog.write_text(text)

dedupe_exact_imports('backend/app/modules/catalog/frontend/components/catalog/CatalogItemModal.vue')
dedupe_exact_imports('backend/app/modules/payments/frontend/components/PatientPaymentsPanel.vue')
