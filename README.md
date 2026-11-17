# River City Roleplay

## Start on Render

1. Put app.py, panels.py, requirements.txt, render.yaml and the entire assets folder at the root of your GitHub repository. Keep your filled-in .env private.
2. In Render choose **New → Blueprint**, connect the repository and enter DISCORD_TOKEN when prompted. Review the price before creating the Starter background worker. This configuration runs one continuous process with no inbound web port.
3. For an existing **background worker**, use Python, build command `python -m pip install -r requirements.txt`, start command `python app.py`, and set DISCORD_TOKEN under Environment. Stop other copies using the same token before starting the worker.
4. In Discord Developer Portal enable Server Members Intent and Message Content Intent. Invite the bot to server 1491365342646112386. For local use, install requirements and run `python app.py` with the included .env beside it.

## Panels and permissions

| Panel | Discord channel |
| --- | --- |
| Dashboard | 1492006832779165756 |
| Assistance | 1572082489743249591 |
| Ticket destination | 1572082450232774727 |
| Welcome messages | 1572082493715386398 |

The bot publishes both panels at startup, upgrades its earlier assistance panel in place, and reattaches its buttons and menus after a restart. Members need View Channel and Read Message History in the panel channels. Grant the bot View Channel, Read Message History, Send Messages, Attach Files and Embed Links there. Change Nickname lets it display as River City Roleplay in this server. The global application name can be changed separately in Discord Developer Portal.

**General Support** handles questions and reports. **High Rank Support** handles sensitive requests. Both collect a subject and details, prevent duplicate active requests in that queue, and include staff claim and requester/staff close buttons. Closing deletes the room and its messages. An open general request does not block an unrelated management request.

For a category destination the bot creates a private text channel underneath. For a text destination, general tickets use private threads and management tickets use separate private text channels alongside that parent. This keeps users with Manage Threads on the general parent out of management conversations. Discord administrators retain access. Grant the bot Manage Channels and Manage Roles at the destination and its parent category, and allow it to send messages and read history. For threads also grant Create Private Threads, Manage Threads and Send Messages in Threads. Requesters need View Channel, Read Message History and Send Messages in Threads on the parent. General staff who handle thread tickets need Manage Threads and Send Messages in Threads there.

High Rank Support uses role **1572082345949790311** by default. A missing configured role prevents a sensitive ticket from opening. SUPPORT_ROLE_ID optionally selects staff for general channel tickets. Without it, roles with server-wide Manage Channels receive access. Existing open tickets keep their original permissions. Configure the bot role above any roles it assigns and members it moderates. Give it Kick Members, Ban Members, Moderate Members and Manage Messages to enable moderation.

## Dashboard options

The rules menu contains editable starter guidelines in RULES in panels.py. Replace the vehicle and booster guidance with your own lists when available. Notification options cover Session, Event, Staff, Giveaway and News. The bot uses or creates matching permission-free roles named, for example, “Session Notification”. To use specific roles, set SESSION_NOTIFICATION_ROLE_ID, EVENT_NOTIFICATION_ROLE_ID, STAFF_NOTIFICATION_ROLE_ID, GIVEAWAY_NOTIFICATION_ROLE_ID or NEWS_NOTIFICATION_ROLE_ID. These are opt-in notification roles, including Staff Notification. Give the bot Manage Roles. It rejects roles granting server or channel permissions.

The Support Desk link is built in. Set GUIDEBOOK_URL, STAFF_APPLICATION_URL and BAN_APPEAL_URL to your actual HTTPS links to enable those buttons. Restart after editing environment settings. For an appeal form intended for banned users, use a link they can access outside the server.

## Commands

| Command | Who can use it |
| --- | --- |
| `.cmds`, `.commands`, `.help` | All members |
| `.dashboard`, `.ticketpanel` | Manage Server |
| `.kick @member [reason]` | Kick Members |
| `.ban @member [reason]`, `.unban user_id [reason]` | Ban Members |
| `.timeout @member minutes [reason]`, `.untimeout @member [reason]` | Moderate Members |
| `.clear amount` (1–100) | Manage Messages |
