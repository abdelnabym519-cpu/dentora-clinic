<script setup lang="ts">
definePageMeta({
  layout: 'public'
})

const route = useRoute()
const slug = computed(() => String(route.params.slug || ''))

const {
  clinic,
  professionals,
  slots,
  confirmation,
  loadingClinic,
  loadingProfessionals,
  loadingSlots,
  submitting,
  lastError,
  fetchClinic,
  fetchProfessionals,
  fetchSlots,
  book,
  clearSlots
} = usePublicBooking(slug.value)

const selectedProfessionalId = ref('')
const selectedDate = ref('')
const selectedStart = ref('')

const form = reactive({
  first_name: '',
  last_name: '',
  phone: '',
  date_of_birth: '',
  email: '',
  reason: ''
})

function clinicDate(offsetDays = 0): string {
  const timezone = clinic.value?.timezone || 'UTC'
  const now = new Date()

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(now)

  const year = Number(parts.find(part => part.type === 'year')?.value || 0)
  const month = Number(parts.find(part => part.type === 'month')?.value || 1)
  const day = Number(parts.find(part => part.type === 'day')?.value || 1)

  const target = new Date(Date.UTC(year, month - 1, day))
  target.setUTCDate(target.getUTCDate() + offsetDays)

  return [
    target.getUTCFullYear(),
    String(target.getUTCMonth() + 1).padStart(2, '0'),
    String(target.getUTCDate()).padStart(2, '0')
  ].join('-')
}

const minBookingDate = computed(() => clinicDate(0))
const maxBookingDate = computed(() =>
  clinicDate(Math.max((clinic.value?.days_ahead || 30), 1))
)

const dobMax = computed(() => clinicDate(0))

function professionalName(id: string): string {
  const professional = professionals.value.find(item => item.id === id)

  if (!professional) return ''

  return `${professional.first_name} ${professional.last_name}`.trim()
}

