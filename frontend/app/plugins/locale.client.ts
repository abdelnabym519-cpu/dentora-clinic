import { watch } from 'vue'
import { STORAGE_KEYS } from '~/constants/storage'
import type { Composer } from 'vue-i18n'
import type { CodeLang } from '~/types'
import { SUPPORTED_LOCALES } from '~/constants/languages'

export default defineNuxtPlugin(async (nuxtApp) => {
  const i18n = nuxtApp.$i18n as Composer
  const localeCookie = useCookie<CodeLang | null>(STORAGE_KEYS.LOCALE_COOKIE, {
    path: '/',
    sameSite: 'lax'
  })

  const applyDirection = (locale: string) => {
    document.documentElement.lang = locale
    document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'
  }

  const isSupported = (value: string | null | undefined): value is CodeLang =>
    Boolean(value && SUPPORTED_LOCALES.includes(value as CodeLang))

  const storedLocale = localStorage.getItem(STORAGE_KEYS.LOCALE)
  const initialLocale = isSupported(localeCookie.value)
    ? localeCookie.value
    : isSupported(storedLocale)
      ? storedLocale
      : null

  if (initialLocale && initialLocale !== i18n.locale.value) {
    await i18n.setLocale(initialLocale)
  }

  if (initialLocale) {
    localeCookie.value = initialLocale
    localStorage.setItem(STORAGE_KEYS.LOCALE, initialLocale)
  }

  applyDirection(i18n.locale.value)

  const syncStoredLocaleToCookie = () => {
    const value = localStorage.getItem(STORAGE_KEYS.LOCALE)
    if (isSupported(value) && value !== localeCookie.value) {
      localeCookie.value = value
    }
  }

  window.addEventListener('beforeunload', syncStoredLocaleToCookie)
  nuxtApp.hook('app:beforeUnmount', () => {
    window.removeEventListener('beforeunload', syncStoredLocaleToCookie)
  })

  watch(i18n.locale, (locale) => {
    localeCookie.value = locale as CodeLang
    localStorage.setItem(STORAGE_KEYS.LOCALE, locale)
    applyDirection(locale)
  })
})
