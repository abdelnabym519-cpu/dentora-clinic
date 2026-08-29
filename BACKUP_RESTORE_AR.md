# Dentora — Backup / Restore للنسخة المحلية

هذا المستند يصف سلوك النسخ الاحتياطي والاستعادة والتعافي التشغيلي للنسخة المحلية المرخصة من Dentora على Windows/Mini PC ضمن تسليم العميل النهائي.

## ما الذي يتم نسخه؟

نسخة Dentora القياسية على الـMini PC لديها مصدران دائمـان لبيانات العيادة:

1. PostgreSQL — كل بيانات النظام والموديولات الموجودة في قاعدة البيانات.
2. `/app/storage` — الملفات المرفوعة وحالة التخزين المحلية للموديولات.

ينشئ `BACKUP_DENTORA.bat` ملف ZIP واحدًا داخل `backups`، ويحتوي فقط على:

- `database.dump` — PostgreSQL custom-format dump.
- `storage.tar` — محتوى التخزين المحلي المطلوب للاستعادة.
- `manifest.json` — هوية النسخة، وقت الإنشاء UTC، إصدار Dentora، Alembic schema revision، أحجام الملفات وSHA-256 checksums ومصدر البيانات العام غير الحساس.

صيغة الـbackup الحالية هي `dentora-backup` بالإصدار `1`.

## ما الذي لا يتم نسخه ولماذا؟

لا يتم وضع `.env.client` داخل الـbackup. لذلك لا يتم نسخ كلمات مرور PostgreSQL أو `SECRET_KEY` أو مفاتيح الخدمة أو machine fingerprint إلى artifact يمكن نقله.

مجلد `/app/storage/license` مستبعد أيضًا من `storage.tar`. يحتوي هذا المسار على `installation_id.txt` و`lease.json`، والـlease موقع رقميًا ومقيد بالجهاز ويُستخدم كحالة ترخيص محلية. أثناء Restore يتم الحفاظ على حالة الترخيص الحالية الموجودة على الجهاز الهدف ونسخها إلى storage volume الجديد بدل قبول حالة ترخيص قادمة من Backup غير موثوق. لذلك:

- Restore على نفس الـMini PC يحافظ على حالة ترخيص التثبيت الحالي.
- Restore على جهاز بديل يتطلب تجهيز الجهاز وتفعيله بطريقة صحيحة أولًا؛ الـbackup لا ينقل هوية الترخيص أو أسرار جهاز آخر.

Caddy PKI، إعدادات LAN/HTTPS، machine fingerprint، Docker configuration و`.env.client` هي حالة تثبيت/بنية تحتية وليست بيانات Backup قابلة للنقل، ولذلك تظل كما هي على الجهاز الهدف.

## إنشاء Backup

شغّل `BACKUP_DENTORA.bat` من Terminal بصلاحية Administrator بينما Dentora يعمل.

عملية Backup تقوم بالآتي:

1. تمنع تشغيل Backup أو Restore آخر في نفس الوقت بواسطة Windows named mutex.
2. تتحقق من Docker ومن إعداد Local Storage ومن أن PostgreSQL يعمل.
3. تتحقق أن قاعدة البيانات على Alembic head الحالي المثبت.
4. توقف خدمات التطبيق التي كانت تعمل مؤقتًا لمنع الكتابة أثناء أخذ snapshot متعدد المكونات، مع إبقاء PostgreSQL متاحًا للـdump.
5. تنشئ `pg_dump -Fc` وتتحقق منه بواسطة `pg_restore --list` قبل اعتماده.
6. تنشئ `storage.tar` مع استبعاد `storage/license`.
7. تنشئ `manifest.json` وتحسب SHA-256 والأحجام وتتحقق من سلامة tar paths وعدم وجود symlinks أو path traversal.
8. تنشئ ZIP أولًا باسم `.partial`، وتتحقق من بنيته، ثم تنقله للاسم النهائي فقط بعد النجاح الكامل.
9. تنظف staging files وتعيد فقط خدمات التطبيق التي كانت تعمل قبل بدء العملية.

ملف نهائي موجود مسبقًا لا يتم overwrite له. كل Backup يحصل على معرف فريد واسم جديد.

## حماية ملفات Backup

المجلد `backups` يحتوي بيانات مرضى حساسة. Dentora يقيد ACL الخاصة به إلى Windows `SYSTEM` و`Administrators` عند إنشاء Backup. لا ترفع ملفات Backup إلى Git أو بريد إلكتروني أو storage عام.

إذا احتجت إخراج النسخة من الجهاز، استخدم وسيطًا أو قرصًا مشفرًا ومقيد الوصول مثل BitLocker-managed storage. لا يضيف Dentora كلمة مرور ضعيفة إلى ZIP ولا يخزن encryption key بجوار الـbackup.

## Restore آمن

الاستخدام:

```bat
RESTORE_DENTORA.bat "C:\Dentora\backups\dentora-YYYYMMDDTHHMMSSZ-xxxxxxxx.zip"
```

