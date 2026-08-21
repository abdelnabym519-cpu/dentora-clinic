import test from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";


const clinic = {
  id: "clinic-1",
  public_slug: "dental",
  display_name: "Dental Clinic",
  phone: "01000000000",
  email: "clinic@example.com",
  timezone: "Africa/Cairo",
  currency: "EGP",
  slot_minutes: 30,
  days_ahead: 30,
  last_synced_at: "2026-08-19T04:00:00Z"
};

const professionals = [
  {
    id: "professional-1",
    clinic_id: "clinic-1",
    public_slug: "dr-ahmed-mahmoud",
    display_name: "د. أحمد محمود",
    active: 1
  },
  {
    id: "professional-2",
    clinic_id: "clinic-1",
    public_slug: "dr-sara-ali",
    display_name: "د. سارة علي",
    active: 1
  }
];


const availabilitySlots = [
  {
    clinic_id: "clinic-1",
    professional_id: "professional-1",
    start_time: "2026-08-20T10:00:00+03:00",
    end_time: "2026-08-20T10:30:00+03:00",
    local_day: "2026-08-20",
    available: 1
  },
  {
    clinic_id: "clinic-1",
    professional_id: "professional-1",
    start_time: "2026-08-20T11:00:00+03:00",
    end_time: "2026-08-20T11:30:00+03:00",
    local_day: "2026-08-20",
    available: 1
  },
  {
    clinic_id: "clinic-1",
    professional_id: "professional-1",
    start_time: "2026-08-20T12:00:00+03:00",
    end_time: "2026-08-20T12:30:00+03:00",
    local_day: "2026-08-20",
    available: 0
  },
  {
    clinic_id: "clinic-1",
    professional_id: "professional-2",
    start_time: "2026-08-20T13:00:00+03:00",
    end_time: "2026-08-20T13:30:00+03:00",
    local_day: "2026-08-20",
    available: 1
  },
  {
    clinic_id: "clinic-1",
    professional_id: "professional-1",
    start_time: "2026-08-20T22:30:00Z",
    end_time: "2026-08-20T23:00:00Z",
    local_day: "2026-08-21",
    available: 1
  },
];


class FakeStatement {
  constructor(sql) {
    this.sql = sql;
    this.params = [];
  }

  bind(...params) {
    this.params = params;
    return this;
  }

  async first() {
    if (this.sql.includes("FROM clinics")) {
      const [slug] = this.params;

      if (
        slug === clinic.public_slug &&
        clinic
      ) {
        return { ...clinic };
      }

      return null;
    }

    if (
      this.sql.includes("FROM professionals") &&
      this.sql.includes("public_slug = ?")
    ) {
      const [clinicId, doctorSlug] = this.params;

      const found = professionals.find(
        item =>
          item.clinic_id === clinicId &&
          item.public_slug === doctorSlug &&
          item.active === 1
      );

      if (!found) {
        return null;
      }

      return {
        id: found.id,
        public_slug: found.public_slug,
        display_name: found.display_name
      };
    }

    throw new Error(
      "Unexpected first() query: " + this.sql
    );
  }

  async all() {
    if (this.sql.includes("FROM availability_slots")) {
      const [
        clinicId,
        professionalId,
        localDay
      ] = this.params;

      return {
        results: availabilitySlots
          .filter(
            item =>
              item.clinic_id === clinicId &&
              item.professional_id === professionalId &&
              item.available === 1 &&
              item.local_day === localDay
          )
          .sort(
            (a, b) =>
              a.start_time.localeCompare(b.start_time)
          )
          .map(item => ({
            start_time: item.start_time,
            end_time: item.end_time
          }))
      };
    }

    if (this.sql.includes("FROM professionals")) {
      const [clinicId] = this.params;

      return {
        results: professionals
          .filter(
            item =>
              item.clinic_id === clinicId &&
              item.active === 1
          )
          .map(item => ({
            public_slug: item.public_slug,
            display_name: item.display_name
          }))
      };
    }

    throw new Error(
      "Unexpected all() query: " + this.sql
    );
  }
}


class FakeDB {
  prepare(sql) {
    return new FakeStatement(sql);
  }
}


const env = {
  DB: new FakeDB()
};