function formatSlot(iso: string): string {
  try {
    return new Intl.DateTimeFormat('ar-EG', {
      timeZone: clinic.value?.timezone || 'UTC',
      hour: 'numeric',
      minute: '2-digit'
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function formatConfirmationDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('ar-EG', {
      timeZone: clinic.value?.timezone || 'UTC',
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

const errorMessage = computed(() => {
  switch (lastError.value) {
    case 'not_found':
      return 'رابط الحجز غير متاح أو تم إيقافه.'
    case 'slot_unavailable':
      return 'الموعد الذي اخترته لم يعد متاحًا. اختر موعدًا آخر.'
    case 'rate_limited':
      return 'تم إجراء محاولات كثيرة في وقت قصير. حاول مرة أخرى بعد قليل.'
    case 'validation':
      return 'راجع البيانات المدخلة وتأكد أنها صحيحة.'
    case 'unknown':
      return 'حدث خطأ غير متوقع. حاول مرة أخرى.'
    default:
      return ''
  }
})

watch(
  [selectedProfessionalId, selectedDate],
  async ([professionalId, day]) => {
    selectedStart.value = ''
    clearSlots()

    if (!professionalId || !day) return

    await fetchSlots(professionalId, day)
  }
)

async function submitBooking() {
  if (
    !selectedProfessionalId.value
    || !selectedDate.value
    || !selectedStart.value
    || !form.first_name.trim()
    || !form.last_name.trim()
    || !form.phone.trim()
    || !form.date_of_birth
  ) {
    return
  }

  const result = await book({
    professional_id: selectedProfessionalId.value,
    start_time: selectedStart.value,
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim(),
    phone: form.phone.trim(),
    date_of_birth: form.date_of_birth,
    email: form.email.trim() || undefined,
    reason: form.reason.trim() || undefined
  })

  if (!result && lastError.value === 'slot_unavailable') {
    selectedStart.value = ''
    await fetchSlots(
      selectedProfessionalId.value,
      selectedDate.value
    )
  }
}

onMounted(async () => {
  const clinicLoaded = await fetchClinic()

  if (!clinicLoaded) return

  await fetchProfessionals()

  if (professionals.value.length === 1) {
    selectedProfessionalId.value = professionals.value[0]!.id
  }
})
</script>

<template>
  <main
    dir="rtl"
    class="min-h-screen bg-gray-50 px-4 py-8 text-right text-gray-900 sm:px-6"
  >
    <div class="mx-auto max-w-3xl">
      <div
        v-if="loadingClinic"
        class="rounded-2xl bg-white p-8 text-center shadow-sm"
      >
        جاري تحميل صفحة الحجز...
      </div>

      <div
        v-else-if="!clinic"
        class="rounded-2xl bg-white p-8 text-center shadow-sm"
      >
        <h1 class="text-xl font-bold">
          صفحة الحجز غير متاحة
        </h1>

        <p
          v-if="errorMessage"
          class="mt-3 text-sm text-red-600"
        >
          {{ errorMessage }}
        </p>
      </div>

      <div v-else-if="confirmation">
        <section
          class="rounded-3xl bg-white p-6 text-center shadow-sm sm:p-10"
        >
          <div
            class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-3xl"
          >
            ✓
          </div>

          <h1 class="mt-5 text-2xl font-bold text-green-700">
            تم حجز موعدك بنجاح
          </h1>

          <p class="mt-2 text-gray-600">
            تم تسجيل الموعد مباشرة في جدول العيادة.
          </p>

          <div
            class="mt-6 rounded-2xl bg-gray-50 p-5 text-right"
          >
            <div class="mb-3">
              <span class="text-sm text-gray-500">العيادة</span>
              <div class="font-semibold">
                {{ clinic.clinic_name }}
              </div>
            </div>

            <div class="mb-3">
              <span class="text-sm text-gray-500">الطبيب</span>
              <div class="font-semibold">
                {{ confirmation.professional_name }}
              </div>
            </div>

            <div>
              <span class="text-sm text-gray-500">الموعد</span>
              <div class="font-semibold">
                {{ formatConfirmationDate(confirmation.start_time) }}
              </div>
            </div>
          </div>

          <p class="mt-6 text-sm text-gray-500">
            احتفظ بموعدك وتواصل مع العيادة إذا احتجت أي مساعدة.
          </p>
        </section>
      </div>

      <template v-else>
        <header class="mb-6 text-center">
          <p class="text-sm font-medium text-gray-500">
            حجز موعد أونلاين
          </p>

          <h1 class="mt-2 text-3xl font-bold">
            {{ clinic.clinic_name }}
          </h1>

          <div
            v-if="clinic.clinic_phone || clinic.clinic_email"
            class="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-gray-500"
          >
            <span v-if="clinic.clinic_phone">
              {{ clinic.clinic_phone }}
            </span>

            <span v-if="clinic.clinic_email">
              {{ clinic.clinic_email }}
            </span>
          </div>
        </header>

        <form
          class="space-y-6"
          @submit.prevent="submitBooking"
        >
          <section class="rounded-2xl bg-white p-5 shadow-sm sm:p-6">
            <h2 class="text-lg font-bold">
              1. اختر الطبيب واليوم
            </h2>

            <div class="mt-5 grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  الطبيب
                </span>

                <select
                  v-model="selectedProfessionalId"
                  required
                  class="w-full rounded-xl border border-gray-300 bg-white px-3 py-3 outline-none focus:border-gray-500"
                >
                  <option value="">
                    اختر الطبيب
                  </option>

                  <option
                    v-for="professional in professionals"
                    :key="professional.id"
                    :value="professional.id"
                  >
                    {{ professional.first_name }}
                    {{ professional.last_name }}
                  </option>
                </select>

                <p
                  v-if="loadingProfessionals"
                  class="mt-2 text-xs text-gray-500"
                >
                  جاري تحميل الأطباء...
                </p>
              </label>

              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  اليوم
                </span>

                <input
                  v-model="selectedDate"
                  type="date"
                  required
                  :min="minBookingDate"
                  :max="maxBookingDate"
                  class="w-full rounded-xl border border-gray-300 bg-white px-3 py-3 outline-none focus:border-gray-500"
                >
              </label>
            </div>
          </section>

          <section class="rounded-2xl bg-white p-5 shadow-sm sm:p-6">
            <h2 class="text-lg font-bold">
              2. اختر الموعد
            </h2>

            <div
              v-if="!selectedProfessionalId || !selectedDate"
              class="mt-4 rounded-xl bg-gray-50 p-4 text-sm text-gray-500"
            >
              اختر الطبيب واليوم أولًا لعرض المواعيد المتاحة.
            </div>

            <div
              v-else-if="loadingSlots"
              class="mt-4 rounded-xl bg-gray-50 p-4 text-sm text-gray-500"
            >
              جاري البحث عن المواعيد المتاحة...
            </div>

            <div
              v-else-if="slots.length === 0"
              class="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-800"
            >
              لا توجد مواعيد متاحة في هذا اليوم. جرّب يومًا آخر.
            </div>

            <div
              v-else
              class="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
            >
              <button
                v-for="slot in slots"
                :key="slot.start"
                type="button"
                class="rounded-xl border px-3 py-3 text-sm font-semibold transition"
                :class="
                  selectedStart === slot.start
                    ? 'border-gray-900 bg-gray-900 text-white'
                    : 'border-gray-200 bg-white hover:border-gray-400'
                "
                @click="selectedStart = slot.start"
              >
                {{ formatSlot(slot.start) }}
              </button>
            </div>
          </section>

          <section class="rounded-2xl bg-white p-5 shadow-sm sm:p-6">
            <h2 class="text-lg font-bold">
              3. بيانات المريض
            </h2>

            <p class="mt-1 text-sm text-gray-500">
              استخدم بيانات المريض الحقيقية حتى تتمكن العيادة من التعرف عليه بشكل صحيح.
            </p>

            <div class="mt-5 grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  الاسم الأول *
                </span>

                <input
                  v-model="form.first_name"
                  type="text"
                  maxlength="100"
                  required
                  autocomplete="given-name"
                  class="w-full rounded-xl border border-gray-300 px-3 py-3 outline-none focus:border-gray-500"
                >
              </label>

              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  اسم العائلة *
                </span>

                <input
                  v-model="form.last_name"
                  type="text"
                  maxlength="100"
                  required
                  autocomplete="family-name"
                  class="w-full rounded-xl border border-gray-300 px-3 py-3 outline-none focus:border-gray-500"
                >
              </label>

              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  رقم الهاتف *
                </span>

                <input
                  v-model="form.phone"
                  type="tel"
                  minlength="7"
                  maxlength="20"
                  required
                  autocomplete="tel"
                  inputmode="tel"
                  class="w-full rounded-xl border border-gray-300 px-3 py-3 text-left outline-none focus:border-gray-500"
                  dir="ltr"
                >
              </label>

              <label class="block">
                <span class="mb-2 block text-sm font-medium">
                  تاريخ الميلاد *
                </span>

                <input
                  v-model="form.date_of_birth"
                  type="date"
                  required
                  :max="dobMax"
                  class="w-full rounded-xl border border-gray-300 px-3 py-3 outline-none focus:border-gray-500"
                >
              </label>

              <label class="block sm:col-span-2">
                <span class="mb-2 block text-sm font-medium">
                  البريد الإلكتروني
                  <span class="font-normal text-gray-400">(اختياري)</span>
                </span>

                <input
                  v-model="form.email"
                  type="email"
                  maxlength="255"
                  autocomplete="email"
                  class="w-full rounded-xl border border-gray-300 px-3 py-3 text-left outline-none focus:border-gray-500"
                  dir="ltr"
                >
              </label>

              <label class="block sm:col-span-2">
                <span class="mb-2 block text-sm font-medium">
                  سبب الزيارة
                  <span class="font-normal text-gray-400">(اختياري)</span>
                </span>

                <textarea
                  v-model="form.reason"
                  rows="3"
                  maxlength="500"
                  placeholder="مثال: كشف، ألم في الضرس، تنظيف..."
                  class="w-full resize-none rounded-xl border border-gray-300 px-3 py-3 outline-none focus:border-gray-500"
                />
              </label>
            </div>
          </section>

          <div
            v-if="errorMessage"
            class="rounded-2xl bg-red-50 p-4 text-sm text-red-700"
          >
            {{ errorMessage }}
          </div>

          <section class="rounded-2xl bg-white p-5 shadow-sm">
            <div
              v-if="selectedStart"
              class="mb-4 rounded-xl bg-gray-50 p-4 text-sm"
            >
              <div class="text-gray-500">
                الموعد المختار
              </div>

              <div class="mt-1 font-bold">
                {{ professionalName(selectedProfessionalId) }}
                —
                {{ formatConfirmationDate(selectedStart) }}
              </div>
            </div>

            <button
              type="submit"
              :disabled="
                submitting
                || !selectedStart
                || !form.first_name.trim()
                || !form.last_name.trim()
                || !form.phone.trim()
                || !form.date_of_birth
              "
              class="w-full rounded-xl bg-gray-900 px-5 py-4 font-bold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {{ submitting ? 'جاري تأكيد الحجز...' : 'تأكيد الحجز' }}
            </button>

            <p class="mt-3 text-center text-xs text-gray-500">
              عند التأكيد سيتم إضافة الموعد مباشرة إلى جدول العيادة.
            </p>
          </section>
        </form>
      </template>
    </div>
  </main>
</template>