Restore يتطلب Administrator وDentora يعمل بكامل خدماته قبل البداية. قبل أي تعديل على البيانات:

1. يفحص بنية ZIP ويقبل الملفات الثلاثة المعروفة فقط؛ لا يسمح بمسارات مطلقة أو path traversal أو ملفات إضافية.
2. يتحقق من `manifest.json`، format version، إصدار التطبيق، Alembic schema revision، الأحجام وSHA-256.
3. يتحقق من `storage.tar` ومنع الروابط والمسارات غير الآمنة وحالة license القادمة من artifact.
4. يشغّل `pg_restore --list` على dump قبل أي تغيير.
5. ينشئ **Pre-Restore Safety Backup** كاملًا للحالة الحالية. إذا لم ينجح، لا يبدأ Restore.

بعد هذه البوابة فقط:

1. تُستعاد قاعدة البيانات إلى temporary database جديد، وليس فوق قاعدة البيانات الحية.
2. يتم التحقق من Alembic revision داخل قاعدة البيانات المؤقتة.
3. يتم إنشاء Docker storage volume جديد، ويستخرج `storage.tar` داخله.
4. تُنسخ حالة `/app/storage/license` الحالية من الجهاز إلى الـvolume الجديد، ولا تؤخذ من الـbackup.
5. يتم تبديل قاعدة البيانات بالـrename بعد تجهيز النسخة المؤقتة بالكامل، مع الاحتفاظ بقاعدة البيانات السابقة كـrollback database أثناء مرحلة التحقق.
6. يتم تغيير `DENTORA_STORAGE_VOLUME` atomically إلى الـvolume الجديد.
7. يعاد إنشاء خدمات التطبيق ثم يتم فحص `PUBLIC_URL/health` باستخدام TLS validation العادي، بدون certificate bypass.
8. بعد Health PASS فقط تعتبر العملية committed، ثم يتم حذف rollback database. الـstorage volume السابق يبقى موجودًا كحماية إضافية من الحذف الصامت، إضافة إلى Safety Backup.

النتيجة تكون واحدة فقط:

- `Restore succeeded`
- أو `Restore failed safely`

## Failure / rollback / interruption

Restore يستخدم `.dentora-restore-journal.json` غير المحتوي على secrets لتسجيل أسماء قواعد البيانات والـvolumes ومرحلة التبديل. لا يحتوي journal على كلمات مرور أو tokens أو محتوى `.env.client`.

إذا حدث failure عادي بعد بدء التغيير، يحاول Dentora تلقائيًا:

- إرجاع `DENTORA_STORAGE_VOLUME` للـvolume السابق.
- إعادة قاعدة البيانات السابقة إلى اسمها الحي إذا تم التبديل.
- حذف temporary database.
- إزالة restore volume غير المعتمد حيثما أمكن.
- إعادة إنشاء الخدمات التي كانت تعمل.

إذا انقطع PowerShell أو الجهاز في منتصف المرحلة الحرجة، يبقى journal. `START_DENTORA.bat` يرفض بدء النظام في هذه الحالة حتى لا يعمل Dentora على حالة ambiguous. نفّذ:

```bat
RESTORE_DENTORA.bat --recover
```

Recovery يقرأ journal ويفضل rollback إلى آخر حالة مؤكدة ما لم تكن العملية قد وصلت بالفعل إلى `committed`.

## التوافق

الإصدار الحالي fail-closed ويقبل Restore فقط عندما:

- Backup format = `dentora-backup` v1.
- `app_version` يطابق الإصدار المثبت بالضبط.
- `schema_revision` يطابق Alembic head المثبت بالضبط.
- Local storage backend هو المسار المدعوم لنسخة العميل.

لا يقوم Restore بترقية Backup قديم ضمنيًا ولا يحاول تخمين migration path أثناء عملية استعادة حرجة. أي دعم لاحق لتحويل Backup بين إصدارات يجب أن يكون feature منفصلًا ومختبرًا.

## Retention وcleanup

لا يحذف Dentora ملفات Backup النهائية تلقائيًا؛ لا توجد retention policy سابقة في architecture الحالية، وإضافة حذف تلقائي قد تسبب فقد بيانات غير مقصود. staging files و`.partial` files وtemporary databases يتم تنظيفها آليًا، بينما Backup النهائي وprevious storage volume لا يتم حذفهما صامتًا بعد Restore ناجح.

ضع سياسة تشغيلية للاحتفاظ بعدد مناسب من النسخ على تخزين مشفر، واحذف النسخ القديمة فقط بعد التحقق من وجود نسخ أحدث صالحة.

## حدود Backup / Restore

Backup لا ينقل أسرار التثبيت أو هوية الترخيص أو إعداد LAN/HTTPS، ولا يحول schema
بين إصدارات مختلفة. تغيير الإصدار يقع خارج نطاق Backup / Restore نفسه وتديره آلية
Auto Update الموثقة في `AUTO_UPDATE_AR.md`. راجع `CLIENT_HANDOFF_AR.md` لخطة التعافي
الكاملة ومسؤوليات التشغيل.
