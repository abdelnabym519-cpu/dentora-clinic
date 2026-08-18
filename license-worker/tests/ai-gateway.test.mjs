import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";

if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

const { handleAiChatCompletions } =
  await import("../src/ai-gateway.js");

function bytesToBase64Url(bytes) {
  return Buffer.from(bytes)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function arrayBufferToPem(buffer, label) {
  const body = Buffer.from(buffer)
    .toString("base64")
    .match(/.{1,64}/g)
    .join("\n");

  return (
    `-----BEGIN ${label}-----\n`
    + `${body}\n`
    + `-----END ${label}-----\n`
  );
}

async function createSigningMaterial() {
  const pair = await crypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"]
  );

  const spki = await crypto.subtle.exportKey(
    "spki",
    pair.publicKey
  );

  const pem = arrayBufferToPem(
    spki,
    "PUBLIC KEY"
  );

  return {
    privateKey: pair.privateKey,

    publicKeyB64: Buffer.from(
      pem,
      "utf8"
    ).toString("base64"),
  };
}

async function signLease(privateKey, overrides = {}) {
  const payload = {
    v: 1,
    product: "dentalpin",

    license_id: "license-test-001",
    activation_id: "activation-test-001",

    installation_id:
      "installation-test-001",

    fingerprint:
      "fingerprint-test-000000000001",

    customer_name:
      "DentalPin AI Gateway Test",

    plan: "standard",

    features: [
      "ai",
      "booking",
      "core",
    ],

    issued_at:
      new Date().toISOString(),

    refresh_after:
      new Date(
        Date.now() + 60 * 60 * 1000
      ).toISOString(),

    valid_until:
      new Date(
        Date.now() + 24 * 60 * 60 * 1000
      ).toISOString(),

    license_expires_at:
      new Date(
        Date.now() + 30 * 24 * 60 * 60 * 1000
      ).toISOString(),

    ...overrides,
  };

  const raw = new TextEncoder().encode(
    JSON.stringify(payload)
  );

  const signature =
    await crypto.subtle.sign(
      "Ed25519",
      privateKey,
      raw
    );

  const token =
    `${bytesToBase64Url(raw)}.`
    + `${bytesToBase64Url(
      new Uint8Array(signature)
    )}`;

  return {
    payload,
    token,
  };
}

function makeDb(row) {
  return {
    prepare() {
      return {
        bind() {
          return {
            async first() {
              return row;
            },
          };
        },
      };
    },
  };
}

function makeRow(
  payload,
  overrides = {}
) {
  return {
    activation_id:
      payload.activation_id,

    license_id:
      payload.license_id,

    installation_id:
      payload.installation_id,

    fingerprint:
      payload.fingerprint,

    revoked_at: null,

    license_status: "active",

    license_expires_at:
      new Date(
        Date.now()
        + 30 * 24 * 60 * 60 * 1000
      ).toISOString(),

    features_json:
      JSON.stringify([
        "ai",
        "booking",
        "core",
      ]),

    ...overrides,
  };
}

function makeEnv(publicKeyB64, row) {
  return {
    LICENSE_PUBLIC_KEY_B64:
      publicKeyB64,

    AI_PROVIDER_MODEL:
      "@cf/zai-org/glm-4.7-flash",

    AI_ALLOWED_MODELS:
      "gpt-5.4-mini",

    AI_MAX_REQUEST_BYTES:
      "524288",

    AI: {
      async run() {
        throw new Error(
          "Unexpected Workers AI call"
        );
      },
    },

    DB: makeDb(row),
  };
}

function makeRequest({
  token,
  body,
  authorization = true,
}) {
  const headers = {
    "content-type":
      "application/json",
  };

  if (authorization && token) {
    headers.authorization =
      `Bearer ${token}`;
  }

  return new Request(
    "https://gateway.test/ai/v1/chat/completions",
    {
      method: "POST",
      headers,
      body: JSON.stringify(
        body ?? {
          model:
            "gpt-5.4-mini",

          stream: true,

          messages: [
            {
              role: "user",
              content: "test",
            },
          ],
        }
      ),
    }
  );
}

async function json(response) {
  return JSON.parse(
    await response.text()
  );
}


