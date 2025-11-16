import runpod
from runpod.serverless.utils import rp_upload
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import binascii # Import for Base64 error handling


# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CUDA check and configuration
def check_cuda_availability():
    """Check CUDA availability and set environment variables."""
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("✅ CUDA is available and working")
            os.environ['CUDA_VISIBLE_DEVICES'] = '0'
            return True
        else:
            logger.error("❌ CUDA is not available")
            raise RuntimeError("CUDA is required but not available")
    except Exception as e:
        logger.error(f"❌ CUDA check failed: {e}")
        raise RuntimeError(f"CUDA initialization failed: {e}")

# Execute CUDA check
try:
    cuda_available = check_cuda_availability()
    if not cuda_available:
        raise RuntimeError("CUDA is not available")
except Exception as e:
    logger.error(f"Fatal error: {e}")
    logger.error("Exiting due to CUDA requirements not met")
    exit(1)



server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
client_id = str(uuid.uuid4())
def save_data_if_base64(data_input, temp_dir, output_filename):
    """
    Check if input data is a Base64 string, and if so, save it as a file and return the path.
    If it's a regular path string, return it as is.
    """
    # Return as is if input is not a string
    if not isinstance(data_input, str):
        return data_input

    try:
        # Base64 strings will succeed when decoding is attempted
        decoded_data = base64.b64decode(data_input)
        
        # Create directory if it doesn't exist
        os.makedirs(temp_dir, exist_ok=True)
        
        # If decoding succeeds, save as a temporary file
        file_path = os.path.abspath(os.path.join(temp_dir, output_filename))
        with open(file_path, 'wb') as f: # Save in binary write mode ('wb')
            f.write(decoded_data)
        
        # Return the path of the saved file
        print(f"✅ Saved Base64 input to '{file_path}' file.")
        return file_path

    except (binascii.Error, ValueError):
        # If decoding fails, treat as a regular path and return the original value
        print(f"➡️ '{data_input}' will be treated as a file path.")
        return data_input
    
def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info(f"Queueing prompt to: {url}")
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    url = f"http://{server_address}:8188/view"
    logger.info(f"Getting image from: {url}")
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()

def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    logger.info(f"Getting history from: {url}")
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break
        else:
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        images_output = []
        if 'images' in node_output:
            for image in node_output['images']:
                image_data = get_image(image['filename'], image['subfolder'], image['type'])
                # Encode bytes object to base64 to make it JSON serializable
                if isinstance(image_data, bytes):
                    import base64
                    image_data = base64.b64encode(image_data).decode('utf-8')
                images_output.append(image_data)
        output_images[node_id] = images_output

    return output_images

def load_workflow(workflow_path):
    """Load workflow JSON file with error handling."""
    if not os.path.exists(workflow_path):
        error_msg = f"Workflow file not found: {workflow_path}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    try:
        with open(workflow_path, 'r') as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in workflow file {workflow_path}: {e}"
        logger.error(error_msg)
        raise ValueError(error_msg)

def handler(job):
    job_input = job.get("input", {})

    logger.info(f"Received job input: {job_input}")
    task_id = f"task_{uuid.uuid4()}"

    image_input = job_input["image_path"]
    # Use helper function to obtain image file path (Base64 or Path)
    # Image extension is unknown, so assume .jpg or receive it from input
    if image_input == "/example_image.png":
        image_path = "/example_image.png"
    else:
        image_path = save_data_if_base64(image_input, task_id, "input_image.jpg")
    

    # Get the directory where handler.py is located
    handler_dir = os.path.dirname(os.path.abspath(__file__))
    workflow_path = os.path.join(handler_dir, "flux_kontext_example.json")
    logger.info(f"Loading workflow from: {workflow_path}")
    prompt = load_workflow(workflow_path)

    prompt["41"]["inputs"]["image"] = image_path
    prompt["6"]["inputs"]["text"] = job_input["prompt"]
    prompt["25"]["inputs"]["noise_seed"] = job_input["seed"]
    prompt["26"]["inputs"]["guidance"] = job_input["guidance"]
    prompt["27"]["inputs"]["width"] = job_input["width"]
    prompt["27"]["inputs"]["height"] = job_input["height"]
    prompt["30"]["inputs"]["width"] = job_input["width"]
    prompt["30"]["inputs"]["height"] = job_input["height"]

    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    logger.info(f"Connecting to WebSocket: {ws_url}")
    
    # First check if HTTP connection is possible
    http_url = f"http://{server_address}:8188/"
    logger.info(f"Checking HTTP connection to: {http_url}")
    
    # HTTP connection check (max 1 minute)
    max_http_attempts = 180
    for http_attempt in range(max_http_attempts):
        try:
            import urllib.request
            response = urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"HTTP connection successful (attempt {http_attempt+1})")
            break
        except Exception as e:
            logger.warning(f"HTTP connection failed (attempt {http_attempt+1}/{max_http_attempts}): {e}")
            if http_attempt == max_http_attempts - 1:
                raise Exception("Cannot connect to ComfyUI server. Please check if the server is running.")
            time.sleep(1)
    
    ws = websocket.WebSocket()
    # WebSocket connection attempt (max 3 minutes)
    max_attempts = int(180/5)  # 3 minutes (attempt once per second)
    for attempt in range(max_attempts):
        import time
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket connection successful (attempt {attempt+1})")
            break
        except Exception as e:
            logger.warning(f"WebSocket connection failed (attempt {attempt+1}/{max_attempts}): {e}")
            if attempt == max_attempts - 1:
                raise Exception("WebSocket connection timeout (3 minutes)")
            time.sleep(5)
    images = get_images(ws, prompt)
    ws.close()

    # Handle case when no images are generated
    if not images:
        return {"error": "Unable to generate images."}
    
    # Return the first image
    for node_id in images:
        if images[node_id]:
            return {"image": images[node_id][0]}
    
    return {"error": "No images found."}

runpod.serverless.start({"handler": handler})