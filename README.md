<!-- mcp-name: io.github.millerchou/rocketchat-mcp -->

# rocketchat-mcp

An [MCP](https://modelcontextprotocol.io) server for [Rocket.Chat](https://rocket.chat).
It lets MCP clients (Claude Desktop, Cursor, Claude Code, etc.) send and read
messages, send DMs, search history, upload/download files, and manage channels
on a Rocket.Chat workspace over stdio.

> Actively maintained fork of
> [elieworkspace/rocketchat-mcp](https://github.com/elieworkspace/rocketchat-mcp),
> adding Personal Access Token auth, more tools, and reliability/security
> improvements. See [NOTICE](NOTICE) for attribution.

## Tools

| Tool | Description |
| --- | --- |
| `send_message_in_channel` | Send a message to a channel |
| `send_direct_message` | Send a direct message to a user |
| `delete_message` | Delete a message (your own, unless the role has force-delete) |
| `get_channel_messages` | Read history of a channel/group/DM; supports `offset` paging and accepts a room ID or name |
| `search_messages` | Keyword search within a room (`chat.search`) |
| `get_unread` | List rooms with unread messages and their latest content |
| `send_file` | Upload a file to a channel or `@user` |
| `download_attachment` | Download a message's attachments to local files |
| `list_all_rooms` | List channels, groups and DMs &lowast; |
| `list_users` | List users &lowast; |
| `get_user_info` | Get a user's profile |
| `create_channel` | Create a channel |

### Quoted messages and attachments

Message listings include quoted text and uploaded files inside quotes. A quote is a
snapshot shared in the containing message; the original room may no longer be accessible.
Use the **containing message ID** when downloading a quoted attachment. You do not need
to read the original room first.

`download_attachment(message_id, attachment_id)` downloads the selected file ID shown
in the listing. Omitting `attachment_id` retains the existing behavior of downloading
all supported attachments, now including quoted files. The server still enforces file
access permissions. File references must originate from this Rocket.Chat server's
upload path; redirects to file storage do not receive Rocket.Chat authentication headers.
Downloads use unique temporary filenames and do not overwrite prior downloads.

HTTP errors include the server's error type and message when available, so a missing
message, an access failure, and a network failure are not reduced to the same diagnosis.
Configured authentication secrets are excluded from these error summaries.

&lowast; `list_all_rooms` and `list_users` call workspace-wide endpoints
(`channels.list` / `users.list`) that require admin or the corresponding
`view-*` permission. Every other tool works for a normal chat user.

## Authentication

A normal chat user is enough for the core tools. A **Personal Access Token** is
recommended — it keeps the token out of process arguments:

| Variable | Description |
| --- | --- |
| `ROCKETCHAT_SERVER_URL` | Workspace URL, e.g. `https://chat.example.com` |
| `ROCKETCHAT_USER_ID` | Your Rocket.Chat user ID |
| `ROCKETCHAT_AUTH_TOKEN` | Personal Access Token |
| `ROCKETCHAT_WATCHDOG_INTERVAL` | (optional) orphan-watchdog interval in seconds, default `60` |

Username/password is also supported via `--username` / `--password`.
Use `--no-verify-ssl` for self-signed certificates.

## Usage

### Run with uvx

```bash
uvx rocketchat-mcp --server-url https://chat.example.com
```

To run the latest unreleased code straight from GitHub instead:

```bash
uvx --from git+https://github.com/millerchou/rocketchat-mcp rocketchat-mcp --server-url https://chat.example.com
```

### Client configuration

```json
{
  "mcpServers": {
    "rocketchat": {
      "command": "uvx",
      "args": ["rocketchat-mcp"],
      "env": {
        "ROCKETCHAT_SERVER_URL": "https://chat.example.com",
        "ROCKETCHAT_USER_ID": "your_user_id",
        "ROCKETCHAT_AUTH_TOKEN": "your_personal_access_token"
      }
    }
  }
}
```

### Local development

```bash
git clone https://github.com/millerchou/rocketchat-mcp
cd rocketchat-mcp
uv run rocketchat.py --server-url https://chat.example.com \
  --auth-token "$ROCKETCHAT_AUTH_TOKEN" --user-id "$ROCKETCHAT_USER_ID"
```

## Reliability

Run the offline attachment and API error tests with:

```bash
uv run python -m unittest discover -s tests -v
```

The tests use synthetic messages and an HTTP mock transport; no chat account is needed.

Persistent HTTP connection pool, room-endpoint caching, log rotation (1 MB),
and an orphan watchdog that self-exits when the MCP client process dies.

## License

Modifications in this fork are released under the [MIT License](LICENSE).
This is a fork of upstream code originally published without a license; see
[NOTICE](NOTICE) for details.
