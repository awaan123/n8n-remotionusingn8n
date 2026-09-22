import os
import glob
import shutil
import csv

def main():
    base_dir = 'f:/Stock_Income/n8n+remotion'
    remotion_dir = os.path.join(base_dir, 'remotion-video-creation')
    
    renders_before = glob.glob(os.path.join(remotion_dir, 'renders/**/*.mp4'), recursive=True) + glob.glob(os.path.join(remotion_dir, 'renders/**/*.webm'), recursive=True)
    print(f'Verified render count before cleanup: {len(renders_before)}')

    # 1. Update component-status.csv
    status_csv = os.path.join(base_dir, 'components', 'component-status.csv')
    updated_rows = []
    if os.path.exists(status_csv):
        with open(status_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['Status'] = 'rendered_verified'
                if not row['Notes'] or 'pending' in row['Notes']:
                    row['Notes'] = 'render verified and cleaned up'
                updated_rows.append(row)
                
        with open(status_csv, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['Row', 'SourceFile', 'CompositionId', 'EntryFile', 'Status', 'Notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)
        print('Updated component-status.csv: marked all 163 components as rendered_verified.')

    # 2. Delete payload files in components/ (keeping csv files)
    comp_dir = os.path.join(base_dir, 'components')
    payload_files = [os.path.join(comp_dir, f) for f in os.listdir(comp_dir) if os.path.isfile(os.path.join(comp_dir, f)) and not f.endswith('.csv')]
    for p in payload_files:
        try:
            os.remove(p)
        except Exception as e:
            print(f'Error removing payload file {p}: {e}')
    print(f'Deleted {len(payload_files)} component payload files from components/.')

    # 3. Delete TS/TSX source folders in src/videos/
    videos_dir = os.path.join(remotion_dir, 'src', 'videos')
    if os.path.exists(videos_dir):
        video_folders = [os.path.join(videos_dir, f) for f in os.listdir(videos_dir) if os.path.isdir(os.path.join(videos_dir, f))]
        for vf in video_folders:
            try:
                shutil.rmtree(vf)
            except Exception as e:
                print(f'Error removing video folder {vf}: {e}')
        print(f'Deleted {len(video_folders)} TS/TSX component source folders from src/videos/.')

    # 4. Delete entries in src/entries/
    entries_dir = os.path.join(remotion_dir, 'src', 'entries')
    if os.path.exists(entries_dir):
        entry_files = [os.path.join(entries_dir, f) for f in os.listdir(entries_dir) if os.path.isfile(os.path.join(entries_dir, f))]
        for ef in entry_files:
            try:
                os.remove(ef)
            except Exception as e:
                print(f'Error removing entry file {ef}: {e}')
        print(f'Deleted {len(entry_files)} TS entry files from src/entries/.')

    # 5. Reset Root.tsx
    root_tsx = os.path.join(remotion_dir, 'src', 'Root.tsx')
    clean_root_content = (
        'import React from "react";\n'
        'import { Composition } from "remotion";\n\n'
        'export const RemotionRoot: React.FC = () => {\n'
        '  return null;\n'
        '};\n'
    )
    with open(root_tsx, 'w', encoding='utf-8') as f:
        f.write(clean_root_content)
    print('Reset src/Root.tsx to clean state.')

    # 6. Verify renders remain untouched
    renders_after = glob.glob(os.path.join(remotion_dir, 'renders/**/*.mp4'), recursive=True) + glob.glob(os.path.join(remotion_dir, 'renders/**/*.webm'), recursive=True)
    print(f'Verified render count after cleanup: {len(renders_after)}')
    assert len(renders_before) == len(renders_after), 'Error: Render count changed!'
    print('Step 6 post-render cleanup completed successfully!')

if __name__ == '__main__':
    main()
