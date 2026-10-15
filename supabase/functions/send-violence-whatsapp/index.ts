// Supabase Edge Function: send violence alert via Twilio
//
// Works on Twilio Trial WITHOUT Content Template Builder:
//   Use WhatsApp Sandbox free-form (join once from your phone).
//
// IMPORTANT:
//   Do NOT set TWILIO_WHATSAPP_FROM to your Business WhatsApp number
//   (e.g. +1737...) unless you also set TWILIO_CONTENT_SID.
//   Without ContentSid we always send via Sandbox +1 415 523 8886.
//
// Secrets:
//   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
//   WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
 //   (optional) TWILIO_CONTENT_SID=HXxxxx  — only if using Business sender
//   (optional) TWILIO_SMS_FROM=+1737...   — India trial SMS usually blocked

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

const SANDBOX_FROM = "whatsapp:+14155238886";

type AlertPayload = {
  id?: string;
  detected_at?: string;
  camera_ip?: string;
  channel?: number;
  confidence?: number;
  label?: string;
  message?: string;
  record?: AlertPayload;
  type?: string;
};

function alertFields(alert: AlertPayload) {
  const when = alert.detected_at
    ? new Date(alert.detected_at).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      dateStyle: "medium",
      timeStyle: "medium",
    })
    : new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

  const conf = alert.confidence != null
    ? `${(alert.confidence * 100).toFixed(1)}%`
    : "n/a";

  const camera = `${alert.camera_ip ?? "unknown"}` +
    (alert.channel != null ? ` (ch ${alert.channel})` : "");

  const label = alert.label ?? "violence";
  return { when, conf, camera, label };
}

function formatMessage(alert: AlertPayload): string {
  if (alert.message) return alert.message;
  const { when, conf, camera, label } = alertFields(alert);
  return [
    "Possible Violence Detected",
    "",
    `Time: ${when}`,
    `Confidence: ${conf}`,
    `Camera: ${camera}`,
    `Label: ${label}`,
    "",
    "Please verify on the live feed.",
  ].join("\n");
}

function phoneOnly(value: string): string {
  return value.replace(/^whatsapp:/i, "").trim();
}

function resolveWhatsAppFrom(): { from: string; mode: "sandbox" | "business" } {
  const contentSid = Deno.env.get("TWILIO_CONTENT_SID");
  const configured = Deno.env.get("TWILIO_WHATSAPP_FROM") || "";

  // Business sender without ContentSid always fails → force Sandbox
  if (!contentSid) {
    return { from: SANDBOX_FROM, mode: "sandbox" };
  }

  if (configured && configured !== SANDBOX_FROM) {
    return { from: configured, mode: "business" };
  }
  return { from: configured || SANDBOX_FROM, mode: "sandbox" };
}

async function twilioCreateMessage(
  accountSid: string,
  authToken: string,
  form: URLSearchParams,
): Promise<{ sid: string }> {
  const url =
    `https://api.twilio.com/2010-04-01/Accounts/${accountSid}/Messages.json`;
  const auth = btoa(`${accountSid}:${authToken}`);
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form,
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.message ?? JSON.stringify(data));
  }
  return { sid: data.sid as string };
}

async function sendWhatsAppSandbox(
  accountSid: string,
  authToken: string,
  body: string,
): Promise<{ sid: string; channel: string; from: string }> {
  const toRaw = Deno.env.get("WHATSAPP_TO");
  if (!toRaw) throw new Error("Missing WHATSAPP_TO secret");

  const to = toRaw.startsWith("whatsapp:") ? toRaw : `whatsapp:${toRaw}`;
  const { from } = resolveWhatsAppFrom();
  const contentSid = Deno.env.get("TWILIO_CONTENT_SID");

  const form = new URLSearchParams({ From: from, To: to });

  if (contentSid && from !== SANDBOX_FROM) {
    // Business WhatsApp with approved template
    // (variables must match your template)
    // Kept for later — not used on trial sandbox path
    throw new Error("Business path unexpected without alert context");
  }

  // Sandbox free-form body (recipient must have joined sandbox)
  form.set("Body", body);

  try {
    const { sid } = await twilioCreateMessage(accountSid, authToken, form);
    return { sid, channel: "whatsapp-sandbox", from };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (
      msg.toLowerCase().includes("not a valid") ||
      msg.toLowerCase().includes("sandbox") ||
      msg.toLowerCase().includes("join") ||
      msg.toLowerCase().includes("63007") ||
      msg.toLowerCase().includes("63015") ||
      msg.toLowerCase().includes("21211")
    ) {
      throw new Error(
        `${msg}. Open WhatsApp on your phone and send the join code ` +
          `shown in Twilio Console → Messaging → Try WhatsApp to ` +
          `+1 415 523 8886, then retry.`,
      );
    }
    throw err;
  }
}

