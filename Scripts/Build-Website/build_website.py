import argparse
import os
import shutil
import re
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser(description="Build static website for GitHub Pages from local app.")
    parser.add_argument("--app-dir", type=str, default="app", help="Path to the original app directory")
    parser.add_argument("--data-dir", type=str, default="app/data_MD", help="Path to the Markdown data directory")
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
        
    # Add md_engine to sys.path to import cache_builder
    sys.path.insert(0, str(app_dir.parent))
    try:
        from app.md_engine.cache_builder import build_cache
    except ImportError as e:
        print(f"Error importing cache_builder: {e}")
        sys.exit(1)

    print(f"==> Building static website to '{output_dir}'")
    
    # 2. Prepare output directory
    if output_dir.exists():
        print("Cleaning existing output directory...")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Copy public files
    public_dir = app_dir / "public"
    if public_dir.exists():
        print(f"Copying static files from {public_dir}...")
        shutil.copytree(public_dir, output_dir, dirs_exist_ok=True)
    
    # 4. Copy attachments
    attachments_src = data_dir / "_attachments"
    attachments_dst = output_dir / "attachments"
    if attachments_src.exists():
        print(f"Copying attachments from {attachments_src}...")
        shutil.copytree(attachments_src, attachments_dst, dirs_exist_ok=True)
        
    # 5. Build Cache (JSON)
    cache_dir = output_dir / "data_cache"
    print(f"Building JSON cache from {data_dir} to {cache_dir}...")
    build_cache(data_dir, cache_dir)
    
    # 6. Modify app_v2.js (Remove API calls and fix paths)
    js_file = output_dir / "app_v2.js"
    if js_file.exists():
        print(f"Patching {js_file} for static hosting...")
        content = js_file.read_text(encoding='utf-8')
        
        # Change fetch path for cache from ../data_cache/ to ./data_cache/
        content = content.replace("'../data_cache/'", "'./data_cache/'")
        content = content.replace('"../data_cache/"', '"./data_cache/"')
        content = content.replace("`../data_cache/", "`./data_cache/")
        
        # Disable saving API calls by injecting a fetch mock at the top of the file
        fetch_mock = """
// [Static Site] Mock fetch API
const originalFetch = window.fetch;
window.fetch = async function(resource, config) {
    let url = typeof resource === 'string' ? resource : (resource instanceof Request ? resource.url : '');
    if (url && url.includes('/api/')) {
        console.log('[Static Site] Ignored API call to:', url);
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({}),
            text: () => Promise.resolve('{}')
        });
    }
    return originalFetch.call(window, resource, config);
};

"""
        content = fetch_mock + content

        
        js_file.write_text(content, encoding='utf-8')
        
    # 7. Modify index.html (Fix relative paths)
    html_file = output_dir / "index.html"
    if html_file.exists():
        print(f"Patching {html_file} for relative paths...")
        content = html_file.read_text(encoding='utf-8')
        
        # Replace /app_v2.js with ./app_v2.js, /styles.css with ./styles.css, /manifest.json with ./manifest.json
        content = content.replace('src="/app_v2.js"', 'src="./app_v2.js"')
        content = content.replace('href="/styles.css"', 'href="./styles.css"')
        content = content.replace('href="/manifest.json"', 'href="./manifest.json"')
        content = content.replace('href="/favicon.ico"', 'href="./favicon.ico"')
        
        html_file.write_text(content, encoding='utf-8')

    print("==> Static website build completed successfully!")

if __name__ == "__main__":
    main()
