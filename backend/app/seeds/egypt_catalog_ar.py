"""Arabic display data for the persistent Egypt demo catalog.

This module changes display localization only.
Pricing remains controlled separately by egypt_catalog.py.
"""

VAT_AR_NAMES = {
    "exempt": "معفى",
    "reduced": "مخفض (10%)",
    "standard": "قياسي (21%)",
}


TREATMENT_AR_NAMES = {
    # Diagnosis
    "DX-VISIT": "كشف وتشخيص أولي",
    "DX-REVIEW": "زيارة متابعة",
    "DX-RXPA": "أشعة حول ذروية",
    "DX-RXPAN": "أشعة بانوراما",
    "DX-CBCT": "أشعة مقطعية ثلاثية الأبعاد CBCT",
    "DX-STUDY": "دراسة تقويم الأسنان",
    "DX-PHOTO": "صور داخل الفم",
    "DX-URGENT": "زيارة طوارئ",
    "DX-2ND-OPINION": "رأي طبي ثانٍ",
    "DX-TELE": "أشعة سيفالومترية جانبية",

    # Preventive
    "PREV-CLEAN": "تنظيف الأسنان",
    "PREV-FLUOR": "تطبيق فلورايد",
    "PREV-CHECKUP": "فحص دوري",
    "PREV-SEAL": "سد الشقوق والحفر الوقائي",
    "PREV-HYGIENE-EDU": "تعليمات العناية بصحة الفم",
    "PREV-CLEAN-CURETTAGE": "إزالة الجير مع كحت لثوي",
    "PREV-CLEAN-PED": "تنظيف وقائي لأسنان الأطفال",

    # Restorative
    "REST-COMP": "حشو تجميلي كومبوزيت",
    "REST-AMAL": "حشو أملغم",
    "REST-TEMP": "حشو مؤقت",
    "REST-INLAY-COMP": "إنلاي كومبوزيت",
    "REST-INLAY-CER": "إنلاي سيراميك",
    "REST-OVER-COMP": "أونلاي كومبوزيت",
    "REST-OVER-CER": "أونلاي سيراميك",
    "REST-VEN-COMP": "قشرة تجميلية كومبوزيت",
    "REST-VEN-PORC": "قشرة خزفية",
    "REST-VEN-ZIR": "قشرة زيركون",
    "REST-CROWN-MC": "تاج معدن-بورسلين",
    "REST-CROWN-ZIR": "تاج زيركون",
    "REST-CROWN-DISI": "تاج ليثيوم ديسيليكات",
    "REST-CROWN-METAL": "تاج معدني",
    "REST-CROWN-PROV": "تاج مؤقت",
    "REST-CROWN-IMPL-MC": "تاج معدن-بورسلين على زرعة",
    "REST-CROWN-IMPL-ZIR": "تاج زيركون على زرعة",
    "REST-CROWN-IMPL-PROV": "تاج مؤقت على زرعة",
    "REST-BRIDGE-MC": "جسر معدن-بورسلين",
    "REST-BRIDGE-ZIR": "جسر زيركون",
    "REST-BRIDGE-MARY": "جسر ماريلاند",
    "REST-SPLINT-OCC": "واقي إطباقي",
    "REST-SPLINT-PERIO": "جبيرة تثبيت لثوية",
    "REST-RECONSTR": "إعادة بناء كبيرة بالكومبوزيت",
    "REST-FILL-REPAIR": "إصلاح حشو",
    "REST-CROWN-RECEMENT": "إعادة تثبيت تاج",
    "REST-CROWN-POST-ENDO": "تاج لسن معالج جذور",
    "REST-HEAL-ABUT": "دعامة شفاء",
    "REST-DEF-ABUT": "دعامة نهائية",

    # Endodontics
    "ENDO-UNI": "علاج جذور لسن أحادي الجذر",
    "ENDO-BI": "علاج جذور لسن ثنائي الجذور",
    "ENDO-MULTI": "علاج جذور لضرس متعدد القنوات",
    "ENDO-RETREAT": "إعادة علاج جذور",
    "ENDO-POST-FIBER": "وتد ألياف",
    "ENDO-POST-METAL": "وتد معدني مصبوب",
    "ENDO-URGENT": "فتح حجرة العصب بشكل عاجل",
    "ENDO-MED-REFRESH": "تغيير دواء داخل القنوات",
    "ENDO-APICOFORM": "إغلاق ذروي تحفيزي",
    "ENDO-PED": "علاج جذور لسن لبني",

    # Periodontics
    "PERIO-SCAL": "إزالة جير بسيطة",
    "PERIO-RAR": "تنظيف عميق وتسوية الجذور لكل ربع",
    "PERIO-SURG": "جراحة لثوية",
    "PERIO-GRAFT": "ترقيع لثوي",
    "PERIO-BONE": "تجديد عظمي موجه",
    "PERIO-MAINT": "صيانة لثوية دورية",
    "PERIO-CURET-SEXT": "كحت لثوي لكل سدس",
    "PERIO-STUDY": "فحص وقياسات دواعم الأسنان",
    "PERIO-SPLINT-RAR": "جبيرة تثبيت بعد التنظيف العميق",
    "PERIO-GINGIV": "استئصال لثة",
    "PERIO-SURG-RESECT": "جراحة لثوية استئصالية",
    "PERIO-SURG-REGEN": "جراحة لثوية تجديدية",

    # Surgery
    "SURG-EXT-SIMPLE": "خلع بسيط",
    "SURG-EXT-COMPLEX": "خلع جراحي معقد",
    "SURG-EXT-3MOLAR": "خلع ضرس عقل",
    "SURG-EXT-OST": "خلع جراحي مع إزالة عظم",
    "SURG-IMP-TI": "زرعة تيتانيوم",
    "SURG-IMP-ZIR": "زرعة زيركون",
    "SURG-SINUS": "رفع الجيب الأنفي",
    "SURG-BONE-GRAFT": "ترقيع عظمي",
    "SURG-APEC": "استئصال ذروة الجذر",
    "SURG-FREN": "استئصال اللجام",
    "SURG-BIOPSY": "خزعة",
    "SURG-CONN-GRAFT": "ترقيع نسيج ضام",
    "SURG-CROWN-LENGTH": "إطالة تاج السن",
    "SURG-CYST": "استئصال كيس",
    "SURG-EXT-INCLUIDO": "خلع سن مطمور",
    "SURG-BONE-REGUL": "تسوية وإعادة تشكيل العظم",
    "SURG-PRP": "بلازما غنية بالصفائح الدموية",
    "SURG-PERIIMP": "علاج التهاب حول الزرعة",
    "SURG-BONE-VERT": "زيادة عظم رأسية",
    "SURG-BONE-HORIZ": "زيادة عظم أفقية",
    "SURG-SINUS-CLOSED": "رفع جيب أنفي مغلق",

    # Orthodontics
    "ORTO-METAL": "تقويم معدني",
    "ORTO-CERAM": "تقويم خزفي",
    "ORTO-LINGUAL": "تقويم لساني",
    "ORTO-INV-LITE": "إنفزلاين لايت",
    "ORTO-INV-FULL": "إنفزلاين كامل",
    "ORTO-BRACK": "استبدال حاصرة تقويم",
    "ORTO-REVIEW": "مراجعة تقويم",
    "ORTO-RET-FIX": "مثبت تقويم ثابت",
    "ORTO-RET-REM": "مثبت تقويم متحرك",
    "ORTO-ATTACH": "ملحقات إنفزلاين",
    "ORTO-BRACK-CEMENT": "تثبيت حاصرات التقويم",
    "ORTO-BRACK-DEBOND": "إزالة حاصرات التقويم",
    "ORTO-SEPARATOR": "فواصل تقويم",
    "ORTO-PALATAL-EXP": "موسع حنكي",
    "ORTO-TAD": "مسمار تثبيت تقويمي مؤقت TAD",

    # Cosmetic
    "EST-BLAN-AMB": "تبييض منزلي",
    "EST-BLAN-CLIN": "تبييض داخل العيادة",
    "EST-BLAN-COMBO": "تبييض مشترك منزلي وعيادي",
    "EST-MICROAB": "كشط دقيق للمينا",
    "EST-REMIN": "إعادة تمعدن تجميلية",
    "EST-COMP-AESTH": "إعادة بناء تجميلية بالكومبوزيت",
    "EST-PIG-REMOVE": "إزالة التصبغات",

    # Prosthetics
    "PROT-FULL-SUP": "طقم أسنان كامل علوي",
    "PROT-FULL-INF": "طقم أسنان كامل سفلي",
    "PROT-PART-METAL": "طقم أسنان جزئي معدني",
    "PROT-PART-ACR": "طقم أسنان جزئي أكريليك",
    "PROT-OVERDENT": "طقم متحرك مدعوم بالزرعات",
    "PROT-REBASE": "إعادة تبطين طقم الأسنان",
    "PROT-REPAIR": "إصلاح طقم الأسنان",
    "PROT-PROV-REMOV": "طقم مؤقت متحرك",
    "PROT-OCC-ADJ": "ضبط الإطباق",

    # Pediatric
    "PED-FLUOR": "فلورايد للأطفال",
    "PED-SEAL": "سد شقوق وقائي للأطفال",
    "PED-PULPOTOMY": "بتر لب",
    "PED-CROWN-SS": "تاج ستانلس ستيل",
    "PED-SPACE": "حافظ مسافة بسيط",
    "PED-SPACE-COMPOUND": "حافظ مسافة مركب",
    "PED-EXT-TEMP": "خلع سن لبني",
    "PED-FILL-TEMP": "حشو سن لبني",
    "PED-PULPECTOMY": "استئصال لب لسن لبني",
}


