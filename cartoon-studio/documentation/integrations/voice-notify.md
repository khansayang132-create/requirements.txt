# Voice Notify for Codex — Compatibility and Setup

Voice Notify is an optional local/offline Codex lifecycle alert integration. It is not cartoon narration or a cloud TTS provider.

## Current environment result

The build environment used for this project is Linux x86_64. The installed Voice Notify setup workflow documents macOS and Windows settings scripts only. Therefore setup in this environment is **BLOCKED / unsupported platform**, not installed or tested. No hook trust state was changed.

## Supported setup requirements

- macOS or Windows host.
- Codex CLI version `0.145.0` or newer.
- Use the Voice Notify plugin's own settings script and its resolved installed plugin root.
- Supported voice choices: female/male. Languages: Korean, Japanese, English, Russian, Simplified Chinese.
- The user must hear the test sound, manually inspect/trust the hook, enter `/hooks` in Codex, fully restart Codex, and verify a lifecycle event.

Never auto-enter `/hooks`, edit hook trust stores, bypass hook trust, or claim setup complete from configuration alone.

## Official plugin workflow

Use the installed `codex-voice-notify/voice-notify-settings` skill on the user's supported host. Its setup command must be run with the exact verified Codex CLI path and the plugin's bundled script. This repository intentionally does not copy or emulate the plugin's private setup scripts.
