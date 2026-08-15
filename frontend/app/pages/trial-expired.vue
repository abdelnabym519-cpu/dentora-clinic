<script setup lang="ts">
definePageMeta({ layout: false })

const { locale } = useI18n()
const isArabic = computed(() => locale.value === 'ar')
</script>

<template>
  <main
    class="min-h-screen bg-canvas flex items-center justify-center p-6"
    :dir="isArabic ? 'rtl' : 'ltr'"
  >
    <section class="w-full max-w-xl rounded-2xl border border-subtle bg-surface p-8 text-center shadow-sm">
      <div class="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 text-amber-800">
        <UIcon
          name="i-lucide-clock-3"
          class="h-7 w-7"
        />
      </div>

      <template v-if="isArabic">
        <h1 class="text-2xl font-semibold text-default">
          انتهت الفترة التجريبية
        </h1>
        <p class="mt-3 text-muted leading-7">
          انتهت مدة تجربة DentalPin البالغة 3 أيام. بيانات التجربة لم يتم حذفها، ويمكن تفعيل النسخة الكاملة عند إتمام الشراء.
        </p>
        <p class="mt-5 font-medium text-default">
          تواصل معنا لتفعيل النسخة الكاملة للعيادة.
        </p>
      </template>

      <template v-else>
        <h1 class="text-2xl font-semibold text-default">
          Trial period ended
        </h1>
        <p class="mt-3 text-muted leading-7">
          Your 3-day DentalPin trial has ended. Trial data has not been deleted and the full version can be activated after purchase.
        </p>
        <p class="mt-5 font-medium text-default">
          Contact us to activate the full clinic version.
        </p>
      </template>
    </section>
  </main>
</template>
