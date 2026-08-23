# Dentora — Auto Update

هذه المرحلة تضيف تحديثًا آمنًا للنسخة المحلية فقط، ولا تشمل Client Packaging أو أي Release Gate لاحق.

## نموذج الثقة

- يقرأ `UPDATE_DENTORA.bat` إعدادات التحديث من `.env.client`.
- يجب أن يكون `UPDATE_METADATA_URL` عبر HTTPS فقط.
- يجب حقن `UPDATE_PUBLIC_KEY_B64` كمفتاح Ed25519 عام مخصص للتحديثات.
- ملف metadata يحتوي descriptor ثابت الحقول + signature. أي حقل غير معروف يُرفض.
- يتم التحقق من توقيع الـdescriptor أولًا، ثم رفض downgrade/reinstall، ثم التحقق من حجم حزمة ZIP وSHA-256 الموقعين.
- لا يوجد command أو script field في metadata، لذلك لا يمكن لخادم التحديث تمرير أوامر تشغيل عشوائية.

## دورة التحديث

1. `UPDATE_DENTORA.bat --check` ينزل metadata والحزمة ويجري التحقق فقط دون تعديل التثبيت.
2. `UPDATE_DENTORA.bat` يبدأ apply كمسؤول Administrator.
3. يتم تنزيل الحزمة إلى staging مؤقت والتحقق منها بالكامل.
4. يتم رفض أي حزمة تحاول تضمين `.env.client` أو backups أو restore/update journals أو `.git`.
5. يُنشأ source snapshot محلي، ثم **نسخة احتياطية إلزامية** باستخدام `scripts/dentora_backup_restore.ps1` نفسه؛ لا يوجد Backup implementation مكرر.
6. بعد نجاح النسخة الاحتياطية فقط يُكتب `.dentora-update-journal.json` ثم تُطبق الملفات.
7. `docker compose up -d --build` يعيد بناء الخدمات؛ backend entrypoint ينفذ Alembic migrations المعتادة.
8. يتم فحص `/health` على `PUBLIC_URL` بدون تجاوز TLS.
9. عند النجاح يُحذف update journal. عند أي فشل بعد بدء mutation يتم استرجاع source snapshot ثم استدعاء Backup/Restore لاستعادة DB/storage ثم إعادة health check.

## الانقطاع والاسترداد

وجود `.dentora-update-journal.json` يجعل `START_DENTORA.bat` يفشل مغلقًا بدل تشغيل حالة مبهمة. شغّل كمسؤول:

`UPDATE_DENTORA.bat --recover`

الاسترداد idempotent من منظور المشغل: إذا لم يوجد journal فلن يغير شيئًا. إذا فشل rollback تبقى الحالة fail-closed ويجب عدم حذف الـjournal يدويًا.

## البيانات والأسرار

التحديث لا يستبدل `.env.client`، ولا يحذف Docker data volumes، ولا يقرأ أو يكتب `LICENSE_MACHINE_FINGERPRINT` أو كلمات مرور PostgreSQL داخل الـmetadata أو logs. Machine-bound license state يبقى مرتبطًا بالتثبيت الحالي. النسخة الاحتياطية والاسترجاع يحافظان على نفس سياسة License التي أغلقتها مرحلة Backup / Restore.

## خارج النطاق

Client Packaging، Documentation/Handover الشامل، وFinal Release Gate مراحل لاحقة وغير منفذة هنا.
