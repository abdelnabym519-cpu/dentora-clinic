"""Egypt-specific catalog overlay for the persistent DentalPin demo.

All prices are synthetic demo amounts in EGP and are not market quotations.
The commercial/default catalog remains unchanged unless this overlay is
explicitly requested by the Arabic Egypt demo seeder.
"""

from copy import deepcopy
from decimal import Decimal
from typing import Any

from app.seeds.egypt_catalog_ar import (
    SESSION_AR_LABELS,
    TREATMENT_AR_DESCRIPTIONS,
    TREATMENT_AR_NAMES,
    VAT_AR_NAMES,
)


CATEGORY_AR: dict[str, tuple[str, str]] = {
    "diagnostico": (
        "الكشف والتشخيص",
        "خدمات الكشف والتقييم والتشخيص",
    ),
    "preventivo": (
        "الوقاية وتنظيف الأسنان",
        "خدمات الوقاية والعناية بصحة الفم والأسنان",
    ),
    "restauradora": (
        "العلاج التحفظي والترميمي",
        "الحشوات وترميم الأسنان",
    ),
    "endodoncia": (
        "علاج الجذور",
        "علاجات عصب وجذور الأسنان",
    ),
    "periodoncia": (
        "علاج اللثة",
        "علاج اللثة والأنسجة الداعمة للأسنان",
    ),
    "cirugia": (
        "جراحة الفم والأسنان",
        "الإجراءات الجراحية وخلع الأسنان",
    ),
    "ortodoncia": (
        "تقويم الأسنان",
        "تقويم الأسنان وتصحيح الاصطفاف",
    ),
    "estetica": (
        "تجميل الأسنان",
        "خدمات تجميل وابتسامة الأسنان",
    ),
    "protesis": (
        "التركيبات والتعويضات",
        "التركيبات الثابتة والمتحركة",
    ),
    "pediatrica": (
        "أسنان الأطفال",
        "علاجات ووقاية أسنان الأطفال",
    ),
}


TREATMENT_OVERRIDES: dict[str, dict[str, Any]] = {
    "DX-VISIT": {
        "name_ar": "كشف وتشخيص أولي",
        "description_ar": "كشف أولي شامل مع الفحص والتشخيص",
        "default_price": Decimal("500.00"),
    },
    "DX-RXPAN": {
        "name_ar": "أشعة بانوراما",
        "description_ar": "أشعة بانورامية للفكين والأسنان",
        "default_price": Decimal("700.00"),
    },
    "PREV-CLEAN": {
        "name_ar": "تنظيف الأسنان",
        "description_ar": "جلسة تنظيف وإزالة الجير والعناية الوقائية",
        "default_price": Decimal("900.00"),
    },
    "REST-COMP": {
        "name_ar": "حشو تجميلي كومبوزيت",
        "description_ar": "حشو كومبوزيت بلون الأسنان",
        "default_price": Decimal("1200.00"),
    },
    "ENDO-MULTI": {
        "name_ar": "علاج جذور لضرس متعدد القنوات",
        "description_ar": "علاج جذور كامل لضرس متعدد القنوات",
        "default_price": Decimal("4500.00"),
        "sessions": [
            ("فتح العصب وتحديد أطوال القنوات", Decimal("1500.00")),
            ("تنظيف وتوسيع القنوات", Decimal("1500.00")),
            ("حشو القنوات وإنهاء علاج الجذور", Decimal("1500.00")),
        ],
    },
    "REST-CROWN-MC": {
        "name_ar": "تاج معدن-بورسلين",
        "description_ar": "تركيبة تاج معدن مغطى بالبورسلين",
        "default_price": Decimal("4500.00"),
        "sessions": [
            ("تحضير السن وأخذ المقاسات", Decimal("1500.00")),
            ("تجربة وتثبيت التاج النهائي", Decimal("3000.00")),
        ],
    },
    "REST-VEN-COMP": {
        "name_ar": "قشرة تجميلية كومبوزيت",
        "description_ar": "قشرة تجميلية مباشرة بالكومبوزيت",
        "default_price": Decimal("2500.00"),
    },
    "EST-BLAN-CLIN": {
        "name_ar": "تبييض أسنان داخل العيادة",
        "description_ar": "جلسة تبييض أسنان احترافية داخل العيادة",
        "default_price": Decimal("6000.00"),
    },
    "PERIO-RAR": {
        "name_ar": "تنظيف عميق وعلاج جذور الأسنان",
        "description_ar": "إزالة الجير العميق وتسوية أسطح الجذور",
        "default_price": Decimal("1800.00"),
    },
    "PROT-PART-METAL": {
        "name_ar": "طقم أسنان جزئي معدني",
        "description_ar": "تعويض جزئي متحرك بقاعدة معدنية",
        "default_price": Decimal("9000.00"),
    },
}


def apply_egypt_vat_overlay(source: dict[str, Any]) -> dict[str, Any]:
    """Return VAT definition with Arabic Egypt display name."""
    data = deepcopy(source)
    key = data.get("key")
    arabic = VAT_AR_NAMES.get(key)

    if arabic:
        data["names"] = {
            **data.get("names", {}),
            "ar": arabic,
        }

    return data


def apply_egypt_category_overlay(source: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied category with Arabic Egypt display values."""
    data = deepcopy(source)
    override = CATEGORY_AR.get(data.get("key"))

    if not override:
        return data

    name_ar, description_ar = override

    data["names"] = {
        **data.get("names", {}),
        "ar": name_ar,
    }

    data["descriptions"] = {
        **data.get("descriptions", {}),
        "ar": description_ar,
    }

    return data


def apply_egypt_treatment_overlay(source: dict[str, Any]) -> dict[str, Any]:
    """Return treatment localized for the persistent Egypt demo."""
    data = deepcopy(source)
    code = data.get("internal_code")

    # Full Arabic display localization for all catalog items.
    arabic_name = TREATMENT_AR_NAMES.get(code)

    if arabic_name:
        data["names"] = {
            **data.get("names", {}),
            "ar": arabic_name,
        }

    arabic_description = TREATMENT_AR_DESCRIPTIONS.get(code)

    if arabic_description:
        data["descriptions"] = {
            **data.get("descriptions", {}),
            "ar": arabic_description,
        }

    # Localize all multi-session labels without changing their default
    # commercial/demo prices unless a dedicated pricing override exists.
    sessions = data.get("sessions") or []

    for index, session in enumerate(sessions, start=1):
        arabic_label = SESSION_AR_LABELS.get((code, index))

        if arabic_label:
            session["labels"] = {
                **session.get("labels", {}),
                "ar": arabic_label,
            }

    # Pricing overrides exist only for selected Egypt demo journeys.
    override = TREATMENT_OVERRIDES.get(code)

    if not override:
        return data

    data["names"] = {
        **data.get("names", {}),
        "ar": override["name_ar"],
    }

    if "description_ar" in override:
        data["descriptions"] = {
            **data.get("descriptions", {}),
            "ar": override["description_ar"],
        }

    data["default_price"] = override["default_price"]

    session_overrides = override.get("sessions")

    if session_overrides:
        sessions = data.get("sessions") or []

        if len(sessions) != len(session_overrides):
            raise ValueError(
                f"Egypt demo session count mismatch for {code}"
            )

        for session, (label_ar, price) in zip(
            sessions,
            session_overrides,
        ):
            session["labels"] = {
                **session.get("labels", {}),
                "ar": label_ar,
            }
            session["default_price"] = price

    return data