test(
  "AI gateway security contract",
  async (t) => {
    const signing =
      await createSigningMaterial();

    const signed =
      await signLease(
        signing.privateKey
      );


    await t.test(
      "missing credential -> 401",
      async () => {
        const row = makeRow(
          signed.payload
        );

        const response =
          await handleAiChatCompletions(
            makeRequest({
              token: null,
              authorization: false,
            }),
            makeEnv(
              signing.publicKeyB64,
              row
            )
          );

        assert.equal(
          response.status,
          401
        );

        const body =
          await json(response);

        assert.match(
          body.detail,
          /credential/i
        );
      }
    );


    await t.test(
      "invalid lease -> 401",
      async () => {
        const row = makeRow(
          signed.payload
        );

        const response =
          await handleAiChatCompletions(
            makeRequest({
              token:
                "invalid.invalid",
            }),
            makeEnv(
              signing.publicKeyB64,
              row
            )
          );

        assert.equal(
          response.status,
          401
        );
      }
    );


    await t.test(
      "AI disabled remotely -> 403",
      async () => {
        const row = makeRow(
          signed.payload,
          {
            features_json:
              JSON.stringify([
                "booking",
                "core",
              ]),
          }
        );

        const response =
          await handleAiChatCompletions(
            makeRequest({
              token:
                signed.token,
            }),
            makeEnv(
              signing.publicKeyB64,
              row
            )
          );

        assert.equal(
          response.status,
          403
        );

        const body =
          await json(response);

        assert.match(
          body.detail,
          /AI feature is not enabled/i
        );
      }
    );


    await t.test(
      "revoked activation -> 403",
      async () => {
        const row = makeRow(
          signed.payload,
          {
            revoked_at:
              new Date().toISOString(),
          }
        );

        const response =
          await handleAiChatCompletions(
            makeRequest({
              token:
                signed.token,
            }),
            makeEnv(
              signing.publicKeyB64,
              row
            )
          );

        assert.equal(
          response.status,
          403
        );

        const body =
          await json(response);

        assert.match(
          body.detail,
          /revoked/i
        );
      }
    );


    await t.test(
      "disallowed model -> 403",
      async () => {
        const row = makeRow(
          signed.payload
        );

        const request =
          makeRequest({
            token:
              signed.token,

            body: {
              model:
                "not-allowed-model",

              stream: true,

              messages: [
                {
                  role: "user",
                  content: "test",
                },
              ],
            },
          });

        const response =
          await handleAiChatCompletions(
            request,
            makeEnv(
              signing.publicKeyB64,
              row
            )
          );

        assert.equal(
          response.status,
          403
        );

        const body =
          await json(response);

        assert.match(
          body.detail,
          /model is not allowed/i
        );
      }
    );


    await t.test(
      "oversized request -> 413",
      async () => {
        const row = makeRow(
          signed.payload
        );

        const env = makeEnv(
          signing.publicKeyB64,
          row
        );

        env.AI_MAX_REQUEST_BYTES =
          "1024";

        const request =
          makeRequest({
            token:
              signed.token,

            body: {
              model:
                "gpt-5.4-mini",

              stream: true,

              messages: [
                {
                  role: "user",

                  content:
                    "x".repeat(5000),
                },
              ],
            },
          });

        const response =
          await handleAiChatCompletions(
            request,
            env
          );

        assert.equal(
          response.status,
          413
        );
      }
    );


    await t.test(
      "valid entitlement streams through Workers AI safely",
      async () => {
        const row = makeRow(
          signed.payload
        );

        const env = makeEnv(
          signing.publicKeyB64,
          row
        );

        let capturedModel = null;
        let capturedBody = null;

        env.AI.run =
          async (model, body) => {
            capturedModel = model;

            capturedBody =
              structuredClone(body);

            const encoder =
              new TextEncoder();

            return new ReadableStream({
              start(controller) {
                controller.enqueue(
                  encoder.encode(
                    'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\\n\\n'
                  )
                );

                controller.enqueue(
                  encoder.encode(
                    'data: [DONE]\\n\\n'
                  )
                );

                controller.close();
              },
            });
          };

        const request =
          makeRequest({
            token:
              signed.token,

            body: {
              model:
                "gpt-5.4-mini",

              stream: true,

              stream_options: {
                include_usage: true,
              },

              parallel_tool_calls:
                false,

              max_completion_tokens:
                99999,

              messages: [
                {
                  role: "user",
                  content:
                    "safe synthetic test",
                },
              ],
            },
          });

        const response =
          await handleAiChatCompletions(
            request,
            env
          );

        assert.equal(
          response.status,
          200
        );

        assert.equal(
          capturedModel,
          "@cf/zai-org/glm-4.7-flash"
        );

        assert.equal(
          capturedBody.model,
          "@cf/zai-org/glm-4.7-flash"
        );

        assert.equal(
          capturedBody
            .max_completion_tokens,
          4096
        );

        assert.equal(
          capturedBody.stream,
          true
        );

        assert.equal(
          capturedBody
            .parallel_tool_calls,
          false
        );

        assert.deepEqual(
          capturedBody
            .stream_options,
          {
            include_usage: true,
          }
        );

        assert.equal(
          JSON.stringify(
            capturedBody
          ).includes(
            signed.token
          ),
          false
        );

        assert.equal(
          response.headers.get(
            "content-type"
          ),
          "text/event-stream"
        );

        const streamed =
          await response.text();

        assert.match(
          streamed,
          /"content":"ok"/
        );

        assert.match(
          streamed,
          /\[DONE\]/
        );
      }
    );
  }
);
