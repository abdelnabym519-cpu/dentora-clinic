"""Egyptian (Arabic / `ar`) demo data overlay.

Added by the local-demo mission: gives the existing demo seeder a fully
Egyptian, obviously-fictional data set (Cairo clinic, Egyptian staff and
patient names, Egyptian-style fictional phone numbers, EGP / Africa-Cairo)
without touching the es/en/fr data in :mod:`app.seeds.demo_data`.

Design notes:

* Every dict here is an OVERLAY: :func:`app.seeds.demo_data.get_patients_data`
  (and the clinic/user getters) merge these fields over the English
  baseline when ``LANG == "ar"``, so any field omitted here falls back to
  English instead of crashing.
* Structural flags (``is_legal_guardian``, ``date_of_birth``, UUIDs, …)
  are intentionally NOT duplicated here — they are language-independent
  and are inherited from the base data at merge time.
* All names, phones, tax ids and addresses are fictional demo values and
  must not be mistaken for a real Egyptian clinic or real people.
* Module seeds that carry their own translations (catalog, clinical
  notes) fall back to English under ``ar``; this is a documented
  limitation, not a crash path.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Clinic — Dentora Demo Dental Clinic, Cairo, Egypt (fictional)
# -----------------------------------------------------------------------------

CLINIC_AR = {
    "name": "عيادة دنتورا التجريبية لطب الأسنان",
    "tax_id": "000-000-000",  # clearly fictional placeholder
    "address": {
        "street": "123 شارع الجمهورية",
        "city": "القاهرة",
        "postal_code": "11513",
        "country": "مصر",
    },
    "phone": "+20 2 2000 0000",  # fictional Cairo landline
    "currency": "EGP",
    "timezone": "Africa/Cairo",
}

# -----------------------------------------------------------------------------
# Staff — the four Egyptian demo professionals requested for the demo,
# keyed exactly like USERS_I18N in demo_data.py.
# -----------------------------------------------------------------------------

USERS_AR: dict[str, dict[str, str]] = {
    "admin": {"first_name": "مسؤول", "last_name": "الديمو"},
    "dentist": {"first_name": "أحمد", "last_name": "حسن"},
    "hygienist": {"first_name": "محمد", "last_name": "علي"},
    "assistant": {"first_name": "سارة", "last_name": "محمود"},
    "receptionist": {"first_name": "يوسف", "last_name": "عادل"},
}

# Egyptian-style fictional professional registry numbers (per role).
PROFESSIONAL_ID_AR = {
    "dentist": "م/12345",
    "hygienist": "م/54321",
}

# -----------------------------------------------------------------------------
# Patients — 15 fictional Egyptian patients, index-aligned with
# PATIENTS_I18N (same DOBs, same clinical archetypes, Arabic names).
# -----------------------------------------------------------------------------

PATIENTS_AR: list[dict] = [
    # [0] pediatric, first checkup (guardian: father)
    {
        "ar": {
            "first_name": "كريم",
            "last_name": "محمود",
            "notes": "مريض طفل. أول زيارة للفحص الدوري.",
        },
        "phone": "+20 100 000 0001",
        "emergency_contact": {
            "name": "محمود سعيد",
            "relationship": "الأب",
            "phone": "+20 100 000 0100",
            "email": "mahmoud.said@email.com",
        },
    },
    # [1] teen, orthodontics in progress (guardian: mother)
    {
        "ar": {
            "first_name": "مريم",
            "last_name": "عبد الرحمن",
            "notes": "علاج تقويم الأسنان قيد التنفيذ.",
        },
        "phone": "+20 100 000 0002",
        "emergency_contact": {
            "name": "هالة عبد الرحمن",
            "relationship": "الأم",
            "phone": "+20 100 000 0101",
            "email": "hala.abdelrahman@email.com",
        },
    },
    # [2] young adult, no notes (emergency: sister)
    {
        "ar": {
            "first_name": "يوسف",
            "last_name": "سامي",
            "notes": None,
        },
        "phone": "+20 100 000 0003",
        "emergency_contact": {
            "name": "دنا سامي",
            "relationship": "الأخت",
            "phone": "+20 100 000 0102",
            "email": None,
        },
    },
    # [3] dental sensitivity, anesthesia caution
    {
        "ar": {
            "first_name": "هبة",
            "last_name": "فؤاد",
            "notes": "حساسية في الأسنان. يُستخدم التخدير بحذر.",
        },
        "phone": "+20 100 000 0004",
        "emergency_contact": {
            "name": "وليد فؤاد",
            "relationship": "الزوج",
            "phone": "+20 100 000 0103",
            "email": "walid.fouad@email.com",
        },
    },
    # [4] adult, no notes (not a legal guardian situation)
    {
        "ar": {
            "first_name": "طارق",
            "last_name": "عزت",
            "notes": None,
        },
        "phone": "+20 100 000 0005",
        "emergency_contact": {
            "name": "شريف عزت",
            "relationship": "الأخ",
            "phone": "+20 100 000 0104",
            "email": None,
        },
    },
    # [5] pregnant, third trimester, avoid X-rays
    {
        "ar": {
            "first_name": "ندى",
            "last_name": "شريف",
            "notes": "حامل في الثلث الثالث. يُتجنب تصوير الأشعة.",
        },
        "phone": "+20 100 000 0006",
        "emergency_contact": {
            "name": "كريم شريف",
            "relationship": "الزوج",
            "phone": "+20 100 000 0105",
            "email": "karim.sherif@email.com",
        },
    },
    # [6] type 2 diabetic, monitor healing
    {
        "ar": {
            "first_name": "خالد",
            "last_name": "مصطفى",
            "notes": "مريض سكري من النوع الثاني. تتم مراقبة التئام الجروح.",
        },
        "phone": "+20 100 000 0007",
        "emergency_contact": {
            "name": "سناء مصطفى",
            "relationship": "الأخت",
            "phone": "+20 100 000 0106",
            "email": "sanaa.mustafa@email.com",
        },
    },
    # [7] adult, no notes
    {
        "ar": {
            "first_name": "منى",
            "last_name": "عصام",
            "notes": None,
        },
        "phone": "+20 100 000 0008",
        "emergency_contact": {
            "name": "هدى عصام",
            "relationship": "الأم",
            "phone": "+20 100 000 0107",
            "email": None,
        },
    },
    # [8] penicillin allergy
    {
        "ar": {
            "first_name": "عمر",
            "last_name": "حاتم",
            "notes": "حساسية من البنسلين.",
        },
        "phone": "+20 100 000 0009",
        "emergency_contact": {
            "name": "ريما حاتم",
            "relationship": "الزوجة",
            "phone": "+20 100 000 0108",
            "email": "reema.hatem@email.com",
        },
    },
    # [9] hypertensive, check blood pressure first
    {
        "ar": {
            "first_name": "سلمى",
            "last_name": "رمزي",
            "notes": "مصابة بارتفاع ضغط الدم. يُقاس الضغط قبل الإجراءات.",
        },
        "phone": "+20 100 000 0010",
        "emergency_contact": {
            "name": "أدهم رمزي",
            "relationship": "الابن",
            "phone": "+20 100 000 0109",
            "email": "adham.hamdy@email.com",
        },
    },
    # [10] upper partial denture
    {
        "ar": {
            "first_name": "فؤاد",
            "last_name": "رشدي",
            "notes": "طقم أسنان جزئي علوي.",
        },
        "phone": "+20 100 000 0011",
        "emergency_contact": {
            "name": "سعاد رشدي",
            "relationship": "الزوجة",
            "phone": "+20 100 000 0110",
            "email": None,
        },
    },
    # [11] implants, periodic review
    {
        "ar": {
            "first_name": "زينب",
            "last_name": "فهمي",
            "notes": "لها زراعة أسنان. مراجعة دورية.",
        },
        "phone": "+20 100 000 0012",
        "emergency_contact": {
            "name": "ليلى فهمي",
            "relationship": "الابنة",
            "phone": "+20 100 000 0111",
            "email": "laila.fahmy@email.com",
        },
    },
    # [12] blood thinners, coordinate before extractions
    {
        "ar": {
            "first_name": "إبراهيم",
            "last_name": "شكري",
            "notes": "يتناول مميعات الدم. التنسيق مع الطبيب قبل أي خلع.",
        },
        "phone": "+20 100 000 0013",
        "emergency_contact": {
            "name": "نعمت شكري",
            "relationship": "الزوجة",
            "phone": "+20 100 000 0112",
            "email": "nematt.shoukry@email.com",
        },
    },
    # [13] senior, no notes
    {
        "ar": {
            "first_name": "فريال",
            "last_name": "لطفي",
            "notes": None,
        },
        "phone": "+20 100 000 0014",
        "emergency_contact": {
            "name": "حسنين لطفي",
            "relationship": "الابن",
            "phone": "+20 100 000 0113",
            "email": None,
        },
    },
    # [14] complete denture, frequent adjustments
    {
        "ar": {
            "first_name": "محمود",
            "last_name": "الحديدي",
            "notes": "طقم أسنان كامل. يحتاج إلى تعديلات دورية.",
        },
        "phone": "+20 100 000 0015",
        "emergency_contact": {
            "name": "أمينة الحديدي",
            "relationship": "الزوجة",
            "phone": "+20 100 000 0114",
            "email": None,
        },
    },
]
