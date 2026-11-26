# OpenQuartz Studio

Native video editor for Windows x64 and macOS (Apple Silicon and Intel).
See [Studio documentation](apps/open_quartz_video_editor/README.md).

Run npm ci, then npm run dev:video-editor. Use npm run test:video-editor:portable
for Rust tests and npm run package:video-editor for a portable archive.

Shared OpenQuartz host sources and the media fixture in this checkout are pinned
copies from the migration baseline 24ee19b. Rust libraries are pinned Git dependencies.
The Studio repository retains its own test and release entry points.
