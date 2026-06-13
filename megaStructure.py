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
    parser = argparse.ArgumentParser(description="Run FlowKit generation pipeline with robust error handling.")
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
            "name": "great_pyramid",
            "description": "Generating a Great Pyramid video in 9:16 aspect ratio",
            "story": "A slow cinematic reveal of a Great Pyramid.",
            "material": "nano_banana_2",
            "characters": []
        })
        if not proj_res or 'id' not in proj_res:
            raise ApiError("Failed to create project")
        project_id = proj_res['id']
        logger.info(f"Project created: {project_id}")
        request("/api/active-project", method="PUT", data={"project_id": project_id})

        logger.info("Creating video...")
        vid_res = request("/api/videos", data={"project_id": project_id, "title": "Megastructure Video", "display_order": 0})
        if not vid_res or 'id' not in vid_res:
            raise ApiError("Failed to create video")
        video_id = vid_res['id']
        logger.info(f"Video created: {video_id}")
        
        logger.info("Creating scenes from prompts...")
        prompts_file = r"C:\Users\DELL\Desktop\New folder\opensourceChromeExt\flowkit\my_prompt_assets\megastructure\prompts.json"
        
        if not os.path.exists(prompts_file):
            raise PipelineError(f"Prompts file not found: {prompts_file}")
            
        with open(prompts_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                raise PipelineError(f"Prompts file is empty: {prompts_file}")
            prompts = json.loads(content)
            
        # Ensure prompts is a list
        if isinstance(prompts, dict):
            prompts = [prompts]
            
        logger.info("Fetching output directory details...")
        out_dir_res = request(f"/api/projects/{project_id}/output-dir", method="GET")
        if out_dir_res and 'path' in out_dir_res:
            output_dir = out_dir_res['path']
        else:
            output_dir = f"output/great_pyramid"
            
        os.makedirs(f"{output_dir}/scenes", exist_ok=True)
        logger.info(f"Assets will be saved to: {output_dir}/scenes")
        
        # We want 9:16 aspect ratio
        ori = "VERTICAL"
        
        for i, p in enumerate(prompts):
            logger.info(f"--- Processing Scene {i+1}/{len(prompts)} ---")
            
            # 0. Create Scene
            scene_res = request("/api/scenes", data={
                "video_id": video_id,
                "display_order": i,
                "prompt": p.get('img_prompt', ''),
                "video_prompt": p.get('vid_prompt', p.get('video_prompt', '')),
                "narrator_text": p.get('text', ''),
                "character_names": [],
                "chain_type": "ROOT"
            })
            if not scene_res or 'id' not in scene_res:
                maybe_abort(f"Failed to create scene {i+1}")
                continue
                
            sid = scene_res['id']
            logger.info(f"Created scene {i+1}: {sid}")
            
            # 1. Generate Image
            logger.info(f"Submitting GENERATE_IMAGE request ({ori})...")
            batch_res = request("/api/requests/batch", data={"requests": [{
                "type": "GENERATE_IMAGE",
                "scene_id": sid,
                "project_id": project_id,
                "video_id": video_id,
                "orientation": ori
            }]})
            if not batch_res:
                maybe_abort("Image submission failed")
                
            logger.info("Polling GENERATE_IMAGE status...")
            attempts = 0
            while attempts < 60:  # 5 minutes timeout (60 * 5s)
                time.sleep(5)
                attempts += 1
                status_data = request(f"/api/requests/batch-status?video_id={video_id}&type=GENERATE_IMAGE", method="GET")
                if not status_data:
                    continue
                done = status_data.get("done", False)
                if done:
                    break
            if attempts >= 60:
                logger.warning(f"Timeout waiting for image for scene {sid}. Proceeding to check status.")
                    
            # 2. Generate Video
            logger.info(f"Submitting GENERATE_VIDEO request ({ori})...")
            batch_res = request("/api/requests/batch", data={"requests": [{
                "type": "GENERATE_VIDEO",
                "scene_id": sid,
                "project_id": project_id,
                "video_id": video_id,
                "orientation": ori
            }]})
            if not batch_res:
                maybe_abort("Video submission failed")
                
            logger.info("Polling GENERATE_VIDEO status...")
            attempts = 0
            while attempts < 60:  # 10 minutes timeout (60 * 10s)
                time.sleep(10)
                attempts += 1
                status_data = request(f"/api/requests/batch-status?video_id={video_id}&type=GENERATE_VIDEO", method="GET")
                if not status_data:
                    continue
                done = status_data.get("done", False)
                if done:
                    break
            if attempts >= 60:
                logger.warning(f"Timeout waiting for video for scene {sid}. Proceeding to check status.")
                    
            # 3. Download Assets
            scene_data = request(f"/api/scenes/{sid}", method="GET")
            if scene_data:
                # Download Image
                img_status = scene_data.get("vertical_image_status")
                img_url = scene_data.get("vertical_image_url")
                if img_status == "COMPLETED" and img_url and img_url.startswith("http"):
                    dest_file = f"{output_dir}/scenes/scene_{i+1:03d}_{sid}.jpg"
                    logger.info(f"Downloading image {dest_file}...")
                    try:
                        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req) as response, open(dest_file, 'wb') as out_file:
                            out_file.write(response.read())
                    except Exception as e:
                        logger.error(f"Failed to download image: {e}")
                elif img_status == "FAILED":
                    logger.warning(f"Image generation failed for scene {i+1}")
                    
                # Download Video
                vid_status = scene_data.get("vertical_video_status")
                vid_url = scene_data.get("vertical_video_url")
                if vid_status == "COMPLETED" and vid_url:
                    dest_file = f"{output_dir}/scenes/scene_{i+1:03d}_{sid}.mp4"
                    logger.info(f"Downloading video {dest_file}...")
                    try:
                        if vid_url.startswith("http"):
                            req = urllib.request.Request(vid_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(req) as response, open(dest_file, 'wb') as out_file:
                                out_file.write(response.read())
                        elif vid_url.startswith("file://"):
                            import shutil
                            src_file = vid_url.replace("file://", "")
                            shutil.copy(src_file, dest_file)
                    except Exception as e:
                        logger.error(f"Failed to download video: {e}")
                elif vid_status == "FAILED":
                    logger.warning(f"Video generation failed for scene {i+1}")
                    
            # 4. Wait 60 seconds before next scene (if not the last one)
            if i < len(prompts) - 1:
                logger.info("Waiting 60 seconds before processing next scene to avoid unusual activity errors...")
                time.sleep(60)
                
        logger.info("All scenes processed and downloaded successfully.")
        
    except PipelineError as e:
        logger.exception(f"Pipeline encountered an error: {e}")
        if args.stop_on_error:
            raise SystemExit("Pipeline aborted due to error.")

if __name__ == "__main__":
    main()
