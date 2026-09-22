This is the Agentic Worklow and u are the orchestrator here. 

You have 5 Task to do 1 by 1.


1. User WIll provide with Google Drive File links Your task is to download all of those files ( Don't miss any single link ) After downloading Save all of those files in components folder. Than review Links and number of newly downloaded files to verify that nothing missed.
2. Analyze the component folder every single file in it and than write CSV file in the same component folder which will contains the filenames and status of that file.
3. From CSV file U will pick unregistered component files and than create its component in the src.videos folder and than register it in Root.tsx file. After registring there Register in the modal_render.py file as well. 
4. Here u will review that component so it must contain any issue or lint error. After it U will mark it registered in the CSV file.
5. Once All component are Done as registered Give me Modal command that I can run by myself and render the videos. Before marking a render as verified, inspect the output resolution and confirm it is valid for the intended upload platform.

6. Post-render cleanup: only after confirming every component has a valid verified render, permanently delete its TS/TSX source and related component payload files and remove its registrations. Never modify, move, or delete any rendered video or video output without the user's explicit permission.

## Adobe Stock video resolution rule

- Square videos must be rendered directly at 2160 x 2160 (or 1080 x 1080). Do not upload 3840 x 3840 square MP4 files; Adobe Stock rejects that resolution.
- Horizontal UHD videos must be rendered at 3840 x 2160. Vertical UHD videos must be rendered at 2160 x 3840.
- H.264 MP4 at a standard frame rate is supported, but a successful local render is not enough: verify the final dimensions with FFprobe before recording `rendered_verified`.
- If a render is technically valid but does not meet the upload platform's resolution rules, record it as `rendered_needs_rerender`; do not run cleanup or delete its sources/registrations.

## Existing render handling

- Preserve all existing rendered MP4 files unless the user explicitly authorizes deletion.
- Files at 3840 x 2160 are valid 4K horizontal deliverables and may be uploaded.
- Files at 3840 x 3840 are unsupported for Adobe Stock. 


# Critical Role for Already Rendered Videos  
Do not change or look at anything present in the rendered folder. Instead, for every new request, create a new folder inside the render folder for new videos to render. Don't try to edit or add to or remove anything inside the rendered folder. Don't even look at it, because there are already my existing rendered videos, so we don't need to change anything there. 
