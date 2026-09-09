# 🔒 Pansariling Gabay (Ako Lang Dapat Makakakita Nito)

⚠️ Ang file na ito ay hindi ipapasok sa GitHub (nasa `.gitignore` na). Sarili mo lang na kopya ito
sa phone/device mo — para lang paalala, huwag ipapadala o i-share kahit kanino.

---

## 🔑 Mga kailangan mong secret

| Ano | Saan makukuha | Ilagay saan |
|---|---|---|
| `BOT_TOKEN` | @BotFather sa Telegram → `/newbot` o `/mybots` | Render → Environment |
| `ADMIN_ID` | @userinfobot sa Telegram | Render → Environment |

**Huwag i-type/i-save ang mga ito sa loob ng `bot.py` o kahit saang file na ipa-push mo sa GitHub.**
Sa Render Environment tab lang dapat ito ilagay.

---

## 📋 Deployment steps (buod)

1. I-unzip ang project sa phone.
2. Gumawa ng **Private** repo sa github.com → "uploading an existing file" → i-upload lahat ng files
   maliban sa mga naka-`.gitignore` (kasama na itong file na ito).
3. Sign up sa render.com gamit ang GitHub account.
4. Render Dashboard → **New +** → **Blueprint** → piliin ang repo mo → **Apply**.
5. Sa service → **Environment** tab → ilagay ang `BOT_TOKEN` at `ADMIN_ID` → **Save Changes**.
6. Panoorin ang **Logs** tab, hanapin: `Bot polling started.`
7. I-check ang Telegram — dapat may "🟢 Online na ang bot." na message.

---

## 🛠 Admin Commands (gamitin sa loob ng Telegram, chat mo mismo sa bot)

| Command | Ginagawa |
|---|---|
| `/admin` | Ipapakita ang listahan ng lahat ng admin commands |
| `/users [page]` | Listahan ng users (pangalan, username, user ID, status, bilang ng mensahe). Halimbawa: `/users 2` para sa page 2 |
| `/stats` | Kabuuang bilang ng users, active, banned, at total messages |
| `/ban USER_ID` | I-ban ang isang user (hindi na sila makakapagpadala) |
| `/unban USER_ID` | Alisin ang ban |
| `/broadcast TEXT` | Magpadala ng text sa lahat ng aktibong (di-banned) users |
| (ipadala media → i-reply ito ng) `/broadcast` | I-broadcast ang larawan/video/file sa lahat |

**Paano sumagot sa isang user:** i-reply lang ang forwarded na mensahe nila (yung notification na
napunta sayo) — kahit anong isulat mo o ipadalang file doon, direkta itong mapupunta sa kanila.

---

## 🩹 Kung may problema

- **Walang response ang bot** → i-check ang Render Logs, baka mali ang `BOT_TOKEN` o hindi pa
  nag-deploy nang tama.
- **Nawala ang users list pagkatapos mag-redeploy** → normal ito sa free tier (walang persistent
  disk). Kung gusto mong maging permanente, kailangan mag-upgrade sa paid Render plan.
- **Naka-block ka ng user** → makikita mo sa error message kapag sumagot ka sa kanila
  ("Hindi naabot ang user").
- **Na-expose ang token mo (nasa screenshot, nai-share, atbp.)** → agad na `/revoke` sa BotFather,
  kumuha ng bago, i-update sa Render Environment tab.

---

## ⚠️ MAHALAGA: Free Web Service = natutulog pagkatapos ng 15 minutong walang traffic

Dahil "Web Service" (hindi "Background Worker") ang deployment type para libre, awtomatikong
"nagpapa-spin down" (natutulog) ang Render sa free Web Services pagkatapos ng ~15 minutong walang
papasok na HTTP request. Kapag natulog ang service, hindi rin tatakbo ang Telegram polling, kaya
**hindi ito totoong 24/7** hangga't walang pumipindot/nag-a-access sa dummy web address niya.

**Solusyon:** gumamit ng libreng "uptime pinger" service (hal. **UptimeRobot**, **cron-job.org**,
o **Better Uptime**) na mag-a-access sa Render URL ng bot mo (makikita ito sa Render dashboard,
parang `https://telegram-receiver-bot-xxxx.onrender.com`) kada 5-10 minuto, para hindi ito
matulog. Libre rin ang mga serbisyong ito.

Kung sawa ka na sa ganitong workaround at gusto mo talagang tunay na Background Worker (walang
spin-down, walang kailangang pinger), kailangan mong mag-upgrade sa paid Render plan
(~$7/buwan pataas).
