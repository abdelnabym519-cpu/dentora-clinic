export const STORAGE_KEYS = {
  LOCALE: 'dentora:locale',
  LOCALE_COOKIE: 'dentora_locale',
  DENSITY: 'ui:density',
  onboardingDismissed: (clinicId: string) =>
    `dentora.settings.onboarding.dismissed:${clinicId}`
} as const