TREATMENT_AR_DESCRIPTIONS = {
    "DX-VISIT": "كشف أولي شامل مع الفحص والتشخيص",
    "PREV-CLEAN": "إزالة الجير وتلميع الأسنان",
    "PREV-CHECKUP": "فحص دوري عام للأسنان واللثة",
}


SESSION_AR_LABELS = {
    ("REST-CROWN-MC", 1): "أخذ المقاسات",
    ("REST-CROWN-MC", 2): "تثبيت التاج",

    ("REST-CROWN-ZIR", 1): "أخذ المقاسات",
    ("REST-CROWN-ZIR", 2): "تثبيت التاج",

    ("REST-CROWN-DISI", 1): "أخذ المقاسات",
    ("REST-CROWN-DISI", 2): "تثبيت التاج",

    ("REST-CROWN-IMPL-MC", 1): "أخذ المقاسات",
    ("REST-CROWN-IMPL-MC", 2): "تركيب التاج",

    ("REST-CROWN-IMPL-ZIR", 1): "أخذ المقاسات",
    ("REST-CROWN-IMPL-ZIR", 2): "تركيب التاج",

    ("ENDO-MULTI", 1): "فتح العصب وتحديد أطوال القنوات",
    ("ENDO-MULTI", 2): "تنظيف وتوسيع القنوات",
    ("ENDO-MULTI", 3): "حشو القنوات",

    ("SURG-IMP-TI", 1): "جراحة تركيب الزرعة",
    ("SURG-IMP-TI", 2): "تركيب دعامة الشفاء",
    ("SURG-IMP-TI", 3): "تركيب التاج",
}
