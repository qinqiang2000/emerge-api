# excalidraw self-hosted runtime assets

Copied from `node_modules/@excalidraw/excalidraw@0.18.1/dist/prod/fonts/` (the
bundle resolves `./fonts/...` font URLs against `window.EXCALIDRAW_ASSET_PATH`
— set to `/excalidraw-assets/` in `src/components/Board/boardAssets.ts`).
Self-hosted because the default CDN fallback is unreliable on the prod VPS.
On upgrading `@excalidraw/excalidraw`, re-copy `dist/prod/fonts/` here.
~13MB on disk, but font subsets are fetched lazily per unicode-range — only
glyph ranges actually drawn on a board are downloaded.
