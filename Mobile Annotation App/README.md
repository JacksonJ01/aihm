# AIHuMo Mobile Annotation App

This is a browser/PWA client for annotating a custom video from a phone or tablet.

## What it supports

- Selects a custom local video with the phone's file picker.
- Frame navigation with previous/next buttons, Left/Right arrows, configurable jump size, and W/S range shortcuts when a physical keyboard is available.
- Green-highlighted current thumbnail and nearby-frame strip.
- Activity, set, repetition, phase, form, and other interval layers.
- Layer-aware fields: values that a layer cannot edit are disabled but are filled from the selected annotation or the surrounding timeline context.
- Dynamic movement type and exercise dropdowns.
- Multi-select issue types, issue categories, and affected joints with visible summaries.
- Editing and clearing an existing temporal annotation row.
- JSON import for existing annotations or an optional session/feature timing export.
- Separate annotation/session JSON export so the original feature Parquet remains unchanged.
- PWA installation and app-shell caching when hosted over HTTPS.

## Run locally

This folder is intentionally dependency-free. From this directory, use any static server, for example:

```powershell
python -m http.server 4173
```

Then open `http://localhost:4173` in a browser. Service workers and install prompts require HTTPS or localhost.

## Phone workflow

1. Deploy this folder as its own static project, or configure the hosting project's root directory as `Mobile Annotation App`.
2. Open the HTTPS URL on the phone.
3. Use the browser menu's **Add to Home Screen** or the in-app **Install app** button.
4. Choose a video from the phone's files/photos.
5. Optionally choose a session JSON or existing annotation JSON.
6. Save or export the annotation JSON when finished.

## Data boundary

This first mobile client performs annotation in the browser. It does not run the laptop MediaPipe processing pipeline and does not rewrite canonical Parquet. For full cloud synchronization, the next step is to connect this client to authenticated storage/API endpoints so processed video, feature manifests, and annotation versions can be uploaded and reopened across devices.
