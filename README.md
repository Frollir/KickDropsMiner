# Kick Drops Miner

<p align="center">
  <img src="appimage/pickaxe.png" alt="Kick Drops Miner green pickaxe logo" width="128">
</p>

Kick Drops Miner is a desktop application that collects timed Kick.com drops without
downloading stream video or audio. It discovers available campaigns, selects eligible live
channels, reports watch activity through Kick's viewer websocket, tracks server-side progress,
switches channels when needed, and claims completed rewards.

## Features

- Discovers all campaigns returned by Kick, including category-wide and channel-restricted drops.
- Uses Kick's server-side progress as the source of truth.
- Automatically selects and switches live channels.
- Automatically claims completed rewards.
- Supports priority and exclusion lists.
- Provides inventory, channel, progress, tray, proxy, theme, and autostart controls.
- Includes optional verbose diagnostics in `logs/kick-drops-miner.log` with automatic rotation.
- Stores the imported Kick session locally so it does not need to be selected on every launch.

## Authentication

Kick Drops Miner does not ask for your Kick password. It imports an authenticated browser session:

1. Log in to [Kick.com](https://kick.com) in your browser.
2. Use a local cookies exporter ([chrome](https://chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc?) / [firefox](https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/) extension) to export cookies for `kick.com` in Netscape `cookies.txt` format.
3. Start Kick Drops Miner and press **Import cookies.txt**.
4. Select the exported file.

Only non-expired Kick cookies are retained. The imported file must contain `session_token`.

> The saved `cookies.txt` grants access to your Kick session. Keep it private and do not share it.

## Running From Source

Python 3.10 or newer is required.

Windows:

```bat
setup_env.bat
run_dev.bat
```

Linux/macOS:

```bash
./setup_env.sh
./env/bin/python main.py
```

## Building

Run `build.bat` on Windows or `build.sh` on Linux/macOS after setting up the environment.
The application is packaged with PyInstaller.

GitHub Actions publishes these native development-build artifacts:

- `Kick.Drops.Miner-x86_64.AppImage` for x86-64 Linux.
- `Kick.Drops.Miner-aarch64.AppImage` for ARM64 Linux.
- `Kick.Drops.Miner.macOS-arm64.zip`, containing `Kick Drops Miner.app` for Apple Silicon.

The macOS application is ad-hoc signed but not notarized with an Apple Developer certificate.
Intel macOS builds are not currently published.

## Technical Notes

Kick's official developer API does not currently document Drops. This project therefore uses the
private web endpoints and viewer websocket used by Kick's website. Those interfaces may change.
Requests use `curl_cffi` browser impersonation because ordinary HTTP clients are rejected by
Kick's security policy.

The `kickautodrops-main` directory is retained only as an untracked implementation reference and
is not included in application builds.

## Credits and Support

The Kick modification was created by [Frollir](https://github.com/Frollir). The original Twitch
application was created by [DevilXD](https://github.com/DevilXD).

Project repository: [Frollir/KickDropsMiner](https://github.com/Frollir/KickDropsMiner)

If you find the application useful, you can support its continued development through
[Buy Me a Coffee](https://buymeacoffee.com/frollir).