async function sendWhatsAppBusiness(
  accountSid: string,
  authToken: string,
  alert: AlertPayload,
): Promise<{ sid: string; channel: string; from: string }> {
  const contentSid = Deno.env.get("TWILIO_CONTENT_SID");
  if (!contentSid) {
    throw new Error("TWILIO_CONTENT_SID required for Business WhatsApp");
  }

  const toRaw = Deno.env.get("WHATSAPP_TO");
  if (!toRaw) throw new Error("Missing WHATSAPP_TO");
  const to = toRaw.startsWith("whatsapp:") ? toRaw : `whatsapp:${toRaw}`;
  const from = Deno.env.get("TWILIO_WHATSAPP_FROM") || SANDBOX_FROM;
  const { when, conf, camera, label } = alertFields(alert);

  const form = new URLSearchParams({
    From: from,
    To: to,
    ContentSid: contentSid,
    ContentVariables: JSON.stringify({
      "1": when,
      "2": conf,
      "3": camera,
      "4": label,
    }),
  });

  const { sid } = await twilioCreateMessage(accountSid, authToken, form);
  return { sid, channel: "whatsapp-business", from };
}

async function sendSms(
  accountSid: string,
  authToken: string,
  body: string,
): Promise<{ sid: string; channel: string; body_sent: string }> {
  // India Twilio trial: Body must be a predefined template name
  // (e.g. sms_internal_alerts), not free-form text.
  const from = Deno.env.get("TWILIO_SMS_FROM") || "+17372508034";
  const to = phoneOnly(
    Deno.env.get("SMS_TO") || Deno.env.get("WHATSAPP_TO") || "",
  );
  const template = Deno.env.get("TWILIO_SMS_TEMPLATE") || "sms_internal_alerts";
  const useTemplate = (Deno.env.get("TWILIO_SMS_USE_TEMPLATE") || "true")
    .toLowerCase() !== "false";

  if (!from || !to) {
    throw new Error(
      "SMS needs TWILIO_SMS_FROM and WHATSAPP_TO (or SMS_TO).",
    );
  }

  // Trial India accounts reject free-form Body — send template name instead.
  const smsBody = useTemplate ? template : body;

  const form = new URLSearchParams({
    From: from.startsWith("+") ? from : `+${from}`,
    To: to.startsWith("+") ? to : `+${to}`,
    Body: smsBody,
  });

  const { sid } = await twilioCreateMessage(accountSid, authToken, form);
  return { sid, channel: "sms", body_sent: smsBody };
}

async function sendAlert(alert: AlertPayload, body: string) {
  const accountSid = Deno.env.get("TWILIO_ACCOUNT_SID");
  const authToken = Deno.env.get("TWILIO_AUTH_TOKEN");
  if (!accountSid || !authToken) {
    throw new Error("Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN");
  }

  const mode = (Deno.env.get("ALERT_CHANNEL") || "whatsapp").toLowerCase();
  const contentSid = Deno.env.get("TWILIO_CONTENT_SID");

  // Prefer sandbox WhatsApp for trial accounts (no Content Builder needed)
  if (mode === "sms") {
    return await sendSms(accountSid, authToken, body);
  }

  if (contentSid && mode === "whatsapp-business") {
    return await sendWhatsAppBusiness(accountSid, authToken, alert);
  }

  // Default path: Sandbox free-form WhatsApp
  try {
    return await sendWhatsAppSandbox(accountSid, authToken, body);
  } catch (waErr) {
    const waMsg = waErr instanceof Error ? waErr.message : String(waErr);

    // Only try SMS if explicitly allowed
    if (mode === "auto") {
      try {
        const sms = await sendSms(accountSid, authToken, body);
        return { ...sms, whatsapp_error: waMsg };
      } catch (smsErr) {
        const smsMsg = smsErr instanceof Error ? smsErr.message : String(smsErr);
        throw new Error(
          `WhatsApp Sandbox failed: ${waMsg}\n` +
            `SMS also failed (common on India trial): ${smsMsg}\n` +
            `Fix: Join Twilio WhatsApp Sandbox from your phone ` +
            `(message the join code to +1 415 523 8886).`,
        );
      }
    }

    throw new Error(waMsg);
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const raw = await req.json() as AlertPayload;
    const alert: AlertPayload = raw.record ?? raw;
    const text = formatMessage(alert);
    const result = await sendAlert(alert, text);

    const alertId = alert.id;
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (alertId && supabaseUrl && serviceKey) {
      const sb = createClient(supabaseUrl, serviceKey);
      await sb
        .from("violence_alerts")
        .update({ whatsapp_status: "sent", whatsapp_error: null })
        .eq("id", alertId);
    }

    return new Response(
      JSON.stringify({ ok: true, ...result, preview: text }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);

    try {
      const raw = await req.clone().json().catch(() => ({})) as AlertPayload;
      const alert = raw.record ?? raw;
      const supabaseUrl = Deno.env.get("SUPABASE_URL");
      const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
      if (alert.id && supabaseUrl && serviceKey) {
        const sb = createClient(supabaseUrl, serviceKey);
        await sb
          .from("violence_alerts")
          .update({ whatsapp_status: "failed", whatsapp_error: msg })
          .eq("id", alert.id);
      }
    } catch {
      // ignore
    }

    return new Response(
      JSON.stringify({ ok: false, error: msg }),
      {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    );
  }
});
