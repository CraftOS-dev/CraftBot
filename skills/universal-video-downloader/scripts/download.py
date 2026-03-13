import os
import subprocess
import sys
import json
import re

def get_formats(url):
    try:
        # Use --no-playlist to avoid downloading entire playlists
        # Use --quiet to reduce noise
        result = subprocess.run(['yt-dlp', '-j', '--no-playlist', url], capture_output=True, text=True)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        
        data = json.loads(result.stdout)
        formats = data.get('formats', [])
        
        # Simplify formats for the user
        simple_formats = []
        seen_res = set()
        
        # Sort formats by resolution (height) descending
        for f in sorted(formats, key=lambda x: (x.get('height') or 0), reverse=True):
            res = f.get('height')
            ext = f.get('ext')
            # Filter for common video resolutions and skip storyboards
            if res and res > 0 and f.get('vcodec') != 'none':
                res_str = f"{res}p"
                if res_str not in seen_res:
                    simple_formats.append({
                        "format_id": f.get('format_id'),
                        "resolution": res_str,
                        "ext": ext,
                        "note": f.get('format_note') or f.get('resolution')
                    })
                    seen_res.add(res_str)
                    
        return {
            "formats": simple_formats, 
            "title": data.get('title'),
            "duration": data.get('duration_string'),
            "uploader": data.get('uploader')
        }
    except Exception as e:
        return {"error": str(e)}

def download_video(url, format_id, output_filename):
    try:
        # Sanitize filename (remove non-alphanumeric except dots/dashes)
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', output_filename)
        if not safe_name.endswith('.mp4'):
            safe_name += '.mp4'
            
        # Download command
        # We try to merge into mp4 for maximum compatibility
        cmd = [
            'yt-dlp', 
            '-f', f'{format_id}+bestaudio/best', 
            '--merge-output-format', 'mp4', 
            '--no-playlist',
            '-o', safe_name, 
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
            
        if os.path.exists(safe_name):
            return {"success": True, "path": safe_name}
        else:
            return {"error": "File was not created."}
            
    except Exception as e:
        return {"error": str(e)}
    finally:
        # We handle deletion here to ensure it's truly "automatic"
        # but only if we are in download mode and success was true.
        # Actually, it's safer to let the agent do it after the 'message' tool call
        # because if the script deletes it, the 'message' tool won't find the file.
        pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python3 download.py [info|download] [url] [format_id]"}))
        sys.exit(1)
    
    action = sys.argv[1]
    url = sys.argv[2]
    
    if action == "info":
        print(json.dumps(get_formats(url)))
    elif action == "download":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Format ID required for download"}))
            sys.exit(1)
        format_id = sys.argv[3]
        # Use format_id in temp name to avoid collisions
        output = f"dl_{format_id}.mp4"
        print(json.dumps(download_video(url, format_id, output)))
