# Troubleshooting

- `cartoon-studio doctor`: shows local tools and whether provider variables are present; it does not authenticate against providers.
- `ProviderNotConfigured`: add the named key to `.env` after enabling that provider.
- `SpendNotApproved`: review provider pricing and credits, then explicitly run the future generation workflow with approval.
- Blender absent: install Blender separately; this package does not download large 3D software automatically.
- FFmpeg absent: install FFmpeg and ensure both `ffmpeg` and `ffprobe` are on PATH.
