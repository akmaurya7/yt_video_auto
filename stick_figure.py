# Updated run_pipeline with robust error handling, logging, and CLI options
import urllib.request
import urllib.parse
import json
import os
import time
import logging
import argparse

BASE_URL = "http://127.0.0.1:8100"

# Define custom exception classes
class PipelineError(Exception):
    """Base class for pipeline errors."""
    pass

class NetworkError(PipelineError):
    pass

class ApiError(PipelineError):
    pass

class TimeoutError(PipelineError):
    pass

class InvalidResponseError(PipelineError):
    pass

def configure_logger():
    logger = logging.getLogger("run_pipeline")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    # File handler
    os.makedirs("output", exist_ok=True)
    fh = logging.FileHandler(os.path.join("output", "pipeline.log"))
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger

logger = configure_logger()

def request(endpoint, method="POST", data=None, retries=3, backoff=20):
    """Wrapper for HTTP requests with retry logic.

    Returns parsed JSON on success or raises a PipelineError on failure.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if data is not None:
        data_bytes = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)

    attempt = 0
    while attempt < retries:
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            logger.error(f"HTTPError on {url}: {e.code} {e.reason}")
            raise ApiError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            logger.warning(f"URLError on {url}: {e.reason}, attempt {attempt+1}/{retries}")
            attempt += 1
            if attempt >= retries:
                raise NetworkError(str(e))
            time.sleep(backoff * attempt)
        except Exception as e:
            logger.exception(f"Unexpected error on {url}: {e}")
            raise PipelineError(str(e))
    raise PipelineError("Max retries exceeded")

def check_for_critical_errors(video_id):
    """Queries for failed requests and aborts pipeline if critical errors like UNUSUAL_ACTIVITY are detected."""
    res = request(f"/api/requests?status=FAILED&video_id={video_id}&limit=20", method="GET")
    if not res or not isinstance(res, list):
        return
    for r in res:
        err = r.get('error_message', '')
        if not err:
            continue
        if 'PUBLIC_ERROR_UNUSUAL_ACTIVITY' in err or 'reCAPTCHA evaluation failed' in err:
            logger.error(f"CRITICAL ERROR DETECTED: {err}")
            logger.error("=== FIX (from fk-doctor) ===")
            logger.error("Google flagged the session as bot-like.")
            logger.error("1. Stop the pipeline.")
            logger.error("2. Open Chrome settings -> Remove all cookies for google.com and labs.google.")
            logger.error("3. Reload labs.google/fx/tools/flow and sign back in.")
            logger.error("4. Resume pipeline (server throttles automatically). Wait 1-6 hours if still blocked.")
            raise SystemExit("Aborting pipeline due to UNUSUAL_ACTIVITY error.")
        elif 'PUBLIC_ERROR_USER_QUOTA_REACHED' in err:
            logger.error("CRITICAL ERROR: Daily quota reached. Wait for reset or upgrade tier.")
            raise SystemExit("Aborting pipeline due to quota exhausted.")
        elif 'PUBLIC_ERROR_MODEL_ACCESS_DENIED' in err:
            logger.error("CRITICAL ERROR: Model access denied (tier mismatch). Check credits.")
            raise SystemExit("Aborting pipeline due to model access denied.")

def parse_args():
    parser = argparse.ArgumentParser(description="Run FlowKit image generation pipeline with robust error handling.")
    parser.add_argument("--stop-on-error", action="store_true", help="Abort the entire pipeline on first unrecoverable error.")
    return parser.parse_args()

def main():
    args = parse_args()
    def maybe_abort(message):
        logger.error(message)
        if args.stop_on_error:
            raise SystemExit("Aborting pipeline due to error.")
    try:
        project_name = "evolution"
        projects = request("/api/projects", method="GET")
        existing_proj = next((p for p in projects if p.get('name') == project_name), None)
        
        if existing_proj:
            project_id = existing_proj['id']
            logger.info(f"Resuming existing project: {project_id}")
        else:
            logger.info("Creating new project...")
            proj_res = request("/api/projects", data={
                "name": project_name,
                "description": "evolution",
                "story": "evolution",
                "material": "nano_banana_2",
                "characters": [{"name": "StickFigure", "entity_type": "character", "description": "simple black stick figure, round circle head, thin black lines for body and limbs"}]
            })
            if not proj_res or 'id' not in proj_res:
                raise ApiError("Failed to create project")
            project_id = proj_res['id']
            logger.info(f"Project created: {project_id}")
            
        request("/api/active-project", method="PUT", data={"project_id": project_id})
        
        logger.info("Checking characters...")
        chars_res = request(f"/api/projects/{project_id}/characters", method="GET")
        if not chars_res:
            raise ApiError("Failed to fetch characters")
        char = next((c for c in chars_res if c.get('name') == "StickFigure"), None)
        if not char:
            raise ApiError("Character StickFigure not found")
            
        char_id = char['id']
        media_id = char.get('media_id')
        
        if not media_id:
            logger.info("Uploading reference image...")
            img_path = r"C:\Users\DELL\Desktop\New folder\opensourceChromeExt\flowkit\my_prompt_assets\stick_figure\base_char.jpg"
            img_res = request("/api/flow/upload-image", data={"file_path": img_path, "file_name": "base_char.jpg", "project_id": project_id})
            if not img_res or 'media_id' not in img_res:
                raise ApiError("Failed to upload image")
            media_id = img_res['media_id']
            logger.info(f"Uploaded image, media_id: {media_id}")
            logger.info(f"Linking media_id to character {char_id}")
            patch_res = request(f"/api/characters/{char_id}", method="PATCH", data={"media_id": media_id})
            if not patch_res or patch_res.get('media_id') != media_id:
                raise ApiError("Failed to link character reference image")
            logger.info("Character reference linked successfully")
        else:
            logger.info(f"Character already has media_id: {media_id}")
            
        video_title = "Main Video"
        videos = request(f"/api/videos?project_id={project_id}", method="GET")
        existing_vid = next((v for v in videos if v.get('title') == video_title), None)
        
        if existing_vid:
            video_id = existing_vid['id']
            logger.info(f"Resuming existing video: {video_id}")
        else:
            logger.info("Creating video...")
            vid_res = request("/api/videos", data={"project_id": project_id, "title": video_title, "display_order": 0})
            if not vid_res or 'id' not in vid_res:
                raise ApiError("Failed to create video")
            video_id = vid_res['id']
            logger.info(f"Video created: {video_id}")
            
        logger.info("Fetching output directory details...")
        out_dir_res = request(f"/api/projects/{project_id}/output-dir", method="GET")
        if out_dir_res and 'path' in out_dir_res:
            output_dir = out_dir_res['path']
        else:
            output_dir = f"output/stick_figure/evolution"
        os.makedirs(f"{output_dir}/scenes", exist_ok=True)
        logger.info(f"Images will be saved to: {output_dir}/scenes")

        logger.info("Creating or resuming scenes from prompts...")
        prompts_file = r"C:\Users\DELL\Desktop\New folder\opensourceChromeExt\flowkit\my_prompt_assets\stick_figure\prompts.json"
        with open(prompts_file, 'r', encoding='utf-8') as f:
            prompts = json.load(f)

        existing_scenes = request(f"/api/scenes?video_id={video_id}", method="GET")
        scene_by_order = {s.get('display_order'): s for s in existing_scenes}
        scene_ids = []
        
        for i, p in enumerate(prompts):
            use_ref = p.get('use_reference') or p.get('use_references') or False
            chars = ["StickFigure"] if use_ref else []
            prompt_text = p['prompt']
            
            if i in scene_by_order:
                sid = scene_by_order[i]['id']
                logger.info(f"Resumed scene {i+1}/{len(prompts)}: {sid}. Updating prompts...")
                request(f"/api/scenes/{sid}", method="PATCH", data={
                    "prompt": prompt_text,
                    "character_names": chars
                })
                scene_ids.append(sid)
            else:
                scene_res = request("/api/scenes", data={
                    "video_id": video_id,
                    "display_order": i,
                    "prompt": prompt_text,
                    "video_prompt": "",
                    "character_names": chars,
                    "chain_type": "ROOT"
                })
                if scene_res and 'id' in scene_res:
                    scene_ids.append(scene_res['id'])
                    logger.info(f"Created scene {i+1}/{len(prompts)}: {scene_res['id']}")
                else:
                    maybe_abort(f"Failed to create scene {i+1}")

        logger.info("Checking scene statuses before batch submission...")
        current_scenes = request(f"/api/scenes?video_id={video_id}", method="GET")
        scene_status_map = {s['id']: s.get("horizontal_image_status") for s in current_scenes}

        requests_list = []
        for sid in scene_ids:
            # Skip scenes that are already successfully generated
            if scene_status_map.get(sid) == "COMPLETED":
                continue
            requests_list.append({
                "type": "GENERATE_IMAGE",
                "scene_id": sid,
                "project_id": project_id,
                "video_id": video_id,
                "orientation": "HORIZONTAL"
            })
            
        if requests_list:
            logger.info(f"Submitting {len(requests_list)} new image generation requests...")
            batch_res = request("/api/requests/batch", data={"requests": requests_list})
            if not batch_res:
                maybe_abort("Batch submission failed")
        else:
            logger.info("All scenes are already COMPLETED. No new requests to submit.")
            
        logger.info("Polling scene generation status...")
        while True:
            time.sleep(10)
            
            scenes_data = request(f"/api/scenes?video_id={video_id}", method="GET")
            if not scenes_data:
                continue
                
            status_map = {s['id']: s.get("horizontal_image_status") for s in scenes_data}
            
            total = len(scene_ids)
            completed = 0
            failed = 0
            pending = 0
            
            for sid in scene_ids:
                st = status_map.get(sid)
                if st == "COMPLETED":
                    completed += 1
                elif st == "FAILED":
                    failed += 1
                else:
                    pending += 1
                    
            done = (pending == 0)
            
            logger.info(f"Generation status: {completed}/{total} completed, {failed} failed.")
            
            if failed > 0:
                check_for_critical_errors(video_id)
            
            if done:
                break
                
        logger.info("All image generations finished. Downloading images...")
        
        for i, sid in enumerate(scene_ids):
            scene_data = request(f"/api/scenes/{sid}", method="GET")
            if not scene_data:
                continue
            status = scene_data.get("horizontal_image_status")
            img_url = scene_data.get("horizontal_image_url")
            
            if status == "COMPLETED" and img_url and img_url.startswith("http"):
                dest_file = f"{output_dir}/scenes/scene_{i+1:03d}_{sid}.jpg"
                logger.info(f"Downloading {dest_file}...")
                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req) as response, open(dest_file, 'wb') as out_file:
                        out_file.write(response.read())
                except Exception as e:
                    logger.error(f"Failed to download image: {e}")
            elif status == "FAILED":
                logger.warning(f"Image generation ultimately failed for scene {i+1}")
                
        logger.info("All image downloads processed.")
    except PipelineError as e:
        logger.exception(f"Pipeline encountered an error: {e}")
        if args.stop_on_error:
            raise SystemExit("Pipeline aborted due to error.")

if __name__ == "__main__":
    main()
