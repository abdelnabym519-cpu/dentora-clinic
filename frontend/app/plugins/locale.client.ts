import { watch } from 'vue'
import { STORAGE_KEYS } from '~/constants/storage'
import type { Composer } from 'vue-i18n'
import type { CodeLang } from '~/types'
import { SUPPORTED_LOCALES } from '~/constants/languages'

export default defineNuxtPlugin(async (nuxtApp) => {
  const i18n = nuxtApp.$i18n as Composer
  const config = useRuntimeConfig()

  const applyDirection = (locale: string) => {
    document.documentElement.lang = locale
    document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'
  }

  const forcedLocale = String(
    config.public.forceLocale || ''
  ) as CodeLang

  if (
    forcedLocale
    && SUPPORTED_LOCALES.includes(forcedLocale)
  ) {
    localStorage.setItem(
      STORAGE_KEYS.LOCALE,
      forcedLocale
    )

    if (i18n.locale.value !== forcedLocale) {
      await i18n.setLocale(forcedLocale)
    }

    applyDirection(forcedLocale)
  } else {
    const savedLocale = localStorage.getItem(
      STORAGE_KEYS.LOCALE
    ) as CodeLang

    if (
      savedLocale
      && SUPPORTED_LOCALES.includes(savedLocale)
      && savedLocale !== i18n.locale.value
    ) {
      await i18n.setLocale(savedLocale)
    }

    applyDirection(i18n.locale.value)
  }

  watch(i18n.locale, (locale) => {
    applyDirection(locale)
  })
})
