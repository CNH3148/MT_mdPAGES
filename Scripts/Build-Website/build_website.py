import argparse
import os
import shutil
import re
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser(description="Build static website for GitHub Pages from local app.")
    parser.add_argument("--app-dir", type=str, default=".", help="Path to the original app directory")
    parser.add_argument("--data-dir", type=str, default="data_MD", help="Path to the Markdown data directory")
    parser.add_argument("--output-dir", type=str, default="data_MD_website", help="Path to the output website directory")
    
    args = parser.parse_args()
    
    app_dir = Path(args.app_dir)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    
    # 1. Check if source directories exist
    if not app_dir.exists():
        print(f"Error: App directory '{app_dir}' not found.")
        sys.exit(1)
        
    if not data_dir.exists():
        print(f"Error: Data directory '{data_dir}' not found.")
        sys.exit(1)
        
    # Add Scripts directory to sys.path to import md_engine.cache_builder
    # Assuming this script is located at Scripts/Build-Website/build_website.py
    # and md_engine is located at Scripts/md_engine
    scripts_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(scripts_dir))
    try:
        from md_engine.cache_builder import build_cache
    except ImportError as e:
        print(f"Error importing cache_builder: {e}")
        sys.exit(1)

    print(f"==> Building static website to '{output_dir}'")
    
    # 2. Prepare output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Copy attachments
    attachments_src = data_dir / "_attachments"
    attachments_dst = output_dir / "attachments"
    if attachments_src.exists():
        print(f"Copying attachments from {attachments_src}...")
        shutil.copytree(attachments_src, attachments_dst, dirs_exist_ok=True)
        
    # 4. Build Cache (JSON)
    cache_dir = output_dir / "data_cache"
    print(f"Building JSON cache from {data_dir} to {cache_dir}...")
    build_cache(data_dir, cache_dir)

    print("==> Static website build completed successfully!")

if __name__ == "__main__":
    main()
