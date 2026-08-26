# Dentora — إعداد أجهزة العمل داخل العيادة

هذا الدليل خاص بأجهزة الاستقبال والأطباء التي ستفتح Dentora من الـMini PC داخل شبكة العيادة. جهاز العمل لا يشغّل قاعدة بيانات أو Backend أو Docker، ولا يحتاج نسخة من `.env.client` أو مفاتيح الترخيص أو أي Secrets.

## قبل البدء

يجب أن تكون مرحلة Mini PC / LAN / HTTPS مكتملة على جهاز السيرفر، وأن يكون Dentora يعمل بعنوان ثابت على HTTPS مثل:

```text
https://192.168.1.50
```

يجب كذلك أن يكون ملف `dentora-lan-ca.crt` قد تم إنشاؤه على الـMini PC بواسطة `SETUP_LAN_HTTPS.bat`.

## تجهيز حزمة أجهزة العمل على الـMini PC

من مجلد Dentora على الـMini PC شغّل:

```bat
PREPARE_WORKSTATION_KIT.bat
```

ينشئ السكريبت مجلدًا محليًا باسم:

```text
Dentora_Workstation_Kit
```

ويضع داخله فقط الملفات اللازمة لإعداد جهاز العمل:

- `SETUP_DENTORA_WORKSTATION.bat`
- `dentora-lan-ca.crt`
- `dentora-workstation.conf`
- `WORKSTATION_SETUP_AR.md`

ملف `dentora-workstation.conf` يحتوي عنوان Dentora على الشبكة وSHA-256 لشهادة الـCA حتى يرفض جهاز العمل شهادة تالفة أو غير مطابقة للحزمة.

لا تحتوي الحزمة على `.env.client` أو كلمة مرور PostgreSQL أو مفاتيح خاصة أو بيانات مرضى.

## إعداد كل جهاز عمل

1. انسخ مجلد `Dentora_Workstation_Kit` كاملًا من الـMini PC إلى جهاز العمل باستخدام وسيلة موثوقة داخل العيادة.
2. تأكد أن الجهاز متصل بنفس شبكة العيادة ويمكنه الوصول إلى عنوان الـMini PC الثابت.
3. اضغط بزر الفأرة الأيمن على `SETUP_DENTORA_WORKSTATION.bat` واختر **Run as administrator**.
4. السكريبت يتحقق تلقائيًا من أن عنوان السيرفر HTTPS ويستخدم IPv4 خاصًا من RFC1918، ويتحقق من SHA-256 لشهادة الـCA ومن صلاحيتها.
5. قبل تعديل Trust Store يتحقق السكريبت من الوصول إلى الـMini PC على TCP 443.
6. بعد ذلك يثبت شهادة Dentora المحلية في `LocalMachine\Root` حتى تثق تطبيقات Windows بالاتصال الداخلي.
7. يتحقق من `https://<Mini-PC-IP>/health` بدون أي certificate bypass.
8. ينشئ Shortcut باسم **Dentora Clinic** على Public Desktop ليظهر لجميع مستخدمي هذا الجهاز.
9. يفتح Dentora في المتصفح الافتراضي بعد نجاح التحقق.

## ما الذي لا يحتاجه جهاز العمل؟

جهاز الاستقبال أو الطبيب لا يحتاج إلى:

- Docker Desktop.
- PostgreSQL.
- ملفات Backend أو Frontend محلية.
- `.env.client`.
- License private key.
- OpenAI/API provider keys.
- نسخة محلية من قاعدة بيانات العيادة.

كل البيانات والخدمات تظل على الـMini PC، وجهاز العمل يستخدم HTTPS فقط عبر شبكة العيادة.

## التحقق بعد الإعداد

الإعداد يعتبر ناجحًا فقط عندما ينتهي السكريبت برسالة `Workstation setup completed successfully` ويكون فحص HTTPS health قد نجح. افتح Shortcut **Dentora Clinic** وتأكد أن المتصفح لا يعرض تحذير شهادة وأن صفحة Dentora تفتح على نفس عنوان الـMini PC الثابت.

إذا فشل الوصول إلى TCP 443، تحقق من اتصال الجهاز بنفس LAN ومن تشغيل Dentora على الـMini PC ومن بقاء عنوانه الثابت كما هو. إذا ظهر خطأ SHA-256 أو شهادة، لا تستخدم bypass ولا تتجاهل التحذير؛ أعد تشغيل `PREPARE_WORKSTATION_KIT.bat` على الـMini PC وانسخ الحزمة كاملة من جديد.

## حدود هذه المرحلة

Workstation Setup تجهز الثقة والوصول الآمن والاختصار على أجهزة الاستقبال/الأطباء فقط. لا تنفذ Backup / Restore، ولا تغيّر Docker volumes أو قاعدة البيانات أو إعدادات الترخيص على الـMini PC.
