# River City Systems

A Python Discord bot for River City Roleplay (server `1491365342646112386`).

## Run

1. Use Python 3.10 or newer. Install dependencies with `python -m pip install -r requirements.txt`.
2. In the Discord Developer Portal, open your application's **Bot** settings and enable **Server Members Intent** and **Message Content Intent**.
3. Invite the bot to River City Roleplay with the bot scope. Grant View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Kick Members, Ban Members, and Moderate Members. Put its role above the members it should moderate.
4. Open the included `.env` beside `app.py` and paste your bot token after `DISCORD_TOKEN=`. You can also use your host's environment or secrets settings. Start the bot with `python app.py`. On Pterodactyl use `app.py` as the startup file. Keep the filled-in file private.
5. Configure the ticket permissions below. The bot places the assistance panel on startup. Staff with Manage Server can restore it with `.ticketpanel`.

## Channels

| Purpose | Discord ID |
| --- | --- |
| Welcome messages | 1572082493715386398 |
| Assistance panel | 1572082489743249591 |
| Ticket destination | 1572082450232774727 |

If the destination is a **category**, grant the bot Manage Channels and Manage Roles there so it can create private channels with permission overwrites. Set the optional `SUPPORT_ROLE_ID` environment variable to your support role ID. Without it, roles with server-wide Manage Channels receive access. Administrators can always access tickets. Restart after changing the setting. Permission overwrites are assigned when a ticket opens.

If the destination is a **text channel**, grant the bot Create Private Threads, Send Messages in Threads, and Manage Threads there. Requesters need View Channel, Read Message History and Send Messages in Threads. Give ticket staff View Channel, Read Message History, Send Messages in Threads and Manage Threads in that parent so they can see private requests. Users with Manage Threads in the parent can claim tickets. Inactive threads can auto-archive under Discord’s parent-channel settings. Members can open a fresh request once their previous thread is archived.

Members can have one active ticket each. Staff can claim a ticket. Closing deletes the channel or thread and its messages. The requester and ticket staff can use Close. Run one bot instance per token.

## Commands

| Command | Required permission |
| --- | --- |
| `.help` | Any member |
| `.kick @member [reason]` | Kick Members |
| `.ban @member [reason]` or `.unban user_id [reason]` | Ban Members |
| `.timeout @member minutes [reason]` or `.untimeout @member [reason]` | Moderate Members |
| `.clear amount` (1–100) | Manage Messages in that channel |
| `.ticketpanel` | Manage Server |
