# n8n + Remotion Video Automation Pipeline

An automated pipeline for ingesting component payloads, generating and registering Remotion compositions, and rendering high-resolution videos (locally or distributed via Modal).

## Repository Overview

- **`download_components.py`**: Downloads component payload files from URLs provided in `ComponentLinks.csv`.
- **`prepare_components.py`**: Parses component payloads and generates isolated Remotion components into `src/videos/` and entries into `src/entries/`.
- **`mark_registered.py`**: Validates and updates registration status in the component tracking CSV.
- **`remotion-video-creation/`**:
  - **`modal_render.py`**: Cloud-scale video rendering pipeline using [Modal](https://modal.com).
  - **`render_local.py`**: Local CLI video renderer with retry logic and resolution checks.
  - **`download_renders.py`**: Safely downloads completed video renders from Modal volume storage.
  - **`tools/`**: Helper utilities for metadata generation, runtime validation, and post-render cleanup.

## Project Structure

```
├── AGENTS.md
├── ComponentLinks.csv
├── components/
│   └── .gitkeep
├── download_components.py
├── mark_registered.py
├── prepare_components.py
└── remotion-video-creation/
    ├── modal_render.py
    ├── render_local.py
    ├── download_renders.py
    ├── renders/
    │   └── .gitkeep
    ├── src/
    │   ├── Root.tsx
    │   ├── index.ts
    │   ├── index.css
    │   └── videos/
    │       └── .gitkeep
    └── tools/
        ├── check-generated-runtime.mjs
        ├── cleanup_step6.py
        ├── downscale-square-videos.ps1
        ├── generate-stock-metadata.mjs
        ├── import-component-payloads.mjs
        └── render-validation-stills.mjs
```

## Setup & Usage

### 1. Install Dependencies
```bash
cd remotion-video-creation
npm install
```

### 2. Add Component URLs
Add your component asset download URLs to `ComponentLinks.csv` (one URL per line).

### 3. Download Components
```bash
python download_components.py
```

### 4. Prepare & Register Remotion Compositions
```bash
python prepare_components.py
```

### 5. Render Videos
- **Locally:**
  ```bash
  cd remotion-video-creation
  python render_local.py
  ```
- **Modal (Cloud):**
  ```bash
  cd remotion-video-creation
  modal run modal_render.py
  python download_renders.py
  ```
