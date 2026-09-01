import { STORAGE_KEYS } from '~/constants/storage'
import { SUPPORTED_LOCALES } from '~/constants/languages'
import type { CodeLang } from '~/types'
import type { Composer } from 'vue-i18n'

export default defineNuxtPlugin(async (nuxtApp) => {
  const i18n = nuxtApp.$i18n as Composer
  const localeCookie = useCookie<CodeLang | null>(STORAGE_KEYS.LOCALE_COOKIE, {
    path: '/',
    sameSite: 'lax'
  })
  const savedLocale = localeCookie.value

  if (
    savedLocale
    && SUPPORTED_LOCALES.includes(savedLocale)
    && savedLocale !== i18n.locale.value
  ) {
    await i18n.setLocale(savedLocale)
  }
})
