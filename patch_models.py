import urllib.request
import json

data = {
    "video_models": {
        "PAYGATE_TIER_ONE": {
            "frame_2_video": {
                "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
                "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite"
            },
            "start_end_frame_2_video": {
                "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
                "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite"
            }
        },
        "PAYGATE_TIER_TWO": {
            "frame_2_video": {
                "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
                "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite"
            },
            "start_end_frame_2_video": {
                "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_i2v_lite",
                "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_i2v_lite"
            }
        }
    }
}

req = urllib.request.Request(
    "http://127.0.0.1:8100/api/models",
    data=json.dumps(data).encode('utf-8'),
    headers={"Content-Type": "application/json"},
    method="PATCH"
)

with urllib.request.urlopen(req) as response:
    print(response.read().decode('utf-8'))
