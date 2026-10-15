# WhatsApp alerts via Supabase (setup)

When violence is detected, the monitor:
1. Saves local snapshot/clip
2. Inserts a row into Supabase `violence_alerts`
3. Calls Edge Function `send-violence-whatsapp` → Twilio sends WhatsApp

Message example:
  ⚠️ Possible Violence Detected
  Time: 11 Aug 2026, 01:50:22 PM
  Confidence: 87.3%
  Camera: 122.175.45.21 (ch 1)

---

## 1. Create Supabase project

1. Go to https://supabase.com → New project
2. Open **SQL Editor**, paste and run `supabase/schema.sql`
3. Copy from **Project Settings → API**:
   - Project URL → `SUPABASE_URL`
   - `anon` key and `service_role` key

## 2. Twilio WhatsApp (easiest to start)

1. Sign up at https://www.twilio.com/try-twilio
2. Open **Messaging → Try it out → Send a WhatsApp message** (Sandbox)
3. From your phone WhatsApp, send the join code shown (e.g. `join <word>`) to the sandbox number
4. Note:
   - Account SID
   - Auth Token
   - Sandbox From number: `whatsapp:+14155238886`
   - Your phone as To: `whatsapp:+91XXXXXXXXXX`

## 3. Deploy the Edge Function

Install CLI if needed:
```bash
brew install supabase/tap/supabase
supabase login
supabase link --project-ref YOUR_PROJECT_REF
```

Set secrets:
```bash
cd /Users/sonamdobriyal/Test/live_feed
supabase secrets set \
  TWILIO_ACCOUNT_SID=ACxxxx \
  TWILIO_AUTH_TOKEN=your_auth_token \
  TWILIO_WHATSAPP_FROM=whatsapp:+14155238886 \
  WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
```

Deploy:
```bash
supabase functions deploy send-violence-whatsapp --no-verify-jwt
```

(Or keep JWT verification and call with the anon/service key — the Python client already sends auth.)

## 4. Configure local .env

```bash
cp .env.example .env
# edit .env with SUPABASE_URL + keys
```

```bash
pip3 install supabase python-dotenv
```

## 5. Test WhatsApp (no camera needed)

```bash
python3 violence_monitor.py --test-whatsapp
```

You should get a WhatsApp on your phone and a new row in Supabase table `violence_alerts`.

## 6. Run live monitor

```bash
python3 violence_monitor.py
```

On detection you will see:
```
  ALERT saved → alert_....jpg
  [notifier] Saved to Supabase id=...
  [notifier] WhatsApp function response: ...
```

Disable WhatsApp temporarily:
```bash
python3 violence_monitor.py --no-whatsapp
```

---

## Optional: Database Webhook (auto-send on insert)

Instead of Python invoking the function, you can:
Dashboard → Database → Webhooks → Create
- Table: `violence_alerts`
- Event: INSERT
- Destination: Edge Function `send-violence-whatsapp`

Then Python only needs to insert the row.

---

## No Content Builder? Use Sandbox WhatsApp or SMS

Twilio does **not** give free reusable “base” WhatsApp templates without
Content Template Builder / WhatsApp Business approval.

Use one of these instead:

### Option A — WhatsApp Sandbox (free-form, no template)

1. Twilio Console → Messaging → Try it out → **Send a WhatsApp message**
2. On your phone, WhatsApp the join code to **+1 415 523 8886**
3. Set secrets (already applied if you followed Agent setup):

```bash
supabase secrets set \
  TWILIO_WHATSAPP_FROM=whatsapp:+14155238886 \
  TWILIO_SMS_FROM=+17372508034 \
  ALERT_CHANNEL=auto
```

4. Test:
```bash
python3 violence_monitor.py --test-whatsapp
```

### Option B — SMS fallback (works without WhatsApp templates)

Same secrets as above. With `ALERT_CHANNEL=auto`, if WhatsApp fails the
function sends an SMS from `TWILIO_SMS_FROM` to your phone.

Force SMS only:
```bash
supabase secrets set ALERT_CHANNEL=sms
```

### Option C — Custom Content Template (later)

When you get Content Builder access, create a template and set
`TWILIO_CONTENT_SID=HXxxxx`.

## ContentSid Required (WhatsApp Business number)

If you see `ContentSid Required`, your `TWILIO_WHATSAPP_FROM` is a **Business**
WhatsApp sender (not sandbox freeform). Meta/Twilio require an approved
**Content Template** for business-initiated alerts.

### Create the template in Twilio

1. Twilio Console → **Content Template Builder** (Messaging → Content)
2. Create a template, e.g. name `violence_alert`, language English
3. Body (use exactly these variables):

```
Possible Violence Detected
Time: {{1}}
Confidence: {{2}}
Camera: {{3}}
Label: {{4}}
Please verify on the live feed.
```

4. Submit for WhatsApp approval (can take minutes–hours)
5. Copy the **Content SID** (starts with `HX...`)

### Set the secret and redeploy

```bash
supabase secrets set TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxx
supabase functions deploy send-violence-whatsapp
python3 violence_monitor.py --test-whatsapp
```

### Alternative: use Twilio Sandbox (quick testing only)

```bash
supabase secrets set TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
# On your phone WhatsApp, send the join code to +1 415 523 8886
# Then remove ContentSid if you set it, or leave Body mode (no ContentSid)
```

## Production notes

- Twilio Sandbox is for testing only; recipients must join the sandbox.
- For production WhatsApp Business, Meta requires **approved message templates** for business-initiated alerts.
- Never commit `.env` or the `service_role` key.
