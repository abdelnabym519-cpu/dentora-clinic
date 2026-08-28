<script setup lang="ts">
import { ar, en, es, fr, pt } from '@nuxt/ui/locale'

const { t, locale } = useI18n()

const nuxtUILocales: Record<string, typeof en> = { en, fr, es, pt, ar }
const nuxtUILocale = computed(() => nuxtUILocales[locale.value] || en)
const documentDirection = computed(() => locale.value === 'ar' ? 'rtl' : 'ltr')

useHead(() => ({
  meta: [
    { name: 'viewport', content: 'width=device-width, initial-scale=1' }
  ],
  link: [
    { rel: 'icon', href: '/favicon.ico' }
  ],
  htmlAttrs: {
    lang: locale.value,
    dir: documentDirection.value
  }
}))

useSeoMeta({
  title: 'Dentora',
  description: t('app.tagline')
})
</script>

<template>
  <UApp :locale="nuxtUILocale">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
