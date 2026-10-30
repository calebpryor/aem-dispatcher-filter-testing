## ModSecurity Rules Directory

This directory is mounted into the container at `/etc/httpd/modsecurity.d/rules/`. ModSecurity 2.9 (Rocky Linux 8 package) runs on the dispatcher vhost (port 80). It sees each request before the dispatcher filters do.

**No rules are built into the image.** Copy your own rule set here: the `*.conf` rule files plus any `*.data` files they reference (`@pmFromFile`, `@ipMatchFromFile`). Everything in this folder except this README is git-ignored, so private rule sets are not committed.

```
modsecurity/
  README.md
  some_rule.conf
  some_rule_logonly.conf          ← same rules, log-only variant
  some_list.data                  ← referenced by the rules (relative to the .conf)
  local_rules/my_custom.conf      ← sub-directories are fine
```

### Choosing what loads
Pick a mode for each rule on the control panel **ModSecurity** tab:

| Files | Modes |
|---|---|
| `name.conf` + `name_logonly.conf` (a pair that shares rule IDs) | **Block**, **Log only**, or **Off**. Only one variant is ever loaded, like symlinking one of them into `activated_rules/` in production. |
| any other `*.conf` | **On** or **Off** |

New files default to **Block** (pairs) or **On** (singles). Choices are saved in `filters/.prefs.json`, so this folder stays an exact copy of your files.

Load order (mirrors a production `mod_security.conf`): files at the top of this folder, then sub-directories, then `local_rules/`, each sorted by name.

### Safety checks
- Every change is checked with `httpd -t` against a staged copy before it goes live. That covers mode changes, saves from the panel, and files edited on the host (picked up by the file watcher). If the check fails, the previous config stays loaded and the error is shown in the panel or in `docker compose logs`.
- Rule IDs that appear in more than one loaded file are flagged (ModSecurity refuses to start with duplicates).
- If a loaded rule references a `.data` file that doesn't exist, an empty placeholder is created next to it, as the production RPM install does.

### Baseline
The sandbox baseline has no `SecRule`s and no request body limits. Audit logging covers only 403 responses (`SecAuditLogRelevantStatus "^403"`). Include your own `.conf` files for body-limit or audit tweaks. The engine mode (On / DetectionOnly / Off) and debug log level set in the panel load last and override your files.

### Testing notes
- Test requests come from `127.0.0.1` inside the container. IP-allowlist rules see that address unless you send `X-Forwarded-For` (and your rules trust it).
- Rules that skip certain hosts (for example author domains) can be tested with `-H 'Host: author.example.com'`.
- Use `--rule <id>` on the Testing tab to check that a specific rule fired. This works for log-only rules, which don't change the status code.
- `logs/error_log` has a `ModSecurity: …` line for every rule match. `logs/modsec_audit.log` has full details of blocked (403) requests.
