# DentalPin — تثبيت نسخة العميل على Windows

هذه النسخة مخصصة للتشغيل المحلي على كمبيوتر العيادة باستخدام Docker Desktop.

## ما يميز نسخة العميل

- تشغيل Production وليس Dev Server.
- بدون Trial: `TRIAL_MODE=false`.
- بدون بيانات Demo: `SEED_ON_STARTUP=0`.
- قاعدة PostgreSQL وملفات الأشعة/المرفقات محفوظة في Docker volumes دائمة.
- أول تشغيل يفتح شاشة إعداد الحساب الأول والعيادة.
- إعدادات Dental Care Clinic المصرية تطبق عبر `SET_CLIENT_PROFILE.bat`.
- تشغيل وإيقاف ونسخ احتياطي من ملفات BAT بدون أوامر يومية.

## المتطلبات

1. Windows 10/11 64-bit.
2. Docker Desktop مثبت ويعمل بوضع Linux containers / WSL2.
3. يفضل 8 GB RAM على الأقل، و16 GB أفضل.
4. مساحة خالية مناسبة لقاعدة البيانات والملفات.
5. اتصال إنترنت في أول Build لتنزيل Docker images وdependencies.

## قبل نقل النسخة للعميل

من Git Bash داخل مجلد المشروع:

```bash
cp .env.client.example .env.client

POSTGRES_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
BUDGET_PUBLIC_SECRET_KEY=$(openssl rand -hex 32)

sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$POSTGRES_PASSWORD/" .env.client
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env.client
sed -i "s/^BUDGET_PUBLIC_SECRET_KEY=.*/BUDGET_PUBLIC_SECRET_KEY=$BUDGET_PUBLIC_SECRET_KEY/" .env.client
```

لا ترفع `.env.client` إلى GitHub ولا تشاركه علنًا.

## التثبيت على كمبيوتر العميل

1. انسخ مجلد DentalPin Client بالكامل إلى مكان ثابت، مثل:
   `C:\DentalPin`
2. شغّل Docker Desktop وانتظر حتى يصبح Ready.
3. شغّل `START_DENTALPIN.bat` كالمستخدم العادي.
4. أول Build قد يستغرق عدة دقائق.
5. افتح `http://localhost`.
6. عند أول تشغيل سيتم تحويلك إلى صفحة Setup لأن قاعدة البيانات نظيفة.
7. أنشئ حساب المدير بكلمة مرور قوية، وأدخل بيانات العيادة والرقم الضريبي المطلوب من النظام.
8. بعد نجاح Setup شغّل `SET_CLIENT_PROFILE.bat` مرة واحدة لتطبيق:
   - Dental Care Clinic
   - +20 10 1234 5678
   - info@dentalcare.com
   - Africa/Cairo
   - EGP
9. اعمل Refresh وسجّل الدخول بالحساب الذي أنشأته.

## الاستخدام اليومي

- تشغيل النظام: `START_DENTALPIN.bat`
- إيقاف الخدمات مع الحفاظ على البيانات: `STOP_DENTALPIN.bat`
- نسخة احتياطية لقاعدة البيانات والمرفقات: `BACKUP_DENTALPIN.bat`

لا تستخدم `docker compose down -v` لأنه يحذف Docker volumes وبالتالي بيانات العيادة.

## الوصول من أجهزة أخرى داخل العيادة

إذا كان مطلوبًا فتح DentalPin من أجهزة أخرى على نفس الشبكة، ثبّت IP لجهاز السيرفر ثم غيّر في `.env.client`:

```env
PUBLIC_URL=http://192.168.1.50
```

واسمح بمنفذ TCP 80 في Windows Firewall. بعد ذلك أعد تشغيل الخدمات.

## ملاحظات مهمة

- بيانات نسخة Railway التجريبية لا تنتقل تلقائيًا إلى هذه النسخة؛ نسخة العميل تبدأ بقاعدة بيانات نظيفة.
- الحجز الإلكتروني يمكن تفعيله من إعدادات النظام بعد إنشاء الأطباء وجداول العمل.
- AI Copilot اختياري؛ ضع مفتاح OpenAI في `OPENAI_API_KEY` فقط إذا كان سيتم استخدامه.
- احتفظ بنسخ احتياطية دورية في مكان آخر غير نفس القرص.