async function readJson(response) {
  return JSON.parse(await response.text());
}


test("GET /health", async () => {
  const response = await worker.fetch(
    new Request("https://booking.dentora.example/health"),
    {}
  );

  assert.equal(response.status, 200);

  const body = await readJson(response);

  assert.equal(body.ok, true);
  assert.equal(
    body.service,
    "dentora-booking"
  );
});


test("GET public clinic", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental"
    ),
    env
  );

  assert.equal(response.status, 200);

  const body = await readJson(response);

  assert.equal(body.ok, true);
  assert.equal(body.data.public_slug, "dental");
  assert.equal(
    body.data.clinic_name,
    "Dental Clinic"
  );

  assert.equal(
    Object.hasOwn(body.data, "license_id"),
    false
  );
});


test("GET clinic professionals", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals"
    ),
    env
  );

  assert.equal(response.status, 200);

  const body = await readJson(response);

  assert.equal(body.ok, true);
  assert.equal(body.data.length, 2);

  assert.equal(
    body.data[0].public_slug,
    "dr-ahmed-mahmoud"
  );
});


test("GET specific professional", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud"
    ),
    env
  );

  assert.equal(response.status, 200);

  const body = await readJson(response);

  assert.equal(body.ok, true);

  assert.equal(
    body.data.public_slug,
    "dr-ahmed-mahmoud"
  );

  assert.equal(
    body.data.display_name,
    "د. أحمد محمود"
  );
});


test("unknown clinic returns 404", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/unknown"
    ),
    env
  );

  assert.equal(response.status, 404);

  const body = await readJson(response);

  assert.equal(body.ok, false);
  assert.equal(body.error, "not_found");
});


test("unknown professional returns 404", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/not-found"
    ),
    env
  );

  assert.equal(response.status, 404);
});


test("public API without DB returns 503", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental"
    ),
    {}
  );

  assert.equal(response.status, 503);

  const body = await readJson(response);

  assert.equal(
    body.error,
    "database_unavailable"
  );
});


test("GET available slots", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud/slots?day=2026-08-20"
    ),
    env
  );

  assert.equal(response.status, 200);

  const body = await readJson(response);

  assert.equal(body.ok, true);
  assert.equal(body.data.length, 2);

  assert.deepEqual(
    body.data,
    [
      {
        start_time: "2026-08-20T10:00:00+03:00",
        end_time: "2026-08-20T10:30:00+03:00"
      },
      {
        start_time: "2026-08-20T11:00:00+03:00",
        end_time: "2026-08-20T11:30:00+03:00"
      }
    ]
  );

  for (const slot of body.data) {
    assert.equal(
      Object.hasOwn(slot, "professional_id"),
      false
    );

    assert.equal(
      Object.hasOwn(slot, "clinic_id"),
      false
    );
  }
});


test("invalid slot day returns 400", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud/slots?day=20-08-2026"
    ),
    env
  );

  assert.equal(response.status, 400);

  const body = await readJson(response);

  assert.equal(body.ok, false);
  assert.equal(body.error, "invalid_day");
});


test("missing slot day returns 400", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud/slots"
    ),
    env
  );

  assert.equal(response.status, 400);

  const body = await readJson(response);

  assert.equal(body.error, "invalid_day");
});


test("unknown doctor slots return 404", async () => {
  const response = await worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/public/dental/professionals/not-found/slots?day=2026-08-20"
    ),
    env
  );

  assert.equal(response.status, 404);
});


test(
  "GET slots uses clinic local day across UTC boundary",
  async () => {
    const response = await worker.fetch(
      new Request(
        "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud/slots?day=2026-08-21"
      ),
      env
    );

    assert.equal(
      response.status,
      200
    );

    const body =
      await readJson(response);

    assert.equal(
      body.ok,
      true
    );

    assert.deepEqual(
      body.data,
      [
        {
          start_time:
            "2026-08-20T22:30:00Z",

          end_time:
            "2026-08-20T23:00:00Z"
        }
      ]
    );

    /*
     * local_day is internal indexing
     * metadata and must not be exposed.
     */
    assert.equal(
      Object.hasOwn(
        body.data[0],
        "local_day"
      ),
      false
    );
  }
);
