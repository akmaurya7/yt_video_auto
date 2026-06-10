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
        logger.info("Creating project...")
        proj_res = request("/api/projects", data={
            "name": "why_brain_is_lying_to_you",
            "description": "Explaining how the brain lies to us",
            "story": "A story about perception, memory, and consciousness.",
            "material": "nano_banana_2",
            "characters": [{"name": "StickFigure", "entity_type": "character", "description": "simple black stick figure, round circle head, thin black lines for body and limbs"}]
        })
        if not proj_res or 'id' not in proj_res:
            raise ApiError("Failed to create project")
        project_id = proj_res['id']
        logger.info(f"Project created: {project_id}")
        request("/api/active-project", method="PUT", data={"project_id": project_id})
        logger.info("Uploading reference image...")
        img_path = r"C:\Users\DELL\Desktop\New folder\opensourceChromeExt\flowkit\my_prompt_assets\base_char.jpg"
        img_res = request("/api/flow/upload-image", data={"file_path": img_path, "file_name": "base_char.jpg", "project_id": project_id})
        if not img_res or 'media_id' not in img_res:
            raise ApiError("Failed to upload image")
        media_id = img_res['media_id']
        logger.info(f"Uploaded image, media_id: {media_id}")
        logger.info("Fetching project characters...")
        chars_res = request(f"/api/projects/{project_id}/characters", method="GET")
        if not chars_res:
            raise ApiError("Failed to fetch characters")
        char_id = next((c.get('id') for c in chars_res if c.get('name') == "StickFigure"), None)
        if not char_id:
            raise ApiError("Character StickFigure not found")
        logger.info(f"Linking media_id to character {char_id}")
        patch_res = request(f"/api/characters/{char_id}", method="PATCH", data={"media_id": media_id})
        if not patch_res or patch_res.get('media_id') != media_id:
            raise ApiError("Failed to link character reference image")
        logger.info("Character reference linked successfully")
        logger.info("Creating video...")
        vid_res = request("/api/videos", data={"project_id": project_id, "title": "Main Video", "display_order": 0})
        if not vid_res or 'id' not in vid_res:
            raise ApiError("Failed to create video")
        video_id = vid_res['id']
        logger.info(f"Video created: {video_id}")
        logger.info("Creating scenes from prompts...")
        prompts_file = r"C:\Users\DELL\Desktop\New folder\opensourceChromeExt\flowkit\my_prompt_assets\prompts.json"
        with open(prompts_file, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
        scene_ids = []
        for i, p in enumerate(prompts):
            use_ref = p.get('use_reference') or p.get('use_references') or False
            chars = ["StickFigure"] if use_ref else []
            scene_res = request("/api/scenes", data={
                "video_id": video_id,
                "display_order": i,
                "prompt": p['prompt'],
                "video_prompt": "",
                "character_names": chars,
                "chain_type": "ROOT"
            })
            if scene_res and 'id' in scene_res:
                scene_ids.append(scene_res['id'])
                logger.info(f"Created scene {i+1}/{len(prompts)}: {scene_res['id']}")
            else:
                maybe_abort(f"Failed to create scene {i+1}")
        logger.info("Fetching output directory details...")
        out_dir_res = request(f"/api/projects/{project_id}/output-dir", method="GET")
        if out_dir_res and 'path' in out_dir_res:
            output_dir = out_dir_res['path']
        else:
            output_dir = f"output/why_brain_is_lying_to_you"
        os.makedirs(f"{output_dir}/scenes", exist_ok=True)
        logger.info(f"Images will be saved to: {output_dir}/scenes")
        for i, sid in enumerate(scene_ids):
            logger.info(f"--- Generating image for scene {i+1}/{len(scene_ids)} (Scene ID: {sid}) ---")
            single_request = {"type": "GENERATE_IMAGE", "scene_id": sid, "project_id": project_id, "video_id": video_id, "orientation": "HORIZONTAL"}
            batch_res = request("/api/requests/batch", data={"requests": [single_request]})
            if not batch_res:
                maybe_abort(f"Batch submission failed for scene {i+1}")
                continue
            logger.info("Request submitted. Polling scene status...")
            while True:
                time.sleep(3)
                scene_data = request(f"/api/scenes/{sid}", method="GET")
                if not scene_data:
                    logger.warning(f"Failed to fetch scene {sid} details, retrying...")
                    continue
                status = scene_data.get("horizontal_image_status")
                img_url = scene_data.get("horizontal_image_url")
                logger.info(f"Scene {i+1} status: {status}")
                if status == "COMPLETED":
                    if img_url and img_url.startswith("http"):
                        dest_file = f"{output_dir}/scenes/scene_{i+1:03d}_{sid}.jpg"
                        logger.info(f"Downloading completed image to {dest_file}...")
                        try:
                            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(req) as response, open(dest_file, 'wb') as out_file:
                                out_file.write(response.read())
                            logger.info("Downloaded successfully")
                        except Exception as e:
                            logger.error(f"Failed to download image: {e}")
                    else:
                        logger.warning(f"Image completed but URL missing/invalid: {img_url}")
                    break
                elif status == "FAILED":
                    maybe_abort(f"Image generation failed for scene {i+1}")
                    break
            if i < len(scene_ids) - 1:
                logger.info("Waiting 20 seconds cooldown before next image...")
                time.sleep(20)
        logger.info("All image generation requests and downloads processed.")
    except PipelineError as e:
        logger.exception(f"Pipeline encountered an error: {e}")
        if args.stop_on_error:
            raise SystemExit("Pipeline aborted due to error.")

if __name__ == "__main__":
    main()
