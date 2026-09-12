import type { Composer } from 'vue-i18n'

/**
 * Translation function that is safe to acquire outside a component `setup`.
 *
 * vue-i18n's `useI18n()` resolves the *current component instance* and throws
 * `Must be called at the top of a 'setup' function` when a composable runs
 * with no instance around it. That is exactly what happens during SSR boot:
 * `app/plugins/settings.registry.ts` calls `useClinic()` -> `useApi()` while
 * the Nuxt app is still initialising, so the whole render failed with a 500
 * ("Patients connection error" / "Failed to fetch clinic" downstream).
 *
 * `$i18n` is the instance @nuxtjs/i18n registers on the Nuxt app — the same
 * global scope `useI18n()` returns when called with no options, which is how
 * every composable in this app calls it. Unlike `useI18n()`, it needs only the
 * Nuxt instance, so it works in components, plugins, middleware and
 * composables alike. Locale reactivity is unchanged: the global composer
 * tracks `locale`, so translated messages still update on locale switches.
 */
export function useGlobalT(): Composer['t'] {
  const { $i18n } = useNuxtApp()
  const composer = $i18n as unknown as Composer

  return composer.t.bind(composer) as Composer['t']
}
