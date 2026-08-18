import { STORAGE_KEYS } from '~/constants/storage'
import { SUPPORTED_LOCALES } from '~/constants/languages'
import type { CodeLang } from '~/types'

export function useLocale() {
  const { locale, setLocale, locales } = useI18n()
  const config = useRuntimeConfig()

  const forcedLocale = computed<CodeLang | null>(() => {
    const value = String(config.public.forceLocale || '') as CodeLang

    return SUPPORTED_LOCALES.includes(value)
      ? value
      : null
  })

  const availableLocales = computed(() => {
    const items = (locales.value as Array<{ code: CodeLang, name: string }>)
      .map(l => ({
        code: l.code,
        name: l.name
      }))

    if (!forcedLocale.value) {
      return items
    }

    return items.filter(
      item => item.code === forcedLocale.value
    )
  })

  async function changeLocale(code: CodeLang): Promise<void> {
    const target = forcedLocale.value || code

    if (import.meta.client) {
      localStorage.setItem(
        STORAGE_KEYS.LOCALE,
        target
      )
    }

    await setLocale(target)
  }

  return {
    locale,
    currentLocale: computed(() => locale.value),
    availableLocales,
    changeLocale,
    forcedLocale
  }
}
