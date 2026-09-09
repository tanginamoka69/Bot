# Telegram 24/7 Receiver Bot

## Mga Feature
- Tumatanggap ng mensahe at files/documents (kasama ang APK) mula sa mga user.
- Ipinapasa (forward) ang natanggap sa admin, kasama ang buod ng user (pangalan, username, user ID, chat ID).
- Puwedeng sagutin ng admin ang user sa pamamagitan lang ng pag-reply sa forwarded na mensahe.
- Text at media broadcast sa lahat ng aktibong user.
- SQLite user database, may bilang ng mensahe kada user.
- `/users` (may pagination), `/stats`, `/ban`, `/unban`, `/admin`.
- Per-user cooldown at broadcast rate limiting para maiwasan ang Telegram flood limits.
- Notification sa admin kapag online na ang bot.
- Render worker configuration.

## Environment variables
| Variable | Paglalarawan |
|---|---|
| `BOT_TOKEN` | Bagong token mula sa BotFather. **HUWAG kailanman i-commit sa Git o ilagay diretso sa code.** |
| `ADMIN_ID` | Telegram user ID ng admin. |
| `BROADCAST_DELAY` | Segundo ng paghihintay sa pagitan ng bawat broadcast message (default 0.05). |
| `USER_COOLDOWN` | Segundo ng cooldown kada user bago tanggapin ulit ang susunod niyang mensahe (default 1.0). |
| `USERS_PAGE_SIZE` | Bilang ng user na ipapakita kada page sa `/users` (default 20). |

⚠️ **Kung naka-expose (nai-publish sa Git, na-screenshot, atbp.) ang dati mong token, i-revoke ito agad sa BotFather (`/revoke` o `/token`) at gumamit ng bago.**

## I-deploy sa Render
Gumawa ng Background Worker gamit ang repository na ito, o gamitin ang `render.yaml`.
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`

### Mahalaga
Ang SQLite file na naka-store sa normal na Render worker filesystem ay hindi garantisadong mananatili sa bawat redeploy/replacement. Para sa matatag na production data, gumamit ng persistent disk o mag-migrate sa PostgreSQL.
